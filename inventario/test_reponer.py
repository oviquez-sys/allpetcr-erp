"""«Reponer» (26/11/2026): una pantalla para Lo vendido, Qué reponer y Agotados.

Lo que fijan estas pruebas:
- El que rota rápido pide antes que el que no rota, con el mismo mínimo (el
  punto de «Qué reponer» del 05/11).
- Lo que no se vende no se pide, y nunca sale un pedido negativo.
- Los días agotados no bajan la venta por día.
- Con un rango corto (hoy, esta semana un lunes) el «Pedir» usa 30 días.
- «No comprar más» saca el producto de lo que hay que pedir.
- El Excel trae una hoja por proveedor, «Pedir» editable y totales en fórmula.
"""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.services import abrir_caja
from catalogo.models import Categoria, Producto
from compras.models import Compra, LineaCompra, Proveedor
from core.models import Empresa, Sucursal
from ventas.models import FacturaVenta
from ventas.services import registrar_venta

from . import reponer
from .models import Agotamiento, Bodega
from .services import registrar_movimiento


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Bodega")
        self.usuario = User.objects.create_user("g", password="x", is_staff=True, is_superuser=True)
        self.categoria = Categoria.objects.create(nombre="Test")
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))
        self.hoy = timezone.localdate()
        self.hace_un_mes = timezone.now() - timedelta(days=40)

    def producto(self, sku, stock, minimo=2):
        p = Producto.objects.create(
            empresa=self.empresa, sku=sku, nombre=f"Producto {sku}", categoria=self.categoria,
            precio_venta=Decimal("1000"), costo_promedio=Decimal("500"), stock_minimo=Decimal(minimo),
        )
        # Que exista desde antes del rango: si no, los días cuentan desde que se creó.
        Producto.objects.filter(pk=p.pk).update(creado_en=self.hace_un_mes)
        if stock:
            registrar_movimiento(producto=p, bodega=self.bodega, tipo="ENT", cantidad=Decimal(stock),
                                 costo_unitario=Decimal("500"), referencia="carga", usuario=self.usuario)
        p.refresh_from_db()
        return p

    def vender(self, producto, cantidad, hace_dias=0):
        f = registrar_venta(sesion_caja=self.sesion, medio_pago=FacturaVenta.MedioPago.EFECTIVO,
                            usuario=self.usuario,
                            lineas=[{"producto_id": producto.pk, "cantidad": Decimal(cantidad)}])
        if hace_dias:
            FacturaVenta.objects.filter(pk=f.pk).update(creado_en=timezone.now() - timedelta(days=hace_dias))
        return f

    def datos(self, dias=30, **kw):
        return reponer.datos(self.empresa, self.hoy - timedelta(days=dias - 1), self.hoy, **kw)

    def fila(self, sku, **kw):
        return next(f for f in self.datos(**kw)["filas"] if f["producto"].sku == sku)


