"""División de alimentos (26/09/2026): la regla en Python y la de la base
tienen que decir lo mismo, y el reporte tiene que mostrar el inventario."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from catalogo import divisiones as dv
from catalogo.models import Categoria, Producto
from core.models import Empresa
from core.reportes import ventas_por_periodo


class Divisiones(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        alimento = Categoria.objects.create(nombre="Alimento")
        seco = Categoria.objects.create(nombre="Alimento seco", padre=alimento)
        snacks = Categoria.objects.create(nombre="Snacks y premios")
        juguetes = Categoria.objects.create(nombre="Juguetes")
        casos = [("A", seco, "Perro"), ("B", seco, "Gato"), ("C", snacks, "Gato"),
                 ("D", alimento, "Perro y gato"), ("E", juguetes, "Perro"), ("F", None, ""),
                 ("G", seco, "")]
        for sku, cat, mascota in casos:
            Producto.objects.create(empresa=cls.empresa, sku=sku, nombre=sku, categoria=cat, mascota=mascota,
                                    precio_venta=100, stock_actual=2, costo_promedio=10)

    def test_la_regla_en_python_y_en_la_base_coinciden(self):
        for p in Producto.objects.select_related("categoria__padre").annotate(div=dv.anotar_division()):
            raiz = None
            if p.categoria:
                raiz = p.categoria.padre.nombre if p.categoria.padre else p.categoria.nombre
            self.assertEqual(p.div, dv.division(raiz, p.mascota), p.sku)

    def test_clasifica_por_especie(self):
        div = dict(Producto.objects.annotate(d=dv.anotar_division()).values_list("sku", "d"))
        self.assertEqual(div["A"], dv.ALIMENTO_PERRO)
        self.assertEqual(div["B"], dv.ALIMENTO_GATO)
        self.assertEqual(div["C"], dv.ALIMENTO_GATO)
        self.assertEqual(div["D"], dv.ALIMENTO_PERRO)
        self.assertEqual(div["E"], dv.ACCESORIOS)
        self.assertEqual(div["F"], dv.ACCESORIOS)
        self.assertEqual(div["G"], dv.ALIMENTO_OTRO)

    def test_reporte_muestra_el_inventario_por_division(self):
        datos = ventas_por_periodo(self.empresa, date(2026, 9, 1), date(2026, 9, 30))
        filas = {d["division"]: d for d in datos["por_division"]}
        self.assertEqual(filas[dv.ALIMENTO_PERRO]["productos"], 2)
        self.assertEqual(filas[dv.ALIMENTO_GATO]["capital"], Decimal("40"))
        self.assertEqual([d["division"] for d in datos["por_division"]], dv.ORDEN)
