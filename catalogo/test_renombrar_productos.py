"""Renombrado de productos desde CSV (26/09/2026)."""
import csv
import os
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase

from catalogo.models import Producto
from core.models import Empresa


class RenombrarProductos(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.arnes = Producto.objects.create(empresa=self.empresa, sku="81211", nombre="Arnes", precio_venta=Decimal("1890"))
        self.aro = Producto.objects.create(empresa=self.empresa, sku="85359", nombre="Aro", precio_venta=Decimal("2190"))
        self.csv = os.path.join(tempfile.mkdtemp(), "renombres.csv")
        with open(self.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sku", "nombre_actual", "nombre_nuevo"])
            w.writerow(["81211", "Arnes", "Arnés estampado étnico talla L"])
            w.writerow(["85359", "Aro", "Aro de goma para halar"])
            w.writerow(["999", "No existe", "Algo"])

    def correr(self, *extra):
        salida = StringIO()
        call_command("renombrar_productos", self.csv, *extra, stdout=salida)
        return salida.getvalue()

    def test_renombra(self):
        self.correr()
        self.arnes.refresh_from_db()
        self.aro.refresh_from_db()
        self.assertEqual(self.arnes.nombre, "Arnés estampado étnico talla L")
        self.assertEqual(self.aro.nombre, "Aro de goma para halar")

    def test_simulacion_no_escribe(self):
        salida = self.correr("--dry-run")
        self.arnes.refresh_from_db()
        self.assertEqual(self.arnes.nombre, "Arnes")
        self.assertIn("Se cambiarían 2", salida)

    def test_no_pisa_un_nombre_cambiado_a_mano(self):
        self.aro.nombre = "Aro que Oscar ya corrigió"
        self.aro.save()
        salida = self.correr()
        self.aro.refresh_from_db()
        self.assertEqual(self.aro.nombre, "Aro que Oscar ya corrigió")
        self.assertIn("1 se saltaron", salida)

    def test_correrlo_dos_veces_no_hace_nada_nuevo(self):
        self.correr()
        salida = self.correr()
        self.assertIn("Se cambiaron 0", salida)
        self.assertIn("Ya estaban bien: 2", salida)

    def test_la_lista_real_es_valida(self):
        """El CSV que se aplica en el servidor: columnas, largo y sin SKU repetidos."""
        ruta = Path(settings.BASE_DIR) / "catalogo" / "renombres" / "2026-09-26.csv"
        with open(ruta, encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        self.assertGreater(len(filas), 250)
        skus = [r["sku"] for r in filas]
        self.assertEqual(len(skus), len(set(skus)))
        largo_max = Producto._meta.get_field("nombre").max_length
        for r in filas:
            self.assertTrue(r["nombre_nuevo"].strip())
            self.assertLessEqual(len(r["nombre_nuevo"]), min(largo_max, 60), r)
            self.assertNotEqual(r["nombre_actual"].strip(), r["nombre_nuevo"].strip(), r)

    def test_archivo_inexistente(self):
        with self.assertRaises(CommandError):
            call_command("renombrar_productos", "no-existe.csv", stdout=StringIO())
