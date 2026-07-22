"""Asigna un código de barras único a los productos que no tengan uno.

- No toca los productos que ya traen código (p. ej. el EAN del proveedor).
- Para los vacíos, usa el SKU como código (es único y numérico, y una pistola
  lectora Code128 lo lee sin problema).
- Si por alguna razón el SKU ya está usado como código de otro producto, le
  agrega un sufijo para garantizar unicidad.

Uso:
    python manage.py asignar_codigos_barras
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import Producto


class Command(BaseCommand):
    help = "Rellena el código de barras vacío de cada producto (usa el SKU)"

    @transaction.atomic
    def handle(self, *args, **opts):
        usados = set(
            Producto.objects.exclude(codigo_barras="").values_list("codigo_barras", flat=True)
        )
        asignados = 0
        for p in Producto.objects.filter(codigo_barras=""):
            codigo = str(p.sku).strip()
            if codigo in usados:  # colisión rarísima: desambiguar
                base, n = codigo, 1
                while codigo in usados:
                    codigo = f"{base}-{n}"
                    n += 1
            p.codigo_barras = codigo
            p.save(update_fields=["codigo_barras"])
            usados.add(codigo)
            asignados += 1
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {asignados} productos recibieron código de barras. "
            f"{len(usados) - asignados} ya tenían uno."
        ))
