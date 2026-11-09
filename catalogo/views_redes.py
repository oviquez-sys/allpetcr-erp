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


# ---------------------------------------------------------------------------
# Publicaciones de alimentos (09/11/2026, prototipo aprobado por Oscar)
# ---------------------------------------------------------------------------
# Segunda pestaña de la misma pantalla. El paquete de arriba hace TODO el
# catálogo de una vez; esta sirve para elegir unos pocos alimentos, ver cómo
# quedan, escoger el beneficio y bajar solo los aprobados.
#
# Solo lee: no cambia precios, inventario ni fichas. Cada vista previa lleva
# una «huella» de los datos con que se dibujó (precio, promoción, ficha,
# foto); si al descargar la huella ya no coincide, esa publicación se marca
# «Desactualizada» y no se descarga hasta volver a verla.
MAX_SELECCION = 24
MAX_LISTA = 80


def _alimentos(empresa, *, q="", especie="", marca="", solo_existencia=True):
    from django.db.models import Q

    from .models import Producto
    from .palabras_clave import filtrar
    qs = Producto.objects.filter(empresa=empresa, activo=True, precio_venta__gt=0).filter(
        Q(ficha_alimento__isnull=False) | Q(categoria__nombre__iexact="Alimento")
        | Q(categoria__padre__nombre__iexact="Alimento"))
    if solo_existencia:
        qs = qs.filter(stock_actual__gt=0)
    if marca:
        qs = qs.filter(marca__iexact=marca)
    if especie:
        qs = qs.filter(Q(ficha_alimento__especie=especie.lower()) | Q(mascota__icontains=especie))
    qs = qs.select_related("ficha_alimento", "categoria__padre").order_by("marca", "nombre")
    return filtrar(qs, q) if q.strip() else list(qs)


def _precio_hoy(producto, promos):
    from .promociones import oferta_de
    oferta = oferta_de(producto, promos[producto.pk]) if producto.pk in promos else None
    return (oferta["precio"] if oferta else producto.precio_venta), oferta


def _tarjetas(empresa, ids, formatos, *, claves=None, aprobadas=(), desactualizadas=()):
    """Una tarjeta por producto elegido, con lo que necesita la vista previa."""
    from . import publicacion
    from .models import Producto
    from .promociones import vigentes
    productos = {p.pk: p for p in Producto.objects.filter(empresa=empresa, pk__in=ids)
                 .select_related("ficha_alimento")}
    promos = vigentes(empresa, productos=productos.keys())
    salida = []
    for pk in ids:
        p = productos.get(pk)
        if p is None:
            continue
        precio, oferta = _precio_hoy(p, promos)
        ficha = publicacion.ficha_publicable(p)
        opciones = [b for b in (ficha.beneficios or []) if b.get("texto")] if ficha else []
        elegidas = (claves or {}).get(pk)
        if elegidas is None:
            elegidas = [b.get("clave") for b in opciones[:publicacion.MAX_BENEFICIOS]]
        salida.append({
            "p": p, "precio": precio, "oferta": oferta, "con_ficha": ficha is not None,
            "huella": publicacion.huella(p, precio=precio, oferta=oferta),
            "beneficios": [{"clave": b.get("clave"), "texto": b["texto"], "on": b.get("clave") in elegidas}
                           for b in opciones],
            "b": ",".join(elegidas), "tiene_foto": bool(p.imagen), "formatos": formatos,
            "aprobada": pk in aprobadas, "desactualizada": pk in desactualizadas,
        })
    return salida


def _ids(valores):
    salida = []
    for v in valores:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n not in salida:
            salida.append(n)
    return salida[:MAX_SELECCION]


def _formatos(valores):
    from .publicacion import FORMATOS
    return [f for f in ("feed", "story") if f in valores and f in FORMATOS] or ["feed", "story"]


