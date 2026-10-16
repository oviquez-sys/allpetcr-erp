"""Descuento de la factura del proveedor (16/10/2026).

Caso real que lo pidió: una compra de Belina con ₡29.260 de subtotal, ₡878 de
descuento y ₡3.690 de IVA (el 13 % de ₡28.382, o sea calculado después del
descuento).
"""
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from catalogo.models import Producto
from core.models import Empresa
from inventario.models import MovimientoInventario

from .models import Compra
from .services import anular_compra, crear_compra, recibir_compra, repartir_descuento
from .tests import BaseCompras


class DescuentoDeFactura(BaseCompras):
    def setUp(self):
        super().setUp()
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL
        self.empresa.save()
        self.nutri = Producto.objects.create(empresa=self.empresa, sku="N1", nombre="NutriSource", precio_venta=9775)
        self.adult = Producto.objects.create(empresa=self.empresa, sku="B1", nombre="Balance Adult", precio_venta=5275)
        self.adulto = Producto.objects.create(empresa=self.empresa, sku="B2", nombre="Balance Adulto", precio_venta=24000)

    def comprar(self, descuento="878", forma="CON"):
        compra = crear_compra(
            proveedor=self.proveedor, sucursal=self.sucursal, forma_pago=forma, usuario=self.usuario,
            lineas=[{"producto": self.nutri, "cantidad": 1, "costo_unitario": 6930},
                    {"producto": self.adult, "cantidad": 1, "costo_unitario": 4000},
                    {"producto": self.adulto, "cantidad": 1, "costo_unitario": 18330}],
            iva="3690", descuento=descuento,
        )
        return recibir_compra(compra=compra, usuario=self.usuario)

    def test_la_factura_de_belina_cuadra(self):
        compra = self.comprar()
        self.assertEqual(compra.descuento, Decimal("878"))
        self.assertEqual(compra.total, Decimal("28382"))           # 29.260 − 878
        self.assertEqual(compra.total_factura, Decimal("32072"))   # + 3.690 de IVA
        self.assertEqual(self.saldo("inventario")[0], Decimal("28382"))
        self.assertEqual(self.saldo("bancos")[1], Decimal("32072"))

    def test_las_lineas_guardan_su_precio_de_factura_y_su_parte(self):
        compra = self.comprar()
        lineas = {l.producto.sku: l for l in compra.lineas.select_related("producto")}
        self.assertEqual(lineas["B2"].total, Decimal("18330"))     # lo que dice el papel
        self.assertEqual(sum(l.descuento for l in lineas.values()), Decimal("878"))
        self.assertEqual(lineas["N1"].descuento, Decimal("207.94"))
        self.assertEqual(lineas["B2"].costo_real_unitario, Decimal("17779.96"))

    def test_el_inventario_entra_con_el_costo_ya_descontado(self):
        self.comprar()
        entradas = MovimientoInventario.objects.filter(tipo="COM")
        valor = sum(m.cantidad * m.costo_unitario for m in entradas)
        self.assertEqual(valor, Decimal("28382"))                  # cuadra con la contabilidad
        self.adulto.refresh_from_db()
        self.assertEqual(self.adulto.costo_promedio, Decimal("17779.96"))

    def test_a_credito_se_debe_lo_de_la_factura(self):
        self.comprar(forma="CRE")
        self.proveedor.refresh_from_db()
        self.assertEqual(self.proveedor.saldo, Decimal("32072"))

    def test_anular_devuelve_todo(self):
        compra = self.comprar(forma="CRE")
        anular_compra(compra=compra, motivo="error", usuario=self.usuario)
        debe, haber = self.saldo("inventario")
        self.assertEqual(debe - haber, Decimal("0"))
        self.proveedor.refresh_from_db()
        self.assertEqual(self.proveedor.saldo, Decimal("0"))

    def test_sin_descuento_todo_sigue_igual(self):
        compra = self.comprar(descuento="0")
        self.assertEqual(compra.total, Decimal("29260"))
        self.assertFalse(compra.lineas.exclude(descuento=0).exists())

    def test_no_acepta_negativo_ni_mayor_que_el_subtotal(self):
        with self.assertRaises(ValidationError):
            self.comprar(descuento="-5")
        with self.assertRaises(ValidationError):
            self.comprar(descuento="29260")
        self.assertFalse(Compra.objects.exists())

    def test_el_reparto_siempre_suma_exacto(self):
        partes = repartir_descuento(Decimal("100"), [Decimal("1"), Decimal("1"), Decimal("1")])
        self.assertEqual(sum(partes), Decimal("100"))
        self.assertEqual(repartir_descuento(Decimal("50"), [Decimal("0"), Decimal("10")]), [Decimal("0"), Decimal("50")])

    def test_la_pantalla_lo_manda(self):
        self.client.login(username="oscar", password="x")
        html = self.client.get(reverse("compras:nueva")).content.decode()
        self.assertIn('id="descuentoFactura"', html)
        r = self.client.post(reverse("compras:registrar"), data=json.dumps({
            "proveedor_id": self.proveedor.pk, "forma_pago": "CON", "iva": 3690, "descuento": 878,
            "lineas": [{"producto_id": self.nutri.pk, "cantidad": 1, "costo_unitario": 6930},
                       {"producto_id": self.adult.pk, "cantidad": 1, "costo_unitario": 4000},
                       {"producto_id": self.adulto.pk, "cantidad": 1, "costo_unitario": 18330}],
        }), content_type="application/json")
        self.assertTrue(r.json()["ok"], r.json())
        self.assertEqual(r.json()["total"], 32072.0)
