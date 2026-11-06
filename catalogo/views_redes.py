"""Pantalla «Catálogo para redes» (06/11/2026). Solo gerente.

El .zip se arma en un hilo aparte (catalogo/redes.py tarda minutos con todo
el catálogo y gunicorn corta las páginas a los 120 s). La pantalla pregunta
cada pocos segundos cómo va. Si el servidor se reinicia a mitad de camino el
hilo muere: a los 30 minutos un paquete que sigue «armando» se da por perdido
y se puede volver a pedir.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.db import close_old_connections, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.roles import GERENTE, rol_requerido
from core.tenancy import empresa_actual

from .models import Categoria, PaqueteRedes

logger = logging.getLogger(__name__)
MINUTOS_PERDIDO = 30
GUARDAR_ULTIMOS = 5


def _perdidos(empresa):
    limite = timezone.now() - timedelta(minutes=MINUTOS_PERDIDO)
    PaqueteRedes.objects.filter(empresa=empresa, estado=PaqueteRedes.Estado.ARMANDO, creado_en__lt=limite) \
        .update(estado=PaqueteRedes.Estado.ERROR, error="Se interrumpió (probablemente el servidor se reinició). "
                                                         "Generalo de nuevo.", terminado_en=timezone.now())


def _armar(pk):
    """Corre en el hilo. Cierra conexiones al empezar y al terminar: el hilo
    tiene su propia conexión a la base."""
    from . import redes
    close_old_connections()
    try:
        paquete = PaqueteRedes.objects.select_related("empresa").get(pk=pk)

        def progreso(hechos, total):
            PaqueteRedes.objects.filter(pk=pk).update(hechos=hechos, total=total)

        archivo, n, sin_foto, fallaron = redes.generar(paquete, progreso)
        if n == 0:
            default_storage.delete(archivo)
            PaqueteRedes.objects.filter(pk=pk).update(
                estado=PaqueteRedes.Estado.ERROR, sin_foto=sin_foto, terminado_en=timezone.now(),
                error=f"Ningún producto con foto cumple esos filtros ({sin_foto} sin foto quedaron fuera).")
            return
        PaqueteRedes.objects.filter(pk=pk).update(
            estado=PaqueteRedes.Estado.LISTO, archivo=archivo, productos=n, sin_foto=sin_foto,
            error=(f"No se pudo abrir la foto de: {', '.join(fallaron)}" if fallaron else ""),
            terminado_en=timezone.now())
        _limpiar_viejos(paquete.empresa)
    except Exception as e:  # noqa: BLE001 — el error queda a la vista en la pantalla
        logger.exception("Catálogo para redes %s falló", pk)
        PaqueteRedes.objects.filter(pk=pk).update(estado=PaqueteRedes.Estado.ERROR, error=str(e)[:500],
                                                  terminado_en=timezone.now())
    finally:
        close_old_connections()


def _limpiar_viejos(empresa):
    """Se guardan los últimos 5: cada .zip pesa decenas de megas."""
    viejos = PaqueteRedes.objects.filter(empresa=empresa, estado=PaqueteRedes.Estado.LISTO) \
        .order_by("-creado_en")[GUARDAR_ULTIMOS:]
    for p in viejos:
        if p.archivo:
            try:
                default_storage.delete(p.archivo)
            except Exception:  # noqa: BLE001
                logger.warning("No se pudo borrar %s", p.archivo)
        p.delete()


def _lanzar(pk):
    if getattr(settings, "CATALOGO_REDES_EN_HILO", True):
        threading.Thread(target=_armar, args=(pk,), daemon=True, name=f"catalogo-redes-{pk}").start()
    else:
        _armar(pk)          # pruebas: todo en el mismo hilo


@rol_requerido(GERENTE)
def catalogo_redes(request):
    empresa = empresa_actual(request)
    _perdidos(empresa)
    if request.method == "POST":
        if PaqueteRedes.objects.filter(empresa=empresa, estado=PaqueteRedes.Estado.ARMANDO).exists():
            messages.info(request, "Ya se está armando uno. Esperá a que termine.")
            return redirect("catalogo:redes")
        try:
            categoria_id = int(request.POST.get("categoria") or 0) or None
        except ValueError:
            categoria_id = None
        paquete = PaqueteRedes.objects.create(
            empresa=empresa, creado_por=request.user,
            filtros={"solo_existencia": request.POST.get("solo_existencia") == "1",
                     "con_precio": request.POST.get("con_precio") == "1",
                     "solo_ofertas": request.POST.get("solo_ofertas") == "1",
                     "categoria_id": categoria_id})
        transaction.on_commit(lambda: _lanzar(paquete.pk))
        return redirect("catalogo:redes")
    paquetes = list(PaqueteRedes.objects.filter(empresa=empresa).select_related("creado_por")[:GUARDAR_ULTIMOS + 2])
    categorias = {c.pk: c.nombre for c in Categoria.objects.filter(padre__isnull=True)}
    for p in paquetes:
        p.categoria_nombre = categorias.get((p.filtros or {}).get("categoria_id"), "Todas")
    return render(request, "catalogo/catalogo_redes.html", {
        "paquetes": paquetes,
        "armando": any(p.estado == PaqueteRedes.Estado.ARMANDO for p in paquetes),
        "categorias": Categoria.objects.filter(padre__isnull=True).order_by("orden", "nombre"),
    })


@rol_requerido(GERENTE)
def catalogo_redes_estado(request, pk):
    p = get_object_or_404(PaqueteRedes, pk=pk, empresa=empresa_actual(request))
    return JsonResponse({"estado": p.estado, "hechos": p.hechos, "total": p.total})


@rol_requerido(GERENTE)
def catalogo_redes_descargar(request, pk):
    p = get_object_or_404(PaqueteRedes, pk=pk, empresa=empresa_actual(request), estado=PaqueteRedes.Estado.LISTO)
    if not p.archivo or not default_storage.exists(p.archivo):
        raise Http404("El archivo ya no existe. Generá uno nuevo.")
    url = default_storage.url(p.archivo)
    if url.startswith("http"):
        return redirect(url)          # en el servidor: directo del almacén, sin pasar por el ERP
    nombre = p.archivo.rsplit("/", 1)[-1]
    return FileResponse(default_storage.open(p.archivo, "rb"), as_attachment=True, filename=nombre)
