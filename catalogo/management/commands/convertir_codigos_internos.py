"""Cambia a EAN-8 interno los códigos que no son un EAN de fábrica.

Qué conserva y qué cambia:

- **Conserva** todo código que sea un EAN-13 o EAN-8 válido. Ese es el código
  impreso por el fabricante: es el bueno, es gratis y la caja lo lee del
  empaque sin pegar nada.
- **Cambia** el resto —los que salieron del SKU y los que parecen EAN pero
  tienen el dígito verificador malo— por un EAN-8 interno (empieza con 2).

Por defecto NO escribe nada: muestra lo que haría. Para aplicarlo:

    python manage.py convertir_codigos_internos --aplicar

La misma operación está en el ERP, en Inventario → Códigos de barras, para
cuando la consola no está disponible.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.codigos import aplicar_conversion, plan_de_conversion
from catalogo.models import Producto


class Command(BaseCommand):
    help = "Convierte a EAN-8 interno los códigos que no son EAN de fábrica."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true",
                            help="Escribe los cambios. Sin esto solo muestra qué haría.")

    @transaction.atomic
    def handle(self, *args, **opciones):
        plan = plan_de_conversion(Producto.objects.all())
        self.stdout.write("=== CONVERSION A CODIGOS INTERNOS ===")
        self.stdout.write(f"  EAN de fabrica que se conservan : {len(plan['conservados'])}")
        self.stdout.write(f"  Ya tenian codigo interno        : {len(plan['ya_internos'])}")
        self.stdout.write(f"  Se convierten                   : {len(plan['cambios'])}")
        for producto, viejo, nuevo in plan["cambios"][:10]:
            self.stdout.write(
                f"      {producto.sku:<14} {viejo or '(vacio)':<16} -> {nuevo}   {producto.nombre[:34]}")
        if len(plan["cambios"]) > 10:
            self.stdout.write(f"      ... y {len(plan['cambios']) - 10} mas")

        if not opciones["aplicar"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Ensayo: no se escribio nada. Volve a correrlo con --aplicar."))
            return

        destino = Path(settings.BASE_DIR) / "codigos_anteriores.csv"
        cuantos = aplicar_conversion(plan, destino)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {cuantos} codigos convertidos. Respaldo en {destino.name}"))