class CuantoPedir(Base):
    def test_el_que_rota_rapido_pide_antes_con_el_mismo_minimo(self):
        rapido = self.producto("RAPIDO", 80)
        lento = self.producto("LENTO", 20)
        self.vender(rapido, 60, hace_dias=10)   # 2 por día en 30 días; quedan 20 → 10 días
        self.vender(lento, 2, hace_dias=10)
        r, l = self.fila("RAPIDO", ver="vendido"), self.fila("LENTO", ver="vendido")
        self.assertEqual(r["alcanza"], 10)
        self.assertEqual(r["pedir"], 40)        # 2 × 30 − 20
        self.assertEqual(r["estado"], "hay")
        self.assertEqual(l["pedir"], 0)
        self.assertEqual([f["producto"].sku for f in self.datos()["filas"]], ["RAPIDO"])

    def test_pedir_para_45_dias(self):
        p = self.producto("P", 80)
        self.vender(p, 60, hace_dias=10)
        self.assertEqual(self.fila("P", cubrir=45)["pedir"], 70)    # 2 × 45 − 20

    def test_alcanza_poco_es_quedan_pocas(self):
        p = self.producto("URGENTE", 125)
        self.vender(p, 120, hace_dias=5)        # 4 por día; quedan 5
        f = self.fila("URGENTE")
        self.assertEqual(f["estado"], "pocas")
        self.assertEqual(f["alcanza"], 1)

    def test_sin_ventas_no_se_pide_y_nunca_negativo(self):
        self.producto("QUIETO", 1, minimo=5)
        sobra = self.producto("SOBRA", 1000)
        self.vender(sobra, 1)
        self.assertEqual(self.fila("SOBRA", ver="vendido")["pedir"], 0)
        self.assertNotIn("QUIETO", [f["producto"].sku for f in self.datos(ver="vendido")["filas"]])

    def test_los_dias_agotado_no_cuentan(self):
        """Vendió 10 en los primeros 10 días y pasó 20 agotado: vende 1 por
        día, no 10/30. Antes «Qué reponer» lo marcaba pero no lo corregía."""
        p = self.producto("FALTO", 10)
        self.vender(p, 10, hace_dias=25)
        aviso = Agotamiento.objects.get(producto=p)
        Agotamiento.objects.filter(pk=aviso.pk).update(fecha=timezone.now() - timedelta(days=20))
        f = self.fila("FALTO")
        self.assertEqual(f["estado"], "agotado")
        # Unos 9-10 días con existencia de los 30 → ~1 por día; sin corregir sería 0,33.
        self.assertGreater(f["diaria"], Decimal("1"))
        self.assertLess(f["diaria"], Decimal("1.12"))
        self.assertIn(f["pedir"], range(31, 35))

    def test_rango_corto_calcula_con_30_dias(self):
        p = self.producto("P", 80)
        self.vender(p, 58, hace_dias=10)
        self.vender(p, 2)
        d = reponer.datos(self.empresa, self.hoy, self.hoy)
        f = d["filas"][0]
        self.assertTrue(d["base_distinta"])
        self.assertEqual(f["vendidas"], Decimal("2"))        # lo de hoy
        self.assertEqual(f["pedir"], 40)                     # con el ritmo de 30 días

    def test_no_comprar_mas_no_se_pide(self):
        p = self.producto("ADIOS", 3)
        self.vender(p, 3, hace_dias=2)
        Agotamiento.objects.filter(producto=p).update(decision=Agotamiento.Decision.NO_COMPRAR)
        self.assertEqual(self.datos()["filas"], [])
        self.assertEqual(self.fila("ADIOS", ver="vendido")["pedir"], 0)

    def test_agotado_sin_ventas_en_el_rango_sigue_para_pedir(self):
        p = self.producto("VIEJO", 1)
        self.vender(p, 1, hace_dias=60)
        self.assertEqual([f["producto"].sku for f in self.datos()["filas"]], ["VIEJO"])
        self.assertEqual([f["producto"].sku for f in self.datos(ver="agotados")["filas"]], ["VIEJO"])
        self.assertEqual(self.datos(ver="vendido")["filas"], [])

    def test_unidad_suelta_dice_cuantas_cajas(self):
        sobre = self.producto("SOBRE", 40)
        caja = self.producto("CAJA", 0)
        Producto.objects.filter(pk=caja.pk).update(unidad_suelta=sobre, unidades_por_empaque=12)
        self.vender(sobre, 30, hace_dias=5)      # 1 por día; quedan 10 → pedir 20
        f = self.fila("SOBRE", ver="vendido")
        self.assertEqual(f["caja"], caja)
        self.assertEqual((f["pedir"], f["cajas"]), (20, 2))


