"""Pruebas de los reportes avanzados (Sprint E):

- Estado de resultados: se arma solo desde los asientos; ingresos − costo −
  gastos = utilidad, y concuerda con lo vendido.
- IVA trimestral (RTS): agrupa compras recibidas por trimestre y aplica el
  factor configurable; sin factor, no calcula impuesto.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from caja.services import abrir_caja
from catalogo.models import Producto
from compras.models import Compra, Proveedor
from compras.services import crear_compra, recibir_compra
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.services import registrar_venta


class BaseReportes(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")  # RTS, factor_rts=0
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.gerente = User.objects.create_user(
            "gerente", password="x", is_staff=True, is_superuser=True
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Cama", precio_venta=Decimal("10000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("50"), costo_unitario=Decimal("6000"), referencia="INI",
        )
        self.producto.refresh_from_db()
        self.sesion = abrir_caja(
            sucursal=self.sucursal, usuario=self.gerente, monto_apertura=Decimal("0")
        )

    def vender(self, cantidad):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.gerente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": cantidad}],
        )


class EstadoResultadosTest(BaseReportes):
    def test_utilidad_bruta_es_ventas_menos_costo(self):
        # Vendo 3 unidades: ingreso 3×10000=30000, costo 3×6000=18000.
        self.vender(3)
        self.client.force_login(self.gerente)
        resp = self.client.get("/contabilidad/estado-resultados/")
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx["total_ingresos"], Decimal("30000"))
        self.assertEqual(ctx["costo_ventas"], Decimal("18000"))
        self.assertEqual(ctx["utilidad_bruta"], Decimal("12000"))
        # Sin otros gastos, la utilidad neta = utilidad bruta.
        self.assertEqual(ctx["utilidad_neta"], Decimal("12000"))

    def test_rango_de_fechas_excluye_lo_de_afuera(self):
        self.vender(2)
        self.client.force_login(self.gerente)
        # Rango en el pasado, sin movimientos: todo en cero.
        resp = self.client.get("/contabilidad/estado-resultados/?desde=2000-01-01&hasta=2000-12-31")
        self.assertEqual(resp.context["total_ingresos"], Decimal("0"))
        self.assertEqual(resp.context["utilidad_neta"], Decimal("0"))

    def test_requiere_rol(self):
        cajero = User.objects.create_user("cajero", password="x", is_staff=True)
        self.client.force_login(cajero)
        resp = self.client.get("/contabilidad/estado-resultados/")
        self.assertIn(resp.status_code, (302, 403))


class IvaTrimestralTest(BaseReportes):
    def _compra_recibida(self, total_costo):
        prov = Proveedor.objects.create(empresa=self.empresa, nombre="Prov")
        compra = crear_compra(
            proveedor=prov, sucursal=self.sucursal,
            lineas=[{"producto": self.producto, "cantidad": Decimal("1"),
                     "costo_unitario": Decimal(str(total_costo))}],
            usuario=self.gerente,
        )
        return recibir_compra(compra=compra, usuario=self.gerente)

    def test_agrupa_compras_del_anio_y_sin_factor_no_calcula(self):
        self._compra_recibida("100000")
        self.client.force_login(self.gerente)
        anio = timezone.localdate().year
        resp = self.client.get(f"/contabilidad/iva-trimestral/?anio={anio}")
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx["total_compras"], Decimal("100000"))
        # factor 0 => sin impuesto calculado
        self.assertFalse(ctx["hay_factor"])
        self.assertEqual(ctx["total_impuesto"], Decimal("0"))

    def test_con_factor_calcula_impuesto(self):
        self.empresa.factor_rts = Decimal("0.02")
        self.empresa.save(update_fields=["factor_rts"])
        self._compra_recibida("100000")
        self.client.force_login(self.gerente)
        anio = timezone.localdate().year
        resp = self.client.get(f"/contabilidad/iva-trimestral/?anio={anio}")
        ctx = resp.context
        self.assertTrue(ctx["hay_factor"])
        # 100000 × 0.02 = 2000
        self.assertEqual(ctx["total_impuesto"], Decimal("2000.00"))

    def test_suma_cuatro_trimestres_igual_al_total(self):
        self.empresa.factor_rts = Decimal("0.02")
        self.empresa.save(update_fields=["factor_rts"])
        self._compra_recibida("50000")
        self.client.force_login(self.gerente)
        anio = timezone.localdate().year
        resp = self.client.get(f"/contabilidad/iva-trimestral/?anio={anio}")
        ctx = resp.context
        suma = sum((t["compras"] for t in ctx["trimestres"]), Decimal("0"))
        self.assertEqual(suma, ctx["total_compras"])
        self.assertEqual(len(ctx["trimestres"]), 4)
