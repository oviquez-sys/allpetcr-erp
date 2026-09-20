"""`/foto/<id>/`: respaldo que genera la miniatura que falte.

Lo pide el navegador (static/js/fotos.js) SOLO cuando la miniatura no cargó.
En régimen normal nadie pasa por acá: las páginas apuntan directo al bucket.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseNotFound, HttpResponseRedirect
from django.views.decorators.cache import never_cache

from catalogo.models import Producto

from .imagenes import generar_miniatura, url_imagen_producto, url_miniatura
from .tenancy import documento_de_empresa


@never_cache
@staff_member_required
def foto_producto(request, pk):
    producto = documento_de_empresa(Producto, request, pk=pk)
    if not producto.imagen:
        return HttpResponseNotFound("Producto sin foto")
    if generar_miniatura(producto.imagen):
        return HttpResponseRedirect(url_miniatura(producto.imagen, producto.actualizado_en))
    # No se pudo miniaturizar (original ausente o dañado): se entrega el
    # original y, si tampoco existe, el navegador pondrá la huella 🐾.
    return HttpResponseRedirect(url_imagen_producto(producto.imagen))
