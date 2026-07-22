"""Pruebas de crédito y cuentas por cobrar (S4)."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from caja.services import abrir_caja
from catalogo.models import Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .cxc import registrar_abono
from .models import Abono, Cliente, DocumentoCxC, FacturaVenta
from .services import anular_factura, registrar_venta


class BaseCredito(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Cama M", precio_venta=Decimal("10000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("50"), costo_unitario=Decimal("6000"), referencia="INI",
        )
        self.producto.refresh_from_db()
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="Veterinaria San Roque", limite_credito=Decimal("50000")
        )
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))

    def vender_credito(self, cantidad, cliente=None):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago="CRE", usuario=self.usuario,
            cliente=cliente or self.cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": cantidad}],
        )


class VentaACredito(BaseCredito):
    def test_credito_genera_cxc_y_sube_saldo(self):
        factura = self.vender_credito(2)  # 20000
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo, Decimal("20000"))
        doc = DocumentoCxC.objects.get(factura=factura)
        self.assertEqual(doc.saldo, Decimal("20000"))
        self.assertEqual(doc.estado, DocumentoCxC.Estado.PENDIENTE)

    def test_credito_no_mueve_caja(self):
        from caja.models import MovimientoCaja
        self.vender_credito(1)
        self.assertFalse(MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.VENTA).exists())

    def test_excede_limite_revienta_venta(self):
        with self.assertRaises(ValidationError):
            self.vender_credito(6)  # 60000 > 50000
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo, Decimal("0"))
        self.assertEqual(FacturaVenta.objects.count(), 0)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("50"))  # inventario intacto

    def test_credito_exige_cliente(self):
        with self.assertRaises(ValidationError):
            registrar_venta(
                sesion_caja=self.sesion, medio_pago="CRE", usuario=self.usuario, cliente=None,
                lineas=[{"producto_id": self.producto.pk, "cantidad": 1}],
            )

    def test_cliente_sin_limite_no_recibe_credito(self):
        sin_credito = Cliente.objects.create(empresa=self.empresa, nombre="Nuevo", limite_credito=Decimal("0"))
        with self.assertRaises(ValidationError):
            self.vender_credito(1, cliente=sin_credito)

    def test_dos_ventas_acumulan_hasta_el_limite(self):
        self.vender_credito(3)  # 30000
        self.vender_credito(2)  # 20000 -> total 50000, justo el límite
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo, Decimal("50000"))
        with self.assertRaises(ValidationError):
            self.vender_credito(1)  # ya no hay disponible


class Abonos(BaseCredito):
    def test_abono_parcial_baja_saldos(self):
        factura = self.vender_credito(3)  # 30000
        doc = DocumentoCxC.objects.get(factura=factura)
        registrar_abono(documento=doc, monto=Decimal("10000"), medio="EFE", usuario=self.usuario)
        doc.refresh_from_db(); self.cliente.refresh_from_db()
        self.assertEqual(doc.saldo, Decimal("20000"))
        self.assertEqual(self.cliente.saldo, Decimal("20000"))
        self.assertEqual(doc.estado, DocumentoCxC.Estado.PENDIENTE)

    def test_abono_total_marca_pagado(self):
        factura = self.vender_credito(2)  # 20000
        doc = DocumentoCxC.objects.get(factura=factura)
        registrar_abono(documento=doc, monto=Decimal("20000"), medio="EFE", usuario=self.usuario)
        doc.refresh_from_db(); self.cliente.refresh_from_db()
        self.assertEqual(doc.saldo, Decimal("0"))
        self.assertEqual(doc.estado, DocumentoCxC.Estado.PAGADO)
        self.assertEqual(self.cliente.saldo, Decimal("0"))

    def test_abono_mayor_al_saldo_se_rechaza(self):
        factura = self.vender_credito(1)  # 10000
        doc = DocumentoCxC.objects.get(factura=factura)
        with self.assertRaises(ValidationError):
            registrar_abono(documento=doc, monto=Decimal("15000"), usuario=self.usuario)

    def test_abono_efectivo_entra_a_caja(self):
        from caja.models import MovimientoCaja
        factura = self.vender_credito(2)
        doc = DocumentoCxC.objects.get(factura=factura)
        registrar_abono(documento=doc, monto=Decimal("5000"), medio="EFE", usuario=self.usuario)
        mov = MovimientoCaja.objects.get(tipo=MovimientoCaja.Tipo.INGRESO)
        self.assertEqual(mov.monto, Decimal("5000"))

    def test_abono_sinpe_no_toca_caja(self):
        from caja.models import MovimientoCaja
        factura = self.vender_credito(2)
        doc = DocumentoCxC.objects.get(factura=factura)
        registrar_abono(documento=doc, monto=Decimal("5000"), medio="SIN", usuario=self.usuario)
        self.assertFalse(MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.INGRESO).exists())


class AnulacionCredito(BaseCredito):
    def test_anular_credito_sin_abonos_libera_credito(self):
        factura = self.vender_credito(3)  # 30000
        anular_factura(factura=factura, motivo="error de digitación", usuario=self.usuario)
        self.cliente.refresh_from_db()
        doc = DocumentoCxC.objects.get(factura=factura)
        self.assertEqual(self.cliente.saldo, Decimal("0"))
        self.assertEqual(doc.estado, DocumentoCxC.Estado.ANULADO)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("50"))  # inventario regresó

    def test_no_anula_credito_con_abonos(self):
        factura = self.vender_credito(3)
        doc = DocumentoCxC.objects.get(factura=factura)
        registrar_abono(documento=doc, monto=Decimal("5000"), medio="SIN", usuario=self.usuario)
        with self.assertRaises(ValidationError):
            anular_factura(factura=factura, motivo="intento", usuario=self.usuario)
