"""Extrae las fotos embebidas en el Excel y las asocia a cada producto.

Las imágenes de un .xlsx viven en xl/media/ y su posición (fila) está en
xl/drawings/drawing1.xml. Cada imagen se ancla a la fila de su producto, así
que se mapea por orden de fila con la lista de productos (mismo orden que
importar_inventario).

Uso:
    python manage.py importar_imagenes "data/INVENTARIO REAL AL 6-7-2026   2.0.xlsx"
"""
import re
import zipfile
from pathlib import Path

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Producto


class Command(BaseCommand):
    help = "Extrae las imágenes del Excel y las asigna a cada producto por su fila"

    def add_arguments(self, parser):
        parser.add_argument("ruta_excel")

    @transaction.atomic
    def handle(self, *args, **opts):
        ruta = opts["ruta_excel"]
        try:
            zf = zipfile.ZipFile(ruta)
        except (FileNotFoundError, zipfile.BadZipFile):
            raise CommandError(f"No se pudo abrir el Excel: {ruta}")

        with zf:
            nombres = zf.namelist()
            draw = next((n for n in nombres if re.match(r"xl/drawings/drawing\d+\.xml$", n)), None)
            if not draw:
                raise CommandError("El Excel no tiene imágenes embebidas (sin drawings).")
            xml = zf.read(draw).decode("utf-8", "ignore")
            rels = zf.read("xl/drawings/_rels/" + draw.split("/")[-1] + ".rels").decode("utf-8")
            rid_target = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))

            # (fila 0-based) -> media file, tomando la primera imagen por fila
            fila_media = {}
            anchors = re.findall(
                r"<xdr:(?:twoCellAnchor|oneCellAnchor)\b.*?</xdr:(?:twoCellAnchor|oneCellAnchor)>",
                xml, re.S,
            )
            for a in anchors:
                mr = re.search(r"<xdr:from>.*?<xdr:row>(\d+)</xdr:row>", a, re.S)
                me = re.search(r'r:embed="(rId\d+)"', a)
                if not (mr and me):
                    continue
                fila = int(mr.group(1))
                target = rid_target.get(me.group(1), "")
                media = "xl/" + target.replace("../", "")
                fila_media.setdefault(fila, media)

            # Mapa fila 0-based del Excel -> SKU (columna B), leyendo la hoja.
            wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
            ws = wb["Inventario Real"] if "Inventario Real" in wb.sheetnames else wb.active
            fila_sku = {}
            for i, row in enumerate(ws.iter_rows(min_row=1, values_only=True)):
                # i es 0-based y coincide con la fila 0-based de los anchors
                sku = row[1] if len(row) > 1 else None
                if sku:
                    fila_sku[i] = str(sku).strip()
            wb.close()

            por_sku = {p.sku: p for p in Producto.objects.all()}
            destino = Path(settings.MEDIA_ROOT) / "productos"
            destino.mkdir(parents=True, exist_ok=True)

            guardadas = sin_producto = 0
            for fila, media in fila_media.items():
                sku = fila_sku.get(fila)
                prod = por_sku.get(sku) if sku else None
                if prod is None:
                    sin_producto += 1
                    continue
                try:
                    data = zf.read(media)
                except KeyError:
                    continue
                ext = Path(media).suffix.lower() or ".png"
                nombre_archivo = f"{prod.sku}{ext}"
                (destino / nombre_archivo).write_bytes(data)
                rel = f"productos/{nombre_archivo}"
                if prod.imagen != rel:
                    prod.imagen = rel
                    prod.save(update_fields=["imagen"])
                guardadas += 1

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {guardadas} imágenes extraídas y asignadas a productos."
            + (f" ({sin_producto} imágenes sin producto coincidente)" if sin_producto else "")
        ))
