"""Deshace un «marcar visibles como impresas» que abarcó de más (27/09/2026).

Pasó así: en Etiquetas, con el buscador vacío, «Marcar visibles como
impresas» marcó el catálogo entero como «etiqueta puesta». Oscar quería
seguir viendo cuáles le faltan.

CÓMO RECONOCE EL LOTE
    El marcado en lote pone la MISMA fecha y hora exacta a todos los productos
    (un solo `update`). Uno por uno —imprimiendo o marcando a mano— cada
    producto queda con su propio instante. Así que un instante compartido por
    muchos productos (`--minimo`, 20 por defecto) es un lote, y lo que tiene
    su propio instante se respeta.

QUÉ LES PONE
    Si el producto tiene una etiqueta que de verdad salió de la impresora
    (trabajo IMPRESO en la cola, que guarda los últimos 7 días), vuelve a
    «puesta» con la hora de esa impresión. Si no, vuelve a «pendiente».

Con --dry-run solo cuenta. Se aplica en el servidor con
DESHACER_MARCADO_ETIQUETAS.bat.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from catalogo.models import Producto
from impresion.models import TrabajoImpresion


class Command(BaseCommand):
    help = "Deshace marcados en lote de «etiqueta puesta» (ver docstring)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--minimo", type=int, default=20,
                            help="Cuántos productos con el mismo instante cuentan como lote.")

    def handle(self, *args, dry_run=False, minimo=20, **opciones):
        lotes = list(
            Producto.objects.filter(etiqueta_impresa_en__isnull=False)
            .values("etiqueta_impresa_en").annotate(n=Count("id")).filter(n__gte=minimo)
            .order_by("etiqueta_impresa_en")
        )
        if not lotes:
            self.stdout.write("  No hay marcados en lote. No hay nada que deshacer.")
            return
        for lote in lotes:
            self.stdout.write(f"  Lote del {timezone.localtime(lote['etiqueta_impresa_en']):%d/%m/%Y %H:%M:%S}: {lote['n']} productos")

        # Última impresión real por SKU. El título del trabajo es «Etiqueta <SKU>»
        # (impresion.servicio.imprimir_etiqueta).
        impresas = {
            fila["titulo"].removeprefix("Etiqueta ").strip(): fila["cuando"]
            for fila in TrabajoImpresion.objects.filter(tipo=TrabajoImpresion.ETIQUETA,
                                                        estado=TrabajoImpresion.IMPRESO)
            .values("titulo").annotate(cuando=Max("terminado_en"))
        }
        productos = list(Producto.objects.filter(
            etiqueta_impresa_en__in=[lote["etiqueta_impresa_en"] for lote in lotes]))
        de_verdad = [p for p in productos if p.sku in impresas]

        self.stdout.write("")
        self.stdout.write(f"  Vuelven a PENDIENTE: {len(productos) - len(de_verdad)}")
        self.stdout.write(f"  Quedan como PUESTA (su etiqueta sí salió de la impresora): {len(de_verdad)}")
        for p in de_verdad:
            self.stdout.write(f"     {p.sku}  {p.nombre}")
        if dry_run:
            self.stdout.write("\n  (Simulación: no se escribió nada.)")
            return

        with transaction.atomic():
            for p in productos:
                p.etiqueta_impresa_en = impresas.get(p.sku)
            Producto.objects.bulk_update(productos, ["etiqueta_impresa_en"])
        self.stdout.write(self.style.SUCCESS(f"\n  Listo: {len(productos)} productos corregidos."))
