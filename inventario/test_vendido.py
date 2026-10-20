"""Lo vendido, para reponer (pedido de Oscar, 20/10/2026)."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.services import abrir_caja
from catalogo.models import Categoria, Producto
from compras.models import Compra, LineaCompra, Proveedor
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from inventario import vendido
from ventas.devoluciones import registrar_devolucion
from ventas.models import FacturaVenta
from ventas.services import anular_factura, registrar_venta


class LoVendidoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Bodega")
        self.usuario = User.objects.create_user("g", password="x", is_staff=True, is_superuser=True)
        self.categoria = Categoria.objects.create(nombre="Test")
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))
        self.hoy = timezone.localdate()

    def _producto(self, sku, stock, minimo=2):
        p = Producto.objects.create(
            empresa=self.empresa, sku=sku, nombre=f"Producto {sku}", categoria=self.categoria,
            precio_venta=Decimal("1000"), costo_promedio=Decimal("500"), stock_minimo=Decimal(minimo),
        )
        registrar_movimiento(producto=p, bodega=self.bodega, tipo="ENT", cantidad=Decimal(stock),
                             costo_unitario=Decimal("500"), referencia="carga", usuario=self.usuario)
        p.refresh_from_db()
        return p

    def _vender(self, producto, cantidad, hace_dias=0):
        f = registrar_venta(sesion_caja=self.sesion, medio_pago=FacturaVenta.MedioPago.EFECTIVO,
                            usuario=self.usuario,
                            lineas=[{"producto_id": producto.pk, "cantidad": Decimal(cantidad)}])
        if hace_dias:
            FacturaVenta.objects.filter(pk=f.pk).update(creado_en=timezone.now() - timedelta(days=hace_dias))
        return f

    def _filas(self, desde=None, hasta=None, **kw):
        return vendido.filas(self.empresa, desde or self.hoy - timedelta(days=6), hasta or self.hoy, **kw)

    def test_cuenta_solo_lo_del_rango_y_lo_ordena_por_urgencia(self):
        sobra = self._producto("SOBRA", 50)
        pocas = self._producto("POCAS", 5)
        cero = self._producto("CERO", 2)
        viejo = self._producto("VIEJO", 10)
        self._vender(sobra, 8)
        self._vender(pocas, 3)
        self._vender(cero, 2)
        self._vender(viejo, 4, hace_dias=30)
        filas = self._filas()
        self.assertEqual([f["producto"].sku for f in filas], ["CERO", "POCAS", "SOBRA"])
        self.assertEqual([f["estado"] for f in filas], ["agotado", "pocas", "hay"])
        self.assertEqual(filas[1]["vendidas"], Decimal("3"))
        self.assertEqual(filas[1]["quedan"], Decimal("2"))
        r = vendido.resumen(filas)
        self.assertEqual((r["productos"], r["unidades"], r["agotados"], r["pocas"]), (3, Decimal("13"), 1, 1))

    def test_anuladas_no_cuentan_y_las_devoluciones_se_restan(self):
        p = self._producto("DEV", 20)
        f = self._vender(p, 5)
        registrar_devolucion(factura=f, motivo="no le quedó",
                             lineas=[{"linea_venta_id": f.lineas.first().pk, "cantidad": Decimal("2")}],
                             usuario=self.usuario)
        g = self._vender(p, 4)
        anular_factura(factura=g, motivo="error", usuario=self.usuario)
        filas = self._filas()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["vendidas"], Decimal("3"))

    def test_trae_el_proveedor_de_la_ultima_compra_y_filtra_por_el(self):
        bel = self._producto("BEL-1234", 10)
        otro = self._producto("OTRO", 10)
        prov = Proveedor.objects.create(empresa=self.empresa, nombre="Belina")
        compra = Compra.objects.create(empresa=self.empresa, sucursal=self.sucursal, proveedor=prov,
                                       numero="OC-T1", estado=Compra.Estado.RECIBIDA)
        LineaCompra.objects.create(compra=compra, producto=bel, cantidad=Decimal("10"),
                                   costo_unitario=Decimal("500"), total=Decimal("5000"))
        self._vender(bel, 1)
        self._vender(otro, 1)
        filas = {f["producto"].sku: f for f in self._filas()}
        self.assertEqual(filas["BEL-1234"]["proveedor"], "Belina")
        self.assertEqual(filas["BEL-1234"]["codigo_proveedor"], "1234")
        self.assertEqual([f["producto"].sku for f in self._filas(proveedor="Belina")], ["BEL-1234"])

    def test_atajos_y_rango_normalizado(self):
        hoy = date(2026, 10, 20)
        self.assertEqual(vendido.rango_de_atajo("hoy", hoy), (hoy, hoy))
        self.assertEqual(vendido.rango_de_atajo("ayer", hoy), (date(2026, 10, 19),) * 2)
        self.assertEqual(vendido.rango_de_atajo("7", hoy), (date(2026, 10, 14), hoy))
        self.assertEqual(vendido.rango_de_atajo("mes", hoy), (date(2026, 10, 1), hoy))
        # Al revés se acomoda; el futuro se corta en hoy; más de un año se recorta.
        self.assertEqual(vendido.normalizar(hoy, date(2026, 10, 1), hoy), (date(2026, 10, 1), hoy))
        self.assertEqual(vendido.normalizar(date(2026, 10, 1), date(2026, 12, 1), hoy), (date(2026, 10, 1), hoy))
        d, h = vendido.normalizar(date(2020, 1, 1), hoy, hoy)
        self.assertEqual((h - d).days + 1, vendido.MAX_DIAS)

    def test_pantalla_y_excel(self):
        p = self._producto("PANT", 3)
        self._vender(p, 2)
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("inventario:vendido"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Producto PANT")
        self.assertContains(r, "Quedan pocas")
        r = self.client.get(reverse("inventario:vendido"), {"desde": "2020-01-01", "hasta": "2020-01-02"})
        self.assertContains(r, "No hubo ventas en esas fechas")
        r = self.client.get(reverse("inventario:vendido_excel"), {"atajo": "hoy"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])

    def test_el_cajero_no_entra(self):
        cajero = User.objects.create_user("c", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(cajero)
        r = self.client.get(reverse("inventario:vendido"))
        self.assertNotEqual(r.status_code, 200)
