"""Precio sin IVA, ganancia y margen de un producto (20/09/2026).

Dos errores que estas pruebas no dejan volver:

1. La ficha de precio mostraba "Ganancia" como precio + costo − 1: un filtro
   `add` de plantilla que sumaba en vez de restar. Con precio ₡5.300 y costo
   ₡2.000 decía ₡7.299, más que el precio mismo.
2. En régimen tradicional el precio incluye IVA, y el margen se calculaba
   contra el precio completo: contaba como ganancia el IVA de Hacienda.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from catalogo.models import TARIFA_GENERAL_IVA, Categoria, Impuesto, Producto
from core.models import Empresa


class GananciaConIVA(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")  # RTS por defecto
        self.iva = Impuesto.objects.create(nombre="IVA general", tarifa=Decimal("13"))
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="79205", nombre="Alfombrilla",
            categoria=Categoria.objects.create(nombre="Descanso"),
            precio_venta=Decimal("5300"), costo_promedio=Decimal("2000"), impuesto=self.iva,
        )

    def _tradicional(self):
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL
        self.empresa.save()
        self.producto.refresh_from_db()

    def test_simplificado_no_desglosa_iva(self):
        p = self.producto
        self.assertEqual(p.precio_sin_iva, Decimal("5300"))
        self.assertEqual(p.iva_unitario, Decimal("0"))
        self.assertEqual(p.ganancia_unitaria, Decimal("3300"))
        self.assertEqual(p.margen_pct, Decimal("62.26"))

    def test_tradicional_saca_el_iva_antes_de_la_ganancia(self):
        self._tradicional()
        p = self.producto
        self.assertEqual(p.precio_sin_iva, Decimal("4690.27"))
        self.assertEqual(p.iva_unitario, Decimal("609.73"))
        self.assertEqual(p.ganancia_unitaria, Decimal("2690.27"))
        self.assertEqual(p.margen_pct, Decimal("57.36"))
        self.assertEqual(p.markup_pct, Decimal("134.51"))

    def test_sin_tarifa_asignada_usa_la_general(self):
        """Suponer 0 le quitaba el IVA a la venta en silencio."""
        self.producto.impuesto = None
        self.producto.save()
        self._tradicional()
        self.assertEqual(self.producto.tarifa_iva, TARIFA_GENERAL_IVA)
        self.assertEqual(self.producto.precio_sin_iva, Decimal("4690.27"))

    def test_ficha_de_precio_muestra_la_ganancia_real(self):
        User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.client.login(username="oscar", password="x")
        url = reverse("catalogo:precio_producto", args=[self.producto.pk])

        html = self.client.get(url).content.decode()
        self.assertIn("₡3.300", html)
        self.assertNotIn("₡7.299", html)  # precio + costo − 1, el error viejo
        self.assertNotIn("IVA incluido", html)

        self._tradicional()
        html = self.client.get(url).content.decode()
        self.assertIn("IVA incluido (13%)", html)
        self.assertIn("₡610", html)    # IVA de Hacienda
        self.assertIn("₡2.690", html)  # ganancia sin IVA
