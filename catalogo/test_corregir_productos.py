"""Correcciones puntuales de producto desde CSV (27/09/2026)."""
import csv
import os
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase

from catalogo.completar import MASCOTAS
from catalogo.models import Producto
from core.models import Empresa


class CorregirProductos(TestCase):
    def setUp(self):
        empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.lata = Producto.objects.create(empresa=empresa, sku="BEL-93020", nombre="NutriSource ChickenTurkeyLambFish 156 g",
                                            mascota="Perro", precio_venta=Decimal("1975"))

    def csv(self, *filas):
        ruta = os.path.join(tempfile.mkdtemp(), "c.csv")
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sku", "campo", "valor_actual", "valor_nuevo", "motivo"])
            w.writerows(filas)
        return ruta

    def correr(self, ruta, *extra):
        salida = StringIO()
        call_command("corregir_productos", ruta, *extra, stdout=salida)
        return salida.getvalue()

    def test_corrige_mascota_y_nombre_sin_tocar_el_precio(self):
        self.correr(self.csv(["BEL-93020", "mascota", "Perro", "Gato", "empaque"],
                             ["BEL-93020", "nombre", "NutriSource ChickenTurkeyLambFish 156 g", "Lata gato 156 g", "empaque"]))
        self.lata.refresh_from_db()
        self.assertEqual((self.lata.mascota, self.lata.nombre, self.lata.precio_venta), ("Gato", "Lata gato 156 g", Decimal("1975")))

    def test_simulacion_no_escribe(self):
        self.correr(self.csv(["BEL-93020", "mascota", "Perro", "Gato", ""]), "--dry-run")
        self.lata.refresh_from_db()
        self.assertEqual(self.lata.mascota, "Perro")

    def test_no_pisa_un_valor_cambiado_a_mano(self):
        self.lata.mascota = "Perro y gato"
        self.lata.save()
        salida = self.correr(self.csv(["BEL-93020", "mascota", "Perro", "Gato", ""]))
        self.lata.refresh_from_db()
        self.assertEqual(self.lata.mascota, "Perro y gato")
        self.assertIn("se saltaron", salida)

    def test_solo_nombre_y_mascota(self):
        with self.assertRaises(CommandError):
            self.correr(self.csv(["BEL-93020", "precio_venta", "1975", "1", ""]))

    def test_mascota_invalida(self):
        with self.assertRaises(CommandError):
            self.correr(self.csv(["BEL-93020", "mascota", "Perro", "Felino", ""]))

    def test_las_correcciones_reales_son_validas(self):
        for ruta in (Path(settings.BASE_DIR) / "catalogo" / "correcciones").glob("*.csv"):
            with open(ruta, encoding="utf-8", newline="") as f:
                for fila in csv.DictReader(f):
                    self.assertIn(fila["campo"], {"nombre", "mascota"}, ruta.name)
                    self.assertTrue(fila["motivo"].strip(), f"{ruta.name}: cada corrección lleva su motivo")
                    if fila["campo"] == "mascota":
                        self.assertIn(fila["valor_nuevo"], MASCOTAS)
