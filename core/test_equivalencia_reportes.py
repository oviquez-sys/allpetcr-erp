"""Los reportes optimizados deben dar EXACTAMENTE lo mismo que antes.

Auditoría 2026-07-28, hallazgo BE-06: `niveles_stock` y `valor_inventario`
traían todos los productos a memoria y los recorrían en Python. Ahora agregan
en la base de datos.

Optimizar un reporte es fácil; optimizarlo sin cambiar el resultado es lo que
hay que demostrar. Estas pruebas calculan cada cifra por el método viejo
—iterando en Python— y exigen que coincida con lo que devuelve la versión
nueva. Es el mismo enfoque que ya usa test_equivalencia_dashboard.py.
"""
from decimal import Decimal

from django.test import TestCase

from catalogo.models import Categoria, Producto
from core import reportes as rep
from core.models import Empresa


class BaseReportes(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPetCR", identificacion="3-102-000000")
        self.otra = Empresa.objects.create(nombre="Otra", identificacion="3-102-111111")
        self.perros = Categoria.objects.create(nombre="Perros")
        self.gatos = Categoria.objects.create(nombre="Gatos")

        def crear(sku, nombre, cat, stock, minimo, costo, empresa=None, activo=True):
            p = Producto.objects.create(
                empresa=empresa or self.empresa, sku=sku, nombre=nombre, categoria=cat,
                precio_venta=Decimal("10000"), stock_minimo=Decimal(minimo), activo=activo,
            )
            # stock_actual y costo_promedio son denormalizados que normalmente
            # mantiene el kardex; acá se fijan directo porque lo que se prueba
            # es la agregación del reporte, no el flujo de inventario.
            Producto.objects.filter(pk=p.pk).update(
                stock_actual=Decimal(stock), costo_promedio=Decimal(costo)
            )
            return Producto.objects.get(pk=p.pk)

        self.p1 = crear("A1", "Alimento perro", self.perros, "10", "2", "4000")
        self.p2 = crear("A2", "Collar", self.perros, "1", "5", "1500")     # bajo mínimo
        self.p3 = crear("A3", "Arena gato", self.gatos, "0", "3", "2500")  # bajo mínimo
        self.p4 = crear("A4", "Juguete", None, "7", "1", "800")            # sin categoría
        self.p5 = crear("A5", "Descontinuado", self.gatos, "99", "1", "900", activo=False)
        self.p6 = crear("A6", "De otra empresa", self.perros, "50", "1", "700", empresa=self.otra)

    def _productos_viejo_metodo(self):
        """Lo que la versión anterior recorría: activos de esta empresa."""
        return list(Producto.objects.filter(empresa=self.empresa, activo=True))


class NivelesStockTest(BaseReportes):
    def test_num_total_coincide_con_el_conteo_en_python(self):
        r = rep.niveles_stock(self.empresa)
        self.assertEqual(r["num_total"], len(self._productos_viejo_metodo()))

    def test_num_bajo_coincide_con_el_conteo_en_python(self):
        viejo = sum(1 for p in self._productos_viejo_metodo() if p.stock_actual <= p.stock_minimo)
        r = rep.niveles_stock(self.empresa)
        self.assertEqual(r["num_bajo"], viejo)
        self.assertEqual(r["num_bajo"], 2, "El escenario debe tener 2 bajo mínimo o no prueba nada")

    def test_solo_bajo_devuelve_exactamente_los_mismos_productos(self):
        viejo = {p.pk for p in self._productos_viejo_metodo() if p.stock_actual <= p.stock_minimo}
        nuevo = {p.pk for p in rep.niveles_stock(self.empresa, solo_bajo=True)["productos"]}
        self.assertEqual(viejo, nuevo)

    def test_el_orden_pone_los_bajo_minimo_primero(self):
        productos = list(rep.niveles_stock(self.empresa)["productos"])
        bajos = [p.stock_actual <= p.stock_minimo for p in productos]
        self.assertEqual(
            bajos, sorted(bajos, reverse=True),
            "Los productos bajo mínimo deben ir primero: es la razón de ser del reporte.",
        )

    def test_no_mezcla_productos_de_otra_empresa(self):
        skus = {p.sku for p in rep.niveles_stock(self.empresa)["productos"]}
        self.assertNotIn("A6", skus)

    def test_no_incluye_productos_inactivos(self):
        skus = {p.sku for p in rep.niveles_stock(self.empresa)["productos"]}
        self.assertNotIn("A5", skus)


class ValorInventarioTest(BaseReportes):
    def _totales_viejo_metodo(self):
        total_valor = Decimal("0")
        total_unidades = Decimal("0")
        grupos = {}
        for p in self._productos_viejo_metodo():
            valor = (p.stock_actual or Decimal("0")) * (p.costo_promedio or Decimal("0"))
            total_valor += valor
            total_unidades += p.stock_actual or Decimal("0")
            cat = p.categoria.nombre if p.categoria else "Sin categoría"
            g = grupos.setdefault(cat, {"valor": Decimal("0"), "unidades": Decimal("0"), "items": 0})
            g["valor"] += valor
            g["unidades"] += p.stock_actual or Decimal("0")
            g["items"] += 1
        return total_valor, total_unidades, grupos

    def test_total_valor_identico(self):
        viejo, _, _ = self._totales_viejo_metodo()
        nuevo = rep.valor_inventario(self.empresa)["total_valor"]
        self.assertEqual(Decimal(str(nuevo)), viejo)
        self.assertGreater(viejo, 0, "El escenario no tiene valor; no probaría nada")

    def test_total_unidades_identico(self):
        _, viejo, _ = self._totales_viejo_metodo()
        nuevo = rep.valor_inventario(self.empresa)["total_unidades"]
        self.assertEqual(Decimal(str(nuevo)), viejo)

    def test_num_productos_identico(self):
        r = rep.valor_inventario(self.empresa)
        self.assertEqual(r["num_productos"], len(self._productos_viejo_metodo()))

    def test_agrupacion_por_categoria_identica(self):
        _, _, viejo = self._totales_viejo_metodo()
        nuevo = {f["categoria"]: f for f in rep.valor_inventario(self.empresa)["filas"]}
        self.assertEqual(set(nuevo), set(viejo))
        for cat, g in viejo.items():
            with self.subTest(categoria=cat):
                self.assertEqual(Decimal(str(nuevo[cat]["valor"])), g["valor"])
                self.assertEqual(Decimal(str(nuevo[cat]["unidades"])), g["unidades"])
                self.assertEqual(nuevo[cat]["items"], g["items"])

    def test_los_productos_sin_categoria_se_agrupan_aparte(self):
        cats = {f["categoria"] for f in rep.valor_inventario(self.empresa)["filas"]}
        self.assertIn("Sin categoría", cats)

    def test_las_filas_van_de_mayor_a_menor_valor(self):
        valores = [f["valor"] for f in rep.valor_inventario(self.empresa)["filas"]]
        self.assertEqual(valores, sorted(valores, reverse=True))

    def test_no_suma_productos_de_otra_empresa(self):
        """Si sumara la otra empresa, el total incluiría 50 × 700 = 35 000."""
        propio, _, _ = self._totales_viejo_metodo()
        self.assertEqual(Decimal(str(rep.valor_inventario(self.empresa)["total_valor"])), propio)


class CostoDeLosReportesTest(BaseReportes):
    """El punto de BE-06: el número de consultas no debe crecer con el catálogo."""

    def _consultas(self, fn):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            r = fn()
            list(r["productos"]) if "productos" in r else None  # forzar evaluación
        return len(ctx.captured_queries)

    def test_valor_inventario_usa_pocas_consultas_constantes(self):
        n = self._consultas(lambda: rep.valor_inventario(self.empresa))
        self.assertLessEqual(n, 3, f"valor_inventario ejecutó {n} consultas; debería agregar en la base.")

    def test_niveles_stock_no_depende_del_numero_de_productos(self):
        antes = self._consultas(lambda: rep.niveles_stock(self.empresa))
        for i in range(30):
            Producto.objects.create(
                empresa=self.empresa, sku=f"X{i}", nombre=f"Extra {i}",
                categoria=self.perros, precio_venta=Decimal("100"),
            )
        despues = self._consultas(lambda: rep.niveles_stock(self.empresa))
        self.assertEqual(
            antes, despues,
            "El número de consultas cambió al agregar 30 productos: el reporte "
            "volvió a depender del tamaño del catálogo.",
        )
