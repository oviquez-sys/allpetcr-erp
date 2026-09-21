"""Asigna la tarifa general de IVA (13 %) a los productos que no tienen.

20/09/2026: AllPetCR resultó ser régimen tradicional desde el primer día, y
ningún producto tenía tarifa cargada. Todo lo que vende la tienda (comida
para perros y gatos, arneses, correas, ropa, higiene, juguetes) lleva 13 %
según el catálogo CABYS oficial de Hacienda — ver
catalogo.models.TARIFA_GENERAL_IVA.

Solo toca productos SIN tarifa: si alguien ya asignó una (por ejemplo, una
reducida confirmada por el contador), se respeta. Reutiliza una tarifa de
13 % existente en vez de crear un duplicado.

No cambia ningún precio ni ninguna venta pasada. Mientras la empresa esté en
régimen simplificado, la tarifa no se usa para desglosar nada.
"""
from decimal import Decimal

from django.db import migrations


def asignar_iva_general(apps, schema_editor):
    Impuesto = apps.get_model("catalogo", "Impuesto")
    Producto = apps.get_model("catalogo", "Producto")
    if not Producto.objects.filter(impuesto__isnull=True).exists():
        return
    iva = Impuesto.objects.filter(tarifa=Decimal("13.00")).order_by("id").first()
    if iva is None:
        iva = Impuesto.objects.create(nombre="IVA general", tarifa=Decimal("13.00"))
    Producto.objects.filter(impuesto__isnull=True).update(impuesto=iva)


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0006_categoria_orden"),
    ]

    operations = [
        # Reversa vacía a propósito: al deshacer no se sabe qué productos
        # tenían la tarifa desde antes, y quitársela a todos sería peor.
        migrations.RunPython(asignar_iva_general, migrations.RunPython.noop),
    ]
