"""Pruebas del comando de reconciliación y del orden estable de bloqueo.

Cubren:
- reconciliar detecta cuando todo cuadra (salida limpia).
- reconciliar detecta un stock denormalizado corrompido a mano.
- reconciliar detecta un saldo de cliente corrompido a mano.
- una venta con líneas en orden de producto descendente se procesa igual
  (el sorted() del fix de deadlock no altera los totales ni el stock).
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from caja.services import abrir_caja
from catalogo.models import Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import Cliente
from ventas.services import registrar_venta


class BaseRecon(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user(
            "oscar", password="clave-test", is_staff=True, is_superuser=True
        )
        self.p1 = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Arnés", precio_venta=Decimal("5000")
        )
        self.p2 = Producto.objects.create(
            empresa=self.empresa, sku="P-002", nombre="Correa", precio_venta=Decimal("3000")
        )
        for p in (self.p1, self.p2):
            registrar_movimiento(
                producto=p, bodega=self.bodega, tipo="INI",
                cantidad=Decimal("10"), costo_unitario=Decimal("1000"), referencia="INI",
            )
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.sesion = abrir_caja(
            sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("20000")
        )

    def correr(self):
        salida = StringIO()
        call_command("reconciliar", stdout=salida)
        return salida.getvalue()


class Reconciliacion(BaseRecon):
    def test_todo_cuadra_recien_creado(self):
        salida = self.correr()
        self.assertIn("Todo cuadra", salida)

    def test_detecta_stock_corrompido(self):
        # Corromper el denormalizado a mano (sin pasar por el kardex).
        Producto.objects.filter(pk=self.p1.pk).update(stock_actual=Decimal("999"))
        salida = self.correr()
        self.assertIn("DIF", salida)
        self.assertIn("P-001", salida)
        self.assertIn("diferencia", salida.lower())

    def test_detecta_saldo_cliente_corrompido(self):
        cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="Fulano", limite_credito=Decimal("100000")
        )
        # Venta a crédito: sube el saldo del cliente por la vía correcta.
        registrar_venta(
            sesion_caja=self.sesion, medio_pago="CRE", usuario=self.usuario, cliente=cliente,
            lineas=[{"producto_id": self.p1.pk, "cantidad": Decimal("1")}],
        )
        # Ahora corromper el saldo del cliente a mano.
        Cliente.objects.filter(pk=cliente.pk).update(saldo=Decimal("1"))
        salida = self.correr()
        self.assertIn("DIF", salida)
        self.assertIn("Fulano", salida)


class OrdenEstableDeBloqueo(BaseRecon):
    def test_venta_lineas_en_orden_descendente(self):
        # Líneas con el producto de id mayor primero: el fix las reordena por
        # id antes de bloquear, pero el resultado debe ser idéntico.
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[
                {"producto_id": self.p2.pk, "cantidad": Decimal("2")},  # 2 x 3000 = 6000
                {"producto_id": self.p1.pk, "cantidad": Decimal("1")},  # 1 x 5000 = 5000
            ],
        )
        self.assertEqual(factura.total, Decimal("11000"))
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.stock_actual, Decimal("9"))
        self.assertEqual(self.p2.stock_actual, Decimal("8"))
        # Y el sistema queda cuadrado tras la venta.
        salida = self.correr()
        self.assertIn("Todo cuadra", salida)