@rol_requerido(GERENTE)
def publicaciones_alimentos(request):
    from .models import Producto
    empresa = empresa_actual(request)
    datos = request.POST if request.method == "POST" else request.GET
    formatos = _formatos(datos.getlist("fmt"))
    ids = _ids(datos.getlist("sel"))
    buscando = request.method == "GET" and "buscar" in request.GET
    contexto = {"formatos": formatos, "max": MAX_SELECCION}

    if request.method == "POST":
        aprobadas = [pk for pk in _ids(request.POST.getlist("ap")) if pk in ids]
        claves = {pk: [c for c in request.POST.getlist(f"b_{pk}") if c] for pk in ids}
        if not aprobadas:
            messages.info(request, "Aprobá al menos una publicación antes de descargar.")
            contexto["tarjetas"] = _tarjetas(empresa, ids, formatos, claves=claves)
            return render(request, "catalogo/publicaciones_alimentos.html", contexto)
        tarjetas = _tarjetas(empresa, ids, formatos, claves=claves, aprobadas=aprobadas)
        viejas = [t["p"].pk for t in tarjetas
                  if t["p"].pk in aprobadas and t["huella"] != request.POST.get(f"h_{t['p'].pk}")]
        if viejas:
            # Cambió el precio, la promoción, la ficha o la foto después de la
            # vista previa: se vuelve a mostrar con los datos de ahora y NO se
            # descarga nada hasta que la miren de nuevo.
            messages.warning(request, "Algo cambió desde la vista previa (precio, promoción, ficha o foto). "
                                      "Revisá las marcadas como «Desactualizada» y aprobalas de nuevo.")
            contexto["tarjetas"] = _tarjetas(empresa, ids, formatos, claves=claves,
                                             aprobadas=[a for a in aprobadas if a not in viejas],
                                             desactualizadas=viejas)
            return render(request, "catalogo/publicaciones_alimentos.html", contexto)
        return _zip_publicaciones([t for t in tarjetas if t["aprobada"]], formatos, claves)

    if ids and not buscando:
        contexto["tarjetas"] = _tarjetas(empresa, ids, formatos)
        return render(request, "catalogo/publicaciones_alimentos.html", contexto)

    q, especie, marca = datos.get("q", ""), datos.get("especie", ""), datos.get("marca", "")
    solo_existencia = datos.get("todos") != "1"
    lista = _alimentos(empresa, q=q, especie=especie, marca=marca, solo_existencia=solo_existencia)
    marcas = (Producto.objects.filter(empresa=empresa, activo=True).exclude(marca="")
              .filter(ficha_alimento__isnull=False).values_list("marca", flat=True).distinct().order_by("marca"))
    from .publicacion import ficha_publicable
    en_lista = {p.pk for p in lista[:MAX_LISTA]}
    # Lo ya elegido que no sale en esta búsqueda se conserva (va arriba).
    previos = [p for p in Producto.objects.filter(empresa=empresa, pk__in=ids).select_related("ficha_alimento")
               if p.pk not in en_lista]
    filas = [{"p": p, "con_ficha": ficha_publicable(p) is not None, "on": p.pk in ids}
             for p in previos + lista[:MAX_LISTA]]
    contexto.update({"filas": filas, "total": len(lista), "q": q, "especie": especie, "marca": marca,
                     "marcas": list(marcas), "todos": not solo_existencia, "lista_max": MAX_LISTA})
    return render(request, "catalogo/publicaciones_alimentos.html", contexto)


def _zip_publicaciones(tarjetas, formatos, claves):
    import io
    import zipfile

    from django.http import HttpResponse

    from . import publicacion, redes
    hoy = timezone.localdate()
    carpeta = f"AllPetcr_publicaciones_{hoy:%Y-%m-%d}"
    destino = {"feed": "Publicaciones_1080x1350", "story": "Estados_1080x1920"}
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_STORED) as z:
        for t in tarjetas:
            p = t["p"]
            if not p.imagen:
                continue
            foto = redes._abrir_foto(p)
            d = publicacion.datos(p, precio=t["precio"], oferta=t["oferta"], fecha=hoy,
                                  claves_beneficio=claves.get(p.pk))
            nombre = redes._limpio(f"{p.sku} {p.nombre}") + ".jpg"
            for f in formatos:
                im, _ = publicacion.dibujar(f, d, foto)
                b = io.BytesIO()
                im.save(b, "JPEG", quality=90, optimize=True)
                z.writestr(f"{carpeta}/{destino[f]}/{nombre}", b.getvalue())
    r = HttpResponse(salida.getvalue(), content_type="application/zip")
    r["Content-Disposition"] = f'attachment; filename="{carpeta}.zip"'
    return r


@rol_requerido(GERENTE)
def publicacion_imagen(request, pk, formato):
    """La vista previa: se dibuja al pedirla, no se guarda nada."""
    import io

    from django.http import HttpResponse

    from . import publicacion, redes
    from .models import Producto
    from .promociones import vigentes
    if formato not in publicacion.FORMATOS:
        raise Http404
    empresa = empresa_actual(request)
    p = get_object_or_404(Producto.objects.select_related("ficha_alimento"), pk=pk, empresa=empresa)
    if not p.imagen:
        raise Http404("Este producto no tiene foto.")
    precio, oferta = _precio_hoy(p, vigentes(empresa, productos=[p.pk]))
    claves = None
    if "b" in request.GET:
        claves = [c for c in request.GET["b"].split(",") if c]
    d = publicacion.datos(p, precio=precio, oferta=oferta, fecha=timezone.localdate(), claves_beneficio=claves)
    im, _ = publicacion.dibujar(formato, d, redes._abrir_foto(p))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=82)
    r = HttpResponse(b.getvalue(), content_type="image/jpeg")
    r["Cache-Control"] = "no-store"
    return r
