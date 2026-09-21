"""Precios nuevos con IVA y cambio a régimen tradicional (20/09/2026)."""
import os
import tempfile
from decimal import Decimal
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from openpyxl import Workbook

from catalogo.models import CambioPrecio, Producto
from catalogo.precios_bonitos import precio_bonito
from core.models import Empresa


class PrecioBonito(TestCase):
    def test_casos_reales(self):
        casos = {  # precio de hoy → precio bonito con IVA
            600: 690, 900: 990, 1200: 1350, 1800: 1990, 1900: 2190,
            2400: 2690, 5300: 5990, 8500: 9590, 22900: 25900, 27900: 30900,
        }
        for hoy, esperado in casos.items():
            self.assertEqual(precio_bonito(Decimal(hoy) * Decimal("1.13")), Decimal(esperado), hoy)

    def test_nunca_baja_mas_de_tres_por_ciento(self):
        for hoy in range(100, 60000, 37):
            exacto = Decimal(hoy) * Decimal("1.13")
            self.assertGreaterEqual(precio_bonito(exacto), exacto * Decimal("0.97"), hoy)


class AplicarPreciosIVA(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.arnes = self._producto("1", "Arnés", 2100)
        self.taza = self._producto("2", "Taza", 2700)
        self.caro = self._producto("3", "Cama", 9000)  # alguien ya lo subió por encima del plan
        self.excel = os.path.join(tempfile.mkdtemp(), "precios.xlsx")
        libro = Workbook()
        hoja = libro.active
        hoja.append(["Código", "Producto", "Precio hoy", "PRECIO NUEVO (con IVA)"])
        hoja.append(["1", "Arnés", 2100, 2890])
        hoja.append(["2", "Taza", 2700, 2990])
        hoja.append(["2", "Taza", 2100, 2890])  # mismo código comprado a otro costo
        hoja.append(["3", "Cama", 8000, 8990])
        hoja.append(["999", "No existe", 500, 690])
        libro.save(self.excel)

    def _producto(self, sku, nombre, precio):
        return Producto.objects.create(empresa=self.empresa, sku=sku, nombre=nombre,
                                       precio_venta=Decimal(precio), costo_promedio=Decimal("1000"))

    def correr(self, *args):
        salida = StringIO()
        call_command("aplicar_precios_iva", "--excel", self.excel, *args, stdout=salida)
        return salida.getvalue()

    def _precios(self):
        return {p.sku: p.precio_venta for p in Producto.objects.all()}

    def test_simulacion_no_escribe(self):
        salida = self.correr("--dry-run")
        self.assertIn("SIMULACIÓN", salida)
        self.assertEqual(self._precios(), {"1": Decimal("2100"), "2": Decimal("2700"), "3": Decimal("9000")})
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.regimen, Empresa.Regimen.SIMPLIFICADO)

    def test_aplica_precios_y_regimen_juntos(self):
        self.correr()
        precios = self._precios()
        self.assertEqual(precios["1"], Decimal("2890"))
        self.assertEqual(precios["2"], Decimal("2990"))  # código repetido: el más alto
        self.assertEqual(precios["3"], Decimal("9000"))  # nunca se baja un precio
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.regimen, Empresa.Regimen.TRADICIONAL)
        cambio = CambioPrecio.objects.get(producto=self.arnes)
        self.assertEqual(cambio.valor_anterior, Decimal("2100"))
        self.assertIn("IVA", cambio.motivo)

    def test_no_se_puede_correr_dos_veces(self):
        self.correr()
        with self.assertRaises(CommandError):
            self.correr()
        self.assertEqual(self._precios()["1"], Decimal("2890"))
