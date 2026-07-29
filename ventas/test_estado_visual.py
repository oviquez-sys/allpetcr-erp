"""FacturaVenta.estado_visual: mapea Emitida/Anulada + DocumentoCxC a los
tres estados que el cliente ve en la factura a color (Pagada/Pendiente/Anulada).

El modelo no tiene un campo "pagada": una venta de contado nunca genera CxC,
y una venta a crédito sí. Estas pruebas fijan esa traducción para que el
rediseño de la factura no tenga que reinventarla ni un futuro cambio la rompa
en silencio.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from caja.services import abrir_caja
from catalogo.models import Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .cxc import registrar_abono
from .models import Cliente
from .services import anular_factura, registrar_venta


class EstadoVisualTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPetCR", identificacion="3-102-000000")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("cajero", password="x", is_staff=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P1", nombre="Alimento", precio_venta=Decimal("10000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("50"), costo_unitario=Decimal("4000"), referencia="INI",
        )
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="Cliente credito", limite_credito=Decimal("50000")
        )
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))

    def _vender(self, medio_pago, cliente=None):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago=medio_pago, usuario=self.usuario, cliente=cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": Decimal("1")}],
        )

    def test_venta_de_contado_es_pagada(self):
        factura = self._vender("EFE")
        self.assertEqual(factura.estado_visual, "PAG")
        self.assertEqual(factura.estado_visual_display, "Pagada")

    def test_venta_a_credito_recien_hecha_es_pendiente(self):
        factura = self._vender("CRE", cliente=self.cliente)
        self.assertEqual(factura.estado_visual, "PEN")
        self.assertEqual(factura.estado_visual_display, "Pendiente")

    def test_venta_a_credito_saldada_es_pagada(self):
        factura = self._vender("CRE", cliente=self.cliente)
        registrar_abono(documento=factura.cxc, monto=factura.total, usuario=self.usuario, medio="EFE")
        factura.refresh_from_db()
        self.assertEqual(factura.estado_visual, "PAG")

    def test_venta_anulada_es_anulada_incluso_si_era_pendiente(self):
        """Anulada manda sobre cualquier otro estado: no importa si tenía
        saldo pendiente, lo primero que se muestra es que se anuló."""
        factura = self._vender("CRE", cliente=self.cliente)
        anular_factura(factura=factura, motivo="prueba", usuario=self.usuario)
        factura.refresh_from_db()
        self.assertEqual(factura.estado_visual, "ANU")
        self.assertEqual(factura.estado_visual_display, "Anulada")

    def test_venta_de_contado_no_tiene_cxc(self):
        """Confirma la premisa del helper: sin crédito no hay DocumentoCxC."""
        factura = self._vender("TAR")
        self.assertFalse(hasattr(factura, "cxc"))
