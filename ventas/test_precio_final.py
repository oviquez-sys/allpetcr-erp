"""Descuento por precio final (13/10/2026, pedido de Oscar).

"Vale ₡2.350 y se lo dejo en ₡2.000": el cajero escribe el precio y el
porcentaje sale solo. Lo que no se puede romper: que el total cierre EXACTO
en ese precio y que sigan mandando las reglas de siempre (tope del cajero,
piso de costo, cupón que no se suma).
"""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError

from catalogo.models import Producto
from inventario.services import registrar_movimiento

from .services import registrar_venta
from .test_auditoria_2026_09 import Base


class PrecioFinal(Base):
    def setUp(self):
        super().setUp()
        self.p = Producto.objects.create(empresa=self.empresa, sku="P2350", nombre="Pechera",
                                         precio_venta=Decimal("2350"), impuesto=self.iva)
        registrar_movimiento(producto=self.p, bodega=self.bodega, tipo="INI", cantidad=Decimal("10"),
                             costo_unitario=Decimal("1000"), referencia="INI")

    def venta(self, precio_final, cantidad=1, **extra):
        return registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                               lineas=[{"producto_id": self.p.pk, "cantidad": cantidad,
                                        "precio_final": precio_final}], **extra)

    def test_cierra_exacto_en_el_precio_dicho(self):
        f = self.venta(2000, cantidad=2)
        linea = f.lineas.get()
        self.assertEqual(f.total, Decimal("4000.00"))
        self.assertEqual(linea.descuento_monto, Decimal("700.00"))
        self.assertEqual(linea.descuento_pct, Decimal("14.89"))

    def test_el_tope_del_cajero_sigue_mandando(self):
        # ₡1.990 de ₡2.350 = 15,32 %: más que el 15 % que un cajero decide solo.
        with self.assertRaisesMessage(ValidationError, "15"):
            self.venta(1990, permitir_descuento_alto=False)
        f = self.venta(1990, permitir_descuento_alto=True)   # el gerente sí
        self.assertEqual(f.total, Decimal("1990.00"))

    def test_bajo_costo_no_pasa(self):
        # Sin IVA, ₡1.100 son ₡973: debajo del costo de ₡1.000.
        with self.assertRaisesMessage(ValidationError, "costo"):
            self.venta(1100, permitir_descuento_alto=True)

    def test_no_puede_ser_mayor_que_el_precio(self):
        with self.assertRaisesMessage(ValidationError, "precio final"):
            self.venta(2400)

    def test_vacio_es_sin_descuento(self):
        self.assertEqual(self.venta("").total, Decimal("2350.00"))
