"""Pruebas del núcleo de inventario: las reglas que protegen el negocio."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Producto
from core.models import AuditLog, Empresa, Sucursal

from .models import Bodega, MovimientoInventario
from .services import registrar_movimiento


class BaseInventario(TestCase):
    def setUp(self):
        empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        sucursal = Sucursal.objects.create(empresa=empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=sucursal, nombre="Principal")
        self.producto = Producto.objects.create(
            empresa=empresa, sku="TEST-001", nombre="Producto de prueba", precio_venta=1000
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("10"), costo_unitario=Decimal("500"), referencia="INI-TEST",
        )
        self.producto.refresh_from_db()


class ReglasDeInventario(BaseInventario):
    def test_carga_inicial_fija_stock_y_costo(self):
        self.assertEqual(self.producto.stock_actual, Decimal("10"))
        self.assertEqual(self.producto.costo_promedio, Decimal("500.00"))

    def test_salida_descuenta_stock(self):
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="VEN",
            cantidad=Decimal("-4"), referencia="FE-TEST",
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("6"))

    def test_no_permite_stock_negativo(self):
        with self.assertRaises(ValidationError):
            registrar_movimiento(
                producto=self.producto, bodega=self.bodega, tipo="VEN",
                cantidad=Decimal("-11"), referencia="FE-TEST",
            )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # intacto

    def test_no_permite_cantidad_cero(self):
        with self.assertRaises(ValidationError):
            registrar_movimiento(
                producto=self.producto, bodega=self.bodega, tipo="AJU",
                cantidad=Decimal("0"), referencia="AJ-TEST",
            )

    def test_costo_promedio_ponderado(self):
        # 10 uds a 500 + 10 uds a 700 = promedio 600
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="COM",
            cantidad=Decimal("10"), costo_unitario=Decimal("700"), referencia="OC-TEST",
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.costo_promedio, Decimal("600.00"))

    def test_salida_no_cambia_costo_promedio(self):
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="VEN",
            cantidad=Decimal("-5"), referencia="FE-TEST",
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.costo_promedio, Decimal("500.00"))

    def test_kardex_guarda_resultantes(self):
        mov = registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="VEN",
            cantidad=Decimal("-3"), referencia="FE-TEST",
        )
        self.assertEqual(mov.stock_resultante, Decimal("7"))
        self.assertEqual(mov.costo_promedio_resultante, Decimal("500.00"))

    def test_todo_movimiento_queda_auditado(self):
        antes = AuditLog.objects.filter(tabla="inventario.movimientoinventario").count()
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="AJU",
            cantidad=Decimal("-1"), referencia="AJ-TEST", motivo="dañado",
        )
        despues = AuditLog.objects.filter(tabla="inventario.movimientoinventario").count()
        self.assertEqual(despues, antes + 1)


class PantallaAjuste(BaseInventario):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user("oscar", password="clave-test", is_staff=True, is_superuser=True)

    def test_requiere_login_de_staff(self):
        respuesta = self.client.get(reverse("inventario:ajuste"))
        self.assertEqual(respuesta.status_code, 302)  # redirige al login

    def test_ajuste_valido_crea_movimiento_con_usuario(self):
        self.client.login(username="oscar", password="clave-test")
        respuesta = self.client.post(reverse("inventario:ajuste"), {
            "producto": self.producto.pk,
            "bodega": self.bodega.pk,
            "cantidad": "-2",
            "costo_unitario": "0",
            "motivo": "Conteo físico: faltante",
        })
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("8"))
        mov = MovimientoInventario.objects.filter(tipo="AJU").latest("id")
        self.assertEqual(mov.usuario, self.staff)
        self.assertIn("faltante", mov.motivo)

    def test_ajuste_a_negativo_muestra_error_sin_mover_stock(self):
        self.client.login(username="oscar", password="clave-test")
        respuesta = self.client.post(reverse("inventario:ajuste"), {
            "producto": self.producto.pk,
            "bodega": self.bodega.pk,
            "cantidad": "-999",
            "costo_unitario": "0",
            "motivo": "prueba",
        })
        self.assertEqual(respuesta.status_code, 200)  # vuelve al formulario
        self.assertContains(respuesta, "Stock insuficiente")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))

    def test_auditoria_captura_usuario_e_ip(self):
        self.client.login(username="oscar", password="clave-test")
        self.client.post(reverse("inventario:ajuste"), {
            "producto": self.producto.pk,
            "bodega": self.bodega.pk,
            "cantidad": "1",
            "costo_unitario": "500",
            "motivo": "Sobrante en conteo",
        })
        log = AuditLog.objects.filter(tabla="inventario.movimientoinventario").latest("fecha")
        self.assertEqual(log.usuario, self.staff)
        self.assertIsNotNone(log.ip)
