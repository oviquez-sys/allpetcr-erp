"""Precio por kilo en la pantalla de ventas (pedido de Oscar, 19/10/2026)."""
from decimal import Decimal

from django.test import SimpleTestCase

from .por_kilo import precio_por_kilo


class PrecioPorKiloTests(SimpleTestCase):
    def test_bolsa_en_kilos(self):
        self.assertEqual(precio_por_kilo(Decimal("64500"), Decimal("15"), "kg"), (4300, "kg"))

    def test_gramos_y_libras(self):
        self.assertEqual(precio_por_kilo(Decimal("2000"), Decimal("500"), "g"), (4000, "kg"))
        # 1 lb = 0,45359237 kg → ₡4.536 / 0,4536 = ₡10.000 el kg
        self.assertEqual(precio_por_kilo(Decimal("4536"), Decimal("1"), "lb"), (10000, "kg"))

    def test_liquidos_dan_precio_por_litro(self):
        self.assertEqual(precio_por_kilo(Decimal("3000"), Decimal("250"), "ml"), (12000, "l"))

    def test_sin_peso_usa_la_presentacion_solo_si_es_un_peso_limpio(self):
        self.assertEqual(precio_por_kilo(Decimal("12000"), None, "", "3 kg"), (4000, "kg"))
        self.assertEqual(precio_por_kilo(Decimal("12000"), None, "", "3,5 kg"), (3429, "kg"))
        self.assertIsNone(precio_por_kilo(Decimal("3000"), None, "", "2 x 85 g"))
        self.assertIsNone(precio_por_kilo(Decimal("3000"), None, "", "Bolsa 3 kg + 1 gratis"))

    def test_unidad_o_sin_datos_no_muestra_nada(self):
        self.assertIsNone(precio_por_kilo(Decimal("5000"), Decimal("1"), "un"))
        self.assertIsNone(precio_por_kilo(Decimal("5000"), None, ""))
        self.assertIsNone(precio_por_kilo(Decimal("0"), Decimal("15"), "kg"))
        self.assertIsNone(precio_por_kilo(Decimal("5000"), Decimal("0"), "kg"))

    def test_el_peso_del_producto_manda_sobre_la_presentacion(self):
        self.assertEqual(precio_por_kilo(Decimal("10000"), Decimal("2"), "kg", "4 kg"), (5000, "kg"))


class SoloAlimentoTests(SimpleTestCase):
    def test_alimento_snacks_y_arena_si(self):
        from .por_kilo import aplica
        self.assertTrue(aplica("Alimento seco", "Alimento"))
        self.assertTrue(aplica("Snacks y premios"))
        self.assertTrue(aplica("Arena", "Arena y sanitarios"))
        self.assertTrue(aplica("Sin categoría", "", tiene_ficha=True))

    def test_shampoo_o_medicina_no(self):
        from .por_kilo import aplica
        self.assertFalse(aplica("Higiene y aseo"))
        self.assertFalse(aplica("Salud y cuidado"))
        self.assertFalse(aplica(None, None))
