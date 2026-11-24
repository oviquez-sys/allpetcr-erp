"""Catálogo de WhatsApp por Meta (24/11/2026, ver catalogo/meta.py).

Dos vistas:
- `feed`: el CSV que descarga Meta. Es PÚBLICA a propósito, porque Meta no
  inicia sesión; la protege la clave de la dirección, que es de una empresa.
- `pantalla`: el gerente copia de ahí el enlace para pegarlo en Meta, ve si
  Meta ya lo leyó y revisa cómo quedan los textos.
"""
from django.conf import settings
from django.contrib import messages
from django.db.models import F
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_safe

from core.roles import GERENTE, rol_requerido
from core.tenancy import empresa_actual

from . import meta
from .models import CatalogoMeta, _clave_catalogo_meta
from .redes import _crc

MUESTRA = 6


@require_safe
def feed(request, clave):
    conf = CatalogoMeta.objects.select_related("empresa").filter(clave=clave, activo=True).first()
    if conf is None:
        raise Http404
    datos = meta.csv_meta(conf.empresa, conf.linea_entrega)
    # Solo cuenta como lectura de Meta si no es alguien del ERP revisando.
    if not request.user.is_authenticated:
        CatalogoMeta.objects.filter(pk=conf.pk).update(ultima_lectura=timezone.now(), lecturas=F("lecturas") + 1)
    respuesta = HttpResponse(datos, content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = 'inline; filename="catalogo-whatsapp.csv"'
    respuesta["X-Robots-Tag"] = "noindex"
    respuesta["Cache-Control"] = "no-store"
    return respuesta


@rol_requerido(GERENTE)
def pantalla(request):
    empresa = empresa_actual(request)
    conf, _ = CatalogoMeta.objects.get_or_create(empresa=empresa)
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "entrega":
            conf.linea_entrega = (request.POST.get("linea_entrega") or "").strip()[:500]
            conf.save(update_fields=["linea_entrega"])
            messages.success(request, "Listo. WhatsApp lo muestra cuando Meta vuelva a leer el enlace (una vez al día).")
        elif accion == "clave":
            conf.clave = _clave_catalogo_meta()
            conf.save(update_fields=["clave"])
            messages.success(request, "Enlace nuevo. Pegalo en Meta: el anterior ya no funciona.")
        return redirect("catalogo:redes_whatsapp")

    items, fuera_salud, sin_foto = meta.seleccion(empresa)
    cierre = meta.cierre(empresa, conf.linea_entrega)
    muestra = [{"titulo": meta.titulo(i.producto), "precio": _crc(i.precio), "antes": _crc(i.oferta["precio_antes"]) if i.oferta else "",
                "descripcion": meta.descripcion(i, cierre), "sku": i.producto.sku,
                "agotado": i.producto.stock_actual <= 0} for i in items[:MUESTRA]]
    return render(request, "catalogo/catalogo_whatsapp.html", {
        "conf": conf,
        "enlace": settings.ERP_URL.rstrip("/") + reverse("catalogo:feed_meta", args=[conf.clave]),
        "total": len(items),
        "agotados": sum(1 for i in items if i.producto.stock_actual <= 0),
        "fuera_salud": fuera_salud,
        "sin_foto": sin_foto,
        "muestra": muestra,
        "con_campana": bool(cierre.envio_bajo or cierre.sorteo_bajo),
    })
