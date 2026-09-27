"""Renombra productos a partir de un CSV sku,nombre_actual,nombre_nuevo
(26/09/2026, a pedido de Oscar).

    python manage.py renombrar_productos catalogo/renombres/2026-09-26.csv --dry-run
    python manage.py renombrar_productos catalogo/renombres/2026-09-26.csv

Por qué existe
--------------
En el sitio había 251 productos con nombres de una o dos palabras ("Arnes",
"Juguete", "Collar") y 181 que compartían nombre con otro: en la tarjeta
del catálogo no había forma de saber cuál era cuál. Los productos Zee.Dog
tenían el problema al revés: nombres largos que la tarjeta cortaba en
"Zee.Dog Gotham -", iguales para quince productos distintos.

Los nombres nuevos se armaron con la descripción de cada producto y, donde
no había, con su foto: tipo + rasgo que lo distingue + talla. Oscar pidió
nombres correctos y cortos, sin revisarlos uno por uno.

Por qué el CSV trae el nombre actual
------------------------------------
Es el seguro contra pisar un cambio hecho a mano: si alguien renombró el
producto en el ERP después de que se armó la lista, el nombre actual ya no
coincide y ese producto se salta (se informa, no se toca). Todo va en una
sola transacción: o se aplica la lista completa, o nada.
"""
import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Producto


class Command(BaseCommand):
    help = "Renombra productos desde un CSV (sku, nombre_actual, nombre_nuevo)."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="CSV con columnas sku, nombre_actual, nombre_nuevo.")
        parser.add_argument("--dry-run", action="store_true", help="Muestra qué haría, sin escribir.")

    def handle(self, *args, archivo, dry_run, **opciones):
        try:
            with open(archivo, encoding="utf-8", newline="") as f:
                filas = list(csv.DictReader(f))
        except FileNotFoundError:
            raise CommandError(f"No encontré el archivo {archivo}")
        faltan = {"sku", "nombre_actual", "nombre_nuevo"} - set(filas[0].keys() if filas else [])
        if faltan:
            raise CommandError(f"Al CSV le faltan columnas: {', '.join(sorted(faltan))}")

        cambiados, iguales, distintos, no_existen = [], [], [], []
        with transaction.atomic():
            for fila in filas:
                sku = fila["sku"].strip()
                actual = fila["nombre_actual"].strip()
                nuevo = fila["nombre_nuevo"].strip()
                if not nuevo:
                    raise CommandError(f"El SKU {sku} trae el nombre nuevo vacío.")
                productos = list(Producto.objects.filter(sku=sku))
                if not productos:
                    no_existen.append(sku)
                    continue
                for p in productos:
                    if p.nombre.strip() == nuevo:
                        iguales.append(sku)
                    elif p.nombre.strip() != actual:
                        distintos.append(f"{sku}: esperaba «{actual}», hay «{p.nombre}»")
                    else:
                        cambiados.append(f"{sku}: {p.nombre} → {nuevo}")
                        p.nombre = nuevo
                        p.save(update_fields=["nombre"])
            if dry_run:
                transaction.set_rollback(True)

        for linea in cambiados:
            self.stdout.write(f"  {linea}")
        if distintos:
            self.stdout.write(self.style.WARNING(
                f"\n{len(distintos)} se saltaron porque su nombre cambió desde que se armó la lista:"))
            for linea in distintos:
                self.stdout.write(f"  {linea}")
        if no_existen:
            self.stdout.write(self.style.WARNING(f"\n{len(no_existen)} SKU no existen: {', '.join(no_existen)}"))
        verbo = "Se cambiarían" if dry_run else "Se cambiaron"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verbo} {len(cambiados)} nombres. Ya estaban bien: {len(iguales)}. "
            f"Saltados: {len(distintos)}. Inexistentes: {len(no_existen)}."
            + (" (simulación: no se escribió nada)" if dry_run else "")))