class PantallaYExcel(Base):
    def setUp(self):
        super().setUp()
        self.prov = Proveedor.objects.create(empresa=self.empresa, nombre="Belina")
        self.bel = self.producto("BEL-77", 80)
        compra = Compra.objects.create(empresa=self.empresa, sucursal=self.sucursal, proveedor=self.prov,
                                       numero="OC-1", factura_proveedor="F-9", estado=Compra.Estado.RECIBIDA)
        LineaCompra.objects.create(compra=compra, producto=self.bel, cantidad=Decimal("10"),
                                   costo_unitario=Decimal("700"), total=Decimal("7000"))
        self.otro = self.producto("OTRO", 10)
        self.vender(self.bel, 60, hace_dias=10)
        self.vender(self.otro, 9, hace_dias=3)
        self.client.force_login(self.usuario)

    def test_pantalla(self):
        r = self.client.get(reverse("inventario:reponer"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Producto BEL-77")
        self.assertContains(r, "Cód. 77")
        self.assertContains(r, "Esta semana")
        # Belina 40 × 700 (última compra) + OTRO 8 × 500 (sin compras: el promedio).
        self.assertEqual(r.context["resumen"]["total"], Decimal("32000"))
        r = self.client.get(reverse("inventario:reponer"), {"proveedor": "Belina"})
        self.assertEqual([f["producto"].sku for f in r.context["filas"]], ["BEL-77"])

    def test_excel_por_proveedor_con_formulas(self):
        from openpyxl import load_workbook

        r = self.client.get(reverse("inventario:reponer_excel"), {"atajo": "30"})
        wb = load_workbook(BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ["Resumen", "Belina", "Sin proveedor"])
        ws = wb["Belina"]
        self.assertEqual((ws["A5"].value, ws["C5"].value), ("77", "Producto BEL-77"))
        self.assertEqual(ws["I5"].value, 40)
        self.assertEqual(ws["J5"].value, 700)
        self.assertEqual(ws["K5"].value, "=IF(ISNUMBER(J5),I5*J5,0)")
        self.assertEqual(ws["I6"].value, "=SUM(I5:I5)")
        res = wb["Resumen"]
        self.assertEqual(res["A5"].value, "Belina")
        self.assertEqual(res["D5"].value, "='Belina'!K6")
        self.assertEqual(res["A7"].value, "TOTAL")


class ConLosDiasDeEntrega(Base):
    """26/11/2026: «quedan pocas» y «Pedir» con lo que tarda cada proveedor."""

    def setUp(self):
        super().setUp()
        self.prov = Proveedor.objects.create(empresa=self.empresa, nombre="Lento", dias_minimos=10,
                                            dias_entrega="0123456")   # todos los días: no depende de hoy
        self.p = self.producto("P", 0)
        from compras.services import crear_y_recibir_compra
        crear_y_recibir_compra(proveedor=self.prov, sucursal=self.sucursal, usuario=self.usuario,
                               lineas=[{"producto": self.p, "cantidad": Decimal("40"), "costo_unitario": Decimal("500")}])
        self.vender(self.p, 30, hace_dias=10)       # 1 por día; quedan 10 → alcanza 10 días

    def test_se_acaba_antes_de_que_llegue(self):
        f = self.fila("P")
        self.assertEqual(f["dias_llegada"], 10)
        self.assertEqual(f["estado"], "pocas")      # con 7 días fijos habría dicho «Hay»
        self.assertEqual(f["pedir"], 30)             # 1 × (30 + 10) − 10

    def test_sin_dias_de_entrega_usa_7(self):
        Proveedor.objects.filter(pk=self.prov.pk).update(dias_minimos=None, dias_entrega="")
        f = self.fila("P", ver="vendido")
        self.assertIsNone(f["llega"])
        self.assertEqual((f["estado"], f["pedir"]), ("hay", 20))


class NoSeVende(Base):
    def test_lo_parado_con_su_valor(self):
        quieto = self.producto("QUIETO", 4)          # costo promedio 500
        vendido = self.producto("VENDE", 4)
        self.vender(vendido, 1, hace_dias=2)
        viejo = self.producto("VIEJO", 2)
        self.vender(viejo, 1, hace_dias=50)
        nuevo = self.producto("NUEVO", 9)
        Producto.objects.filter(pk=nuevo.pk).update(creado_en=timezone.now())   # recién llegado
        d = self.datos(ver="dormido")
        por_sku = {f["producto"].sku: f for f in d["filas"]}
        self.assertEqual(sorted(por_sku), ["QUIETO", "VIEJO"])
        self.assertEqual(por_sku["QUIETO"]["valor"], Decimal("2000"))
        self.assertIsNone(por_sku["QUIETO"]["ultima_venta"])
        self.assertEqual(por_sku["VIEJO"]["dias_sin_vender"], 50)
        self.assertEqual(d["resumen"]["valor"], Decimal("2500"))
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("inventario:reponer"), {"ver": "dormido"})
        self.assertContains(r, "plata parada")
        r = self.client.get(reverse("inventario:reponer_excel"), {"ver": "dormido"})
        from openpyxl import load_workbook
        ws = load_workbook(BytesIO(r.content))["No se vende"]
        self.assertEqual(ws["C5"].value, "Producto QUIETO")
        self.assertEqual(ws["G5"].value, "=E5*F5")
