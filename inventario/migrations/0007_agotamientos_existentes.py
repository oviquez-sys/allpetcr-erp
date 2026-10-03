"""Crea el aviso para lo que ya estaba agotado el día que nace la función.

Sin esto la lista arrancaría vacía y los productos que se agotaron antes del
02/10/2026 seguirían escondidos (la regla del 02/08 oculta todo lo que tiene
stock cero). Solo entran los que de verdad tuvieron existencia y salieron:
su último movimiento es una salida que los dejó en cero. Se salta la
anulación de una compra: eso corrige un error de digitación, no es un
producto que se vendió hasta acabarse.
"""
from django.db import migrations

SALIDAS = ("VEN", "REG", "AJU", "TRA")


def crear(apps, schema_editor):
    Producto = apps.get_model("catalogo", "Producto")
    Movimiento = apps.get_model("inventario", "MovimientoInventario")
    Agotamiento = apps.get_model("inventario", "Agotamiento")
    for producto in Producto.objects.filter(stock_actual=0, activo=True).iterator():
        ultimo = Movimiento.objects.filter(producto=producto).order_by("-fecha", "-id").first()
        if ultimo is None or ultimo.cantidad >= 0 or ultimo.stock_resultante != 0:
            continue
        if ultimo.tipo not in SALIDAS:
            continue
        if Agotamiento.objects.filter(producto=producto, repuesto_en__isnull=True).exists():
            continue
        Agotamiento.objects.create(
            producto=producto, movimiento=ultimo, tipo_salida=ultimo.tipo, fecha=ultimo.fecha,
        )


class Migration(migrations.Migration):
    dependencies = [("inventario", "0006_agotamiento")]

    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
