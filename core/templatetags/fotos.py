"""{% foto_producto producto 44 %} — la foto de un producto, igual en todo el ERP.

Regla de Oscar (20/09/2026): "siempre que hablemos de un producto quiero
poder ver la imagen". Para que eso se cumpla en cada pantalla —y siga
cumpliéndose en las que se hagan después— la foto se dibuja SIEMPRE con
este tag, nunca armando la URL a mano en la plantilla.

Armarla a mano fue justamente el error que dejó fotos rotas en producción:
`{{ MEDIA_URL }}{{ p.imagen }}` da "/media/productos/x.jpeg", que existe en
la computadora de Oscar pero NO en el servidor, donde las fotos viven en el
bucket. `core/test_fotos.py` verifica que ese patrón no vuelva a aparecer.

Qué dibuja: la miniatura (rápida, perezosa), con la foto grande en
`data-grande` para ampliarla con un clic, y `data-respaldo` para que
static/js/fotos.js la regenere si falta. Sin foto: una huella 🐾 del mismo
tamaño, para que las filas no bailen.

Registrado como builtin en settings (no hace falta {% load %}).
"""
from django import template
from django.utils.html import format_html

from core.imagenes import datos_foto

register = template.Library()


@register.simple_tag
def foto_producto(producto, tam=44, clase=""):
    tam = int(tam)
    radio = max(6, tam // 5)
    estilo = f"width:{tam}px;height:{tam}px;border-radius:{radio}px"
    d = datos_foto(producto) if producto is not None else {"miniatura": ""}
    if not d["miniatura"]:
        return format_html(
            '<span class="foto-prod vacia {}" style="{};font-size:{}px" title="Sin foto">🐾</span>',
            clase, estilo, max(12, tam // 2),
        )
    return format_html(
        '<img class="foto-prod clickable-product-img {}" src="{}" data-grande="{}" data-respaldo="{}" '
        'alt="{}" width="{}" height="{}" loading="lazy" decoding="async" style="{}">',
        clase, d["miniatura"], d["imagen"], d["respaldo"], getattr(producto, "nombre", ""), tam, tam, estilo,
    )
