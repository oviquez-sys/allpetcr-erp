"""El crédito se autoriza contra los documentos, no contra el campo `saldo`.

El hueco que cierra
-------------------
`Cliente.saldo` es un valor denormalizado — lo dice el propio docstring del
modelo: "la fuente de verdad es la suma de documentos CxC pendientes". Pero
hasta esta versión `validar_credito` autorizaba contra ese campo.

La diferencia no es teórica. Si `saldo` quedaba por debajo de la deuda real
—una corrección a mano en el admin, una transacción interrumpida, un proceso
a medias— el sistema aprobaba ventas a crédito por encima del límite del
cliente, y nada lo detectaba hasta la próxima corrida de `manage.py
reconciliar`, que a la fecha de este cambio todavía no está programada.

Es el caso clásico de un control que parece existir y no existe.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from caja.services import abrir_caja
from catalogo.models import Categoria, Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.cxc import deuda_real, validar_credito
from ventas.models import Cliente, DocumentoCxC, FacturaVenta
from ventas.services import registrar_venta


class CreditoContraDocumentos(TestCase):

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Bodega")
        self.usuario = User.objects.create_user("g", password="x", is_staff=True, is_superuser=True)
        self.categoria = Categoria.objects.create(nombre="Test")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="CR-1", nombre="Alimento",
            categoria=self.categoria, precio_venta=Decimal("10000"),
            costo_promedio=Decimal("5000"), stock_minimo=Decimal("1"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="ENT",
            cantidad=Decimal("500"), costo_unitario=Decimal("5000"),
            referencia="carga", usuario=self.usuario,
        )
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario,
                                 monto_apertura=Decimal("0"))
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="Deudor", limite_credito=Decimal("50000"),
        )

    def _vender_credito(self, cantidad):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago=FacturaVenta.MedioPago.CREDITO,
            usuario=self.usuario, cliente=self.cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": Decimal(cantidad)}],
        )

    def test_bloquea_aunque_el_saldo_denormalizado_este_bajo(self):
        """EL CASO QUE ANTES SE COLABA.

        El cliente debe ₡40.000 en documentos y su límite es ₡50.000, así que
        sólo le quedan ₡10.000. Se ensucia `saldo` a mano dejándolo en cero —
        exactamente lo que produce una corrección manual en el admin.

        Con la lógica vieja el sistema veía ₡50.000 disponibles y aprobaba una
        venta de ₡30.000, dejando al cliente ₡70.000 por encima de su límite.
        """
        self._vender_credito(4)  # ₡40.000
        self.cliente.refresh_from_db()
        self.assertEqual(deuda_real(self.cliente), Decimal("40000"))

        # Se corrompe el denormalizado, como pasaría por una edición a mano.
        self.cliente.saldo = Decimal("0")
        self.cliente.save(update_fields=["saldo"])
        self.cliente.refresh_from_db()

        # El atajo viejo diría que hay ₡50.000 disponibles.
        self.assertEqual(self.cliente.credito_disponible, Decimal("50000"))

        # La validación real mira los documentos y rechaza.
        with self.assertRaises(ValidationError) as cm:
            validar_credito(self.cliente, Decimal("30000"))
        self.assertIn("reconciliar", str(cm.exception),
                      "el mensaje debería avisar del descuadre, no sólo rechazar")

    def test_autoriza_lo_que_de_verdad_cabe_en_el_limite(self):
        """No se volvió restrictivo de más: lo que entra en el límite pasa."""
        self._vender_credito(3)  # ₡30.000 de ₡50.000
        self.cliente.refresh_from_db()
        validar_credito(self.cliente, Decimal("20000"))  # justo el disponible

    def test_rechaza_lo_que_excede_el_limite(self):
        self._vender_credito(3)  # ₡30.000
        self.cliente.refresh_from_db()
        with self.assertRaises(ValidationError):
            validar_credito(self.cliente, Decimal("20001"))

    def test_un_documento_pagado_libera_credito(self):
        """La deuda baja al cobrar, calculada desde los documentos."""
        from ventas.cxc import registrar_abono

        self._vender_credito(5)  # ₡50.000: consume todo el límite
        self.cliente.refresh_from_db()
        with self.assertRaises(ValidationError):
            validar_credito(self.cliente, Decimal("1000"))

        doc = DocumentoCxC.objects.get(cliente=self.cliente)
        registrar_abono(documento=doc, monto=Decimal("50000"), medio="EFE",
                        usuario=self.usuario)

        self.cliente.refresh_from_db()
        self.assertEqual(deuda_real(self.cliente), Decimal("0"))
        validar_credito(self.cliente, Decimal("50000"))

    def test_los_documentos_anulados_no_consumen_credito(self):
        """Anular una venta a crédito tiene que devolver el cupo."""
        from ventas.services import anular_factura

        factura = self._vender_credito(5)  # consume el límite entero
        self.cliente.refresh_from_db()
        self.assertEqual(deuda_real(self.cliente), Decimal("50000"))

        anular_factura(factura=factura, motivo="prueba", usuario=self.usuario)

        self.cliente.refresh_from_db()
        self.assertEqual(deuda_real(self.cliente), Decimal("0"),
                         "un documento anulado no debería seguir consumiendo crédito")
        validar_credito(self.cliente, Decimal("50000"))

    def test_sin_credito_habilitado_sigue_bloqueado(self):
        sin_credito = Cliente.objects.create(
            empresa=self.empresa, nombre="Contado", limite_credito=Decimal("0"),
        )
        with self.assertRaises(ValidationError):
            validar_credito(sin_credito, Decimal("1"))
