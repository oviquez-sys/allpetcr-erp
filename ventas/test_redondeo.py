"""Redondeo del total (17/10/2026). Caso real de Oscar: ₡13.554 en efectivo,
la clienta no tenía para el vuelto y se le cobró ₡13.500."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from caja.models import MovimientoCaja
from caja.test_auditoria_2026_09 import Base
from catalogo.models import Producto
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta
from ventas.services import registrar_venta


class Redondeo(Base):
    def setUp(self):
        super().setUp()
        self.a = Producto.objects.create(empresa=self.empresa, sku="R1", nombre="Alimento", precio_venta=9554)
        self.b = Producto.objects.create(empresa=self.empresa, sku="R2", nombre="Juguete", precio_venta=4000)
        for p in (self.a, self.b):
            registrar_movimiento(producto=p, bodega=Bodega.objects.get(), tipo="INI", cantidad=Decimal("5"),
                                 costo_unitario=Decimal("1000"), referencia="INI")

    def vender(self, redondeo, gerente=True, **extra):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.oscar,
            lineas=[{"producto_id": self.a.pk, "cantidad": 1}, {"producto_id": self.b.pk, "cantidad": 1}],
            redondeo=redondeo, permitir_descuento_alto=gerente, permitir_bajo_costo=gerente, **extra)

    def test_13554_se_cobra_13500(self):
        f = self.vender(54, monto_recibido=13500)
        self.assertEqual(f.total, Decimal("13500"))
        self.assertEqual(f.redondeo, Decimal("54"))
        self.assertEqual(f.descuento, Decimal("54"))
        self.assertEqual(f.descuento_sin_redondeo, Decimal("0"))
        self.assertEqual(f.vuelto, Decimal("0"))
        lineas = list(f.lineas.all())
        self.assertEqual(sum(l.redondeo for l in lineas), Decimal("54"))
        self.assertEqual(sum(l.total for l in lineas), Decimal("13500"))
        self.assertEqual(sum(l.subtotal + l.impuesto for l in lineas), Decimal("13500"))
        # La caja espera lo que de verdad entró: el cierre cuadra.
        self.assertEqual(MovimientoCaja.objects.filter(tipo="VEN").get().monto, Decimal("13500"))

    def test_el_tiquete_lo_muestra_aparte(self):
        f = self.vender(54)
        self.client.force_login(self.oscar)
        html = self.client.get(reverse("ventas:tiquete", args=[f.pk])).content.decode()
        self.assertIn("Redondeo", html)
        self.assertNotIn("Descuentos", html)

    def test_topes(self):
        with self.assertRaises(ValidationError):
            self.vender(600, gerente=False)          # cajero: hasta ₡500
        self.assertEqual(self.vender(600).redondeo, Decimal("600"))   # gerente: hasta ₡1.000
        with self.assertRaises(ValidationError):
            self.vender(1500)
        with self.assertRaises(ValidationError):
            self.vender("54.5")
        self.assertEqual(FacturaVenta.objects.count(), 1)

    def test_sin_redondeo_todo_igual(self):
        f = self.vender(0)
        self.assertEqual(f.total, Decimal("13554"))
        self.assertEqual(f.redondeo, Decimal("0"))

    def test_desde_la_pantalla(self):
        self.client.force_login(self.oscar)
        r = self.client.post(reverse("ventas:vender"), {
            "medio_pago": "EFE", "redondeo": 54,
            "lineas": [{"producto_id": self.a.pk, "cantidad": 1}, {"producto_id": self.b.pk, "cantidad": 1}],
        }, content_type="application/json")
        self.assertTrue(r.json()["ok"], r.json())
        self.assertEqual(FacturaVenta.objects.get().total, Decimal("13500"))
        html = self.client.get(reverse("ventas:pos")).content.decode()
        self.assertIn("Redondear el total", html)
        self.assertIn("const REDONDEO_MAX = 1000", html)
