"""Vistas de impresión: mandar un tiquete o una tanda de etiquetas.

Todas responden a POST. Imprimir cambia el mundo físico (gasta papel y hace
ruido en el mostrador): si respondiera a GET, cualquier recarga de página o
precarga del navegador sacaría papel solo.
"""
from __future__ import annotations

import logging

from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalogo.consultas import productos_visibles
from core.roles import CAJERO, GERENTE, rol_requerido
from core.tenancy import documento_de_empresa, empresa_actual
from inventario.etiquetas import seleccionar_para_etiquetas
from ventas.models import FacturaVenta

from . import servicio
from .servicio import ErrorDeImpresion

logger = logging.getLogger(__name__)


@rol_requerido(CAJERO, GERENTE)
@require_POST
def tiquete(request, factura_id):
    factura = documento_de_empresa(
        FacturaVenta.objects.select_related("empresa", "sucursal", "cliente")
        .prefetch_related("lineas__producto"),
        request,
        pk=factura_id,
    )
    try:
        servicio.imprimir_tiquete(factura)
    except ErrorDeImpresion as e:
        logger.warning("No se pudo imprimir el tiquete %s: %s", factura.numero, e)
        return JsonResponse({"ok": False, "error": str(e)}, status=503)
    return JsonResponse({"ok": True})


def _a_donde_volver(request):
    """A qué pantalla regresar después de imprimir una tanda.

    Solo se aceptan rutas internas. Un `volver_a` con http:// convertiría el
    formulario en un redirector abierto: alguien podría mandarle al personal un
    enlace que imprime y de paso lo saca a un sitio ajeno con pinta de ERP."""
    destino = (request.POST.get("volver_a") or "").strip()
    if destino.startswith("/") and not destino.startswith("//"):
        return destino
    return "inventario:etiquetas"


@rol_requerido(CAJERO, GERENTE)
@require_POST
def etiquetas(request):
    """Imprime en el rollo la misma selección que muestra la pantalla.

    Los filtros llegan por POST con los mismos nombres que usa la pantalla de
    etiquetas, así que lo que se ve en el navegador y lo que sale del rollo no
    se pueden desincronizar: los decide la misma función."""
    seleccion = seleccionar_para_etiquetas(empresa_actual(request), request.POST)
    destino = _a_donde_volver(request)
    if not seleccion.pares:
        messages.warning(request, "No hay etiquetas que imprimir con esos filtros.")
        return redirect(destino)
    try:
        total = servicio.imprimir_etiquetas(seleccion.pares)
    except ErrorDeImpresion as e:
        messages.error(request, f"⛔ {e}")
        return redirect(destino)
    aviso = f"🏷️ {total} etiqueta(s) enviadas a la impresora."
    if seleccion.recortado:
        aviso += " La selección se cortó en el tope; repetí para la siguiente tanda."
    messages.success(request, aviso)
    return redirect(destino)


def _producto_de_la_empresa(request, producto_id):
    """El producto, siempre acotado a la empresa de la sesión.

    Incluye los agotados a propósito: la pantalla de etiquetas se usa para el
    conteo físico, donde el producto en cero es justamente el que hay que ir a
    verificar (ver inventario.views.etiquetas)."""
    return get_object_or_404(
        productos_visibles(empresa_actual(request), incluir_agotados=True),
        pk=producto_id,
    )


@rol_requerido(CAJERO, GERENTE)
@require_POST
def etiqueta_producto(request, producto_id):
    """Imprime N etiquetas de UN producto. Es el camino del conteo físico."""
    producto = _producto_de_la_empresa(request, producto_id)
    try:
        copias = max(1, min(50, int(request.POST.get("copias", "1"))))
    except (TypeError, ValueError):
        copias = 1
    try:
        servicio.imprimir_etiqueta(producto, copias)
    except ErrorDeImpresion as e:
        logger.warning("No se pudo imprimir la etiqueta de %s: %s", producto.sku, e)
        return JsonResponse({"ok": False, "error": str(e)}, status=503)
    return JsonResponse({"ok": True, "copias": copias})


@rol_requerido(CAJERO, GERENTE)
def codigo_png(request, producto_id):
    """El código de barras del producto, como imagen, para verlo en pantalla.

    Se sirve como imagen y no incrustado en la página a propósito: dibujar los
    532 códigos del catálogo dentro del HTML son varios megabytes y la pantalla
    tarda en abrir. Así el navegador pide solo los que se están viendo
    (`loading="lazy"`) y los guarda en su caché."""
    producto = _producto_de_la_empresa(request, producto_id)
    if not producto.codigo_barras:
        raise Http404("El producto no tiene código de barras.")
    from .etiqueta import imagen_codigo_barras

    # Se dibuja con el ancho real del rollo para que lo que se ve en pantalla
    # tenga las mismas barras que va a salir en papel.
    imagen = imagen_codigo_barras(
        str(producto.codigo_barras), ancho_mm=settings.ETIQUETA_ANCHO_MM, alto_px=64
    )
    memoria = BytesIO()
    imagen.save(memoria, "PNG")
    respuesta = HttpResponse(memoria.getvalue(), content_type="image/png")
    # Privada: es dato de la empresa, no debe quedar en caché de intermediarios.
    respuesta["Cache-Control"] = "private, max-age=86400"
    return respuesta


@rol_requerido(GERENTE)
def estado(request):
    """Pantalla de comprobación: qué ve el ERP y una impresión de prueba."""
    datos = servicio.diagnostico()
    if request.method == "POST":
        que = request.POST.get("probar")
        try:
            if que == "recibos":
                from .prueba import prueba_recibos
                prueba_recibos()
                messages.success(request, "Prueba enviada a la impresora de recibos.")
            elif que == "etiquetas":
                from .prueba import prueba_etiquetas
                prueba_etiquetas()
                messages.success(request, "Etiqueta de prueba enviada.")
        except ErrorDeImpresion as e:
            messages.error(request, f"⛔ {e}")
        return redirect("impresion:estado")
    return render(request, "impresion/estado.html", {"d": datos, "title": "Impresoras"})
