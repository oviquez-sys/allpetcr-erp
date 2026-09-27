"""Correcciones puntuales de datos de producto desde un CSV (27/09/2026).

    python manage.py corregir_productos catalogo/correcciones/2026-09-27.csv --dry-run
    python manage.py corregir_productos catalogo/correcciones/2026-09-27.csv

CSV: sku, campo, valor_actual, valor_nuevo, motivo

Por qué existe
--------------
Al investigar las fichas de alimento aparecieron datos del ERP que no
coinciden con el empaque (un alimento de gato cargado como "Perro", un
"Duck" que en la bolsa es "Chicken & Duck"). Corregirlos a mano en el admin
del servidor no deja registro de por qué se cambió; este CSV sí, y queda en
git junto con el motivo.

Garantías
---------
- Solo los campos de CAMPOS: nada que toque precio, costo, existencias, SKU
  o código de barras puede corregirse por esta vía.
- `mascota` solo acepta los valores oficiales (catalogo/completar.py).
- Si el valor actual ya no es el esperado (alguien lo cambió), esa fila se
  salta y se informa: nunca pisa una corrección hecha a mano.
- Una sola transacción: o entra el CSV completo, o nada.
"""
import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.completar import MASCOTAS
from catalogo.models import Producto

CAMPOS = {"nombre", "mascota"}


class Command(BaseCommand):
    help = "Corrige nombre o mascota de productos desde un CSV con valor actual y nuevo."

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument("--dry-run", action="store_true", help="Muestra qué haría, sin escribir.")

    def handle(self, *args, archivo, dry_run, **opciones):
        try:
            with open(archivo, encoding="utf-8", newline="") as f:
                filas = list(csv.DictReader(f))
        except FileNotFoundError:
            raise CommandError(f"No encontré el archivo {archivo}")

        for n, fila in enumerate(filas, start=2):
            if fila["campo"] not in CAMPOS:
                raise CommandError(f"Fila {n}: el campo «{fila['campo']}» no se corrige por esta vía.")
            if fila["campo"] == "mascota" and fila["valor_nuevo"] not in MASCOTAS:
                raise CommandError(f"Fila {n}: «{fila['valor_nuevo']}» no es una mascota válida ({', '.join(MASCOTAS)}).")
            if not fila["valor_nuevo"].strip():
                raise CommandError(f"Fila {n}: el valor nuevo está vacío.")

        cambiados, saltados, ya_estaban, no_existen = [], [], [], []
        with transaction.atomic():
            for fila in filas:
                sku, campo = fila["sku"].strip(), fila["campo"]
                actual, nuevo = fila["valor_actual"].strip(), fila["valor_nuevo"].strip()
                producto = Producto.objects.filter(sku=sku).first()
                if producto is None:
                    no_existen.append(sku)
                    continue
                hoy = (getattr(producto, campo) or "").strip()
                if hoy == nuevo:
                    ya_estaban.append(f"{sku} {campo}")
                elif hoy != actual:
                    saltados.append(f"{sku} {campo}: esperaba «{actual}», hay «{hoy}»")
                else:
                    setattr(producto, campo, nuevo)
                    producto.save(update_fields=[campo])
                    cambiados.append(f"{sku} {campo}: {actual} → {nuevo}   ({fila.get('motivo', '').strip()})")
            if dry_run:
                transaction.set_rollback(True)

        for linea in cambiados:
            self.stdout.write(f"  {linea}")
        for titulo, lista in (("se saltaron porque el valor cambió", saltados), ("SKU no existen", no_existen)):
            if lista:
                self.stdout.write(self.style.WARNING(f"\n{len(lista)} {titulo}:"))
                for linea in lista:
                    self.stdout.write(f"  {linea}")
        verbo = "Se aplicarían" if dry_run else "Se aplicaron"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verbo} {len(cambiados)} correcciones. Ya estaban bien: {len(ya_estaban)}. "
            f"Saltadas: {len(saltados)}. Inexistentes: {len(no_existen)}."
            + (" (simulación: no se escribió nada)" if dry_run else "")))
