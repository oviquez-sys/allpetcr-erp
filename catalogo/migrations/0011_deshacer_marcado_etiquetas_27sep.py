"""Deshace el «marcar visibles como impresas» del 27/09/2026, una sola vez.

Ese día un clic con el buscador vacío marcó el catálogo entero como
«etiqueta puesta». Se arregla con una migración y no con un .bat porque el
.bat necesita entrar directo a la base, y la base solo deja entrar a las
direcciones de internet de su lista: la de la tienda había cambiado y no
había forma de correrlo. Oscar autorizó correrlo así, sin vista previa.

Misma lógica que `manage.py deshacer_marcado_etiquetas` (ver ahí el porqué),
limitada a los lotes de ESE día para no tocar ningún marcado anterior.
"""
from datetime import date
from zoneinfo import ZoneInfo

from django.db import migrations
from django.db.models import Count, Max

DIA_DEL_ERROR = date(2026, 9, 27)
MINIMO_LOTE = 20
COSTA_RICA = ZoneInfo("America/Costa_Rica")


def deshacer(apps, schema_editor):
    Producto = apps.get_model("catalogo", "Producto")
    TrabajoImpresion = apps.get_model("impresion", "TrabajoImpresion")

    lotes = [
        fila["etiqueta_impresa_en"]
        for fila in Producto.objects.filter(etiqueta_impresa_en__isnull=False)
        .values("etiqueta_impresa_en").annotate(n=Count("id")).filter(n__gte=MINIMO_LOTE)
        if fila["etiqueta_impresa_en"].astimezone(COSTA_RICA).date() == DIA_DEL_ERROR
    ]
    if not lotes:
        return
    impresas = {
        fila["titulo"].removeprefix("Etiqueta ").strip(): fila["cuando"]
        for fila in TrabajoImpresion.objects.filter(tipo="etiqueta", estado="impreso")
        .values("titulo").annotate(cuando=Max("terminado_en"))
    }
    productos = list(Producto.objects.filter(etiqueta_impresa_en__in=lotes))
    for p in productos:
        p.etiqueta_impresa_en = impresas.get(p.sku)
    Producto.objects.bulk_update(productos, ["etiqueta_impresa_en"])


class Migration(migrations.Migration):
    dependencies = [
        ("catalogo", "0010_ficha_alimento"),
        ("impresion", "0001_initial"),
    ]

    # Sin vuelta atrás: el estado anterior al error no se puede reconstruir.
    operations = [migrations.RunPython(deshacer, migrations.RunPython.noop)]
