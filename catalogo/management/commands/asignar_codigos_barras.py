"""Asigna un código de barras interno a los productos que no tengan uno.

- No toca los productos que ya traen código (p. ej. el EAN de fábrica).
- A los vacíos les da un EAN-8 interno (empieza con 2). Antes se copiaba el
  SKU; se cambió el 06/09/2026 porque un SKU largo en barras es ilegible en
  una etiqueta de 35 mm. El porqué completo está en catalogo/codigos.py.

Uso:
    python manage.py asignar_codigos_barras
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.codigos import siguiente_interno
from catalogo.models import Producto


class Command(BaseCommand):
    help = "Rellena el código de barras vacío de cada producto (EAN-8 interno)"

    @transaction.atomic
    def handle(self, *args, **opts):
        usados = set(
            Producto.objects.exclude(codigo_barras="").values_list("codigo_barras", flat=True)
        )
        ya_tenian = len(usados)
        asignados = 0
        for p in Producto.objects.filter(codigo_barras=""):
            codigo = siguiente_interno(usados)
            p.codigo_barras = codigo
            p.save(update_fields=["codigo_barras"])
            usados.add(codigo)
            asignados += 1
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {asignados} productos recibieron código interno. "
            f"{ya_tenian} ya tenían uno."
        ))
