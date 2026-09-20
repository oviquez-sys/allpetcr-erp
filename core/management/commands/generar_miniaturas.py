"""Genera las miniaturas que falten (o todas, con --forzar).

Lo corre entrypoint.sh en segundo plano en cada despliegue, así que no hace
falta correrlo a mano. Solo crea las que no existen: la segunda vez tarda lo
que tarda preguntarle al bucket si cada archivo está.
"""
from django.core.management.base import BaseCommand

from catalogo.models import Producto
from core.imagenes import generar_miniatura


class Command(BaseCommand):
    help = "Crea las miniaturas de las fotos de producto que todavía no tienen."

    def add_arguments(self, parser):
        parser.add_argument("--forzar", action="store_true", help="Rehacer también las que ya existen.")

    def handle(self, *args, forzar=False, **opts):
        rutas = sorted(set(Producto.objects.exclude(imagen="").values_list("imagen", flat=True)))
        ok = fallas = 0
        for ruta in rutas:
            if generar_miniatura(ruta, forzar=forzar):
                ok += 1
            else:
                fallas += 1
                self.stdout.write(f"  sin miniatura: {ruta} (el original falta o está dañado)")
        self.stdout.write(self.style.SUCCESS(f"Miniaturas listas: {ok}. Fotos con problema: {fallas}."))
