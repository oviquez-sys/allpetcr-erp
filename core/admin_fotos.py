"""Columna "Foto" para cualquier tabla del admin que mencione un producto.

Uso:  foto = columna_foto("producto")            en el ModelAdmin / Inline
      list_display = ("foto", "producto", ...)    o en readonly_fields/fields
Para llegar al producto por una relación: columna_foto("linea_venta.producto").
"""
from django.contrib import admin

from core.templatetags.fotos import foto_producto


def columna_foto(ruta="producto", tam=36):
    partes = ruta.split(".")

    @admin.display(description="Foto")
    def foto(self, obj):
        p = obj
        for parte in partes:
            p = getattr(p, parte, None)
            if p is None:
                break
        return foto_producto(p, tam, "clickable-product-img")

    return foto
