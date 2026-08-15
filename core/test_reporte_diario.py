"""Pruebas del reporte diario a los socios (FRA-004, auditoría 2026-08-15).

No mockea SMTP a mano: usa el backend de correo de pruebas de Django
(django.core.mail.outbox), igual que ya hace ventas/tests.py para
factura_enviar. Los datos del reporte se generan con los mismos servicios
de dominio que usa el sistema real (registrar_venta, abrir_caja/cerrar_caja,
anular_factura) en vez de fabricar filas sueltas — así la prueba también
confirma que el reporte lee lo que esos servicios realmente escriben.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from caja.services import abrir_caja, cerrar_caja
from catalogo.models import Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.services import anular_factura, registrar_venta


class BaseReporteDiario(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM", identificacion="3-102-000000")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("oscar", password="clave-test", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Arnés prueba", precio_venta=Decimal("5000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("50"), costo_unitario=Decimal("2000"), referencia="INI",
        )
        self.producto.refresh_from_db()
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("20000"))
        self.hoy = timezone.localdate()

    def correr(self, fecha=None, destinatarios="socio1@x.com,socio2@x.com"):
        mail.outbox.clear()
        call_command(
            "reporte_diario",
            fecha=(fecha or self.hoy).isoformat(),
            destinatarios=destinatarios,
            verbosity=0,
        )


class ContenidoDelReporte(BaseReporteDiario):
    def test_ventas_del_dia_aparecen_en_el_correo(self):
        registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2}],
        )
        self.correr()
        self.assertEqual(len(mail.outbox), 1)
        cuerpo = mail.outbox[0].body
        self.assertIn("10.000,00", cuerpo)  # 2 × 5000, formato CR
        self.assertIn("1 venta", cuerpo)

    def test_regalia_sobre_tope_aparece_marcada(self):
        # 2 unidades × 5000 = 10000 > REGALIA_MAXIMA_SIN_AUTORIZACION (5000)
        registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2, "es_regalia": True, "motivo": "prueba"}],
            permitir_regalia_alta=True,
        )
        self.correr()
        cuerpo = mail.outbox[0].body
        self.assertIn("Arnés prueba", cuerpo)
        self.assertIn("10.000,00", cuerpo)  # 2 × 5000, el valor regalado
        self.assertNotIn("Sin regalías por encima del tope hoy.", cuerpo)

    def test_descuento_alto_aparece_marcado(self):
        # 20% sobre 5000 = 4000, no baja del costo (2000): pasa el piso de
        # costo, solo activa el techo de descuento (SEC-001).
        registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 20}],
            permitir_descuento_alto=True,
        )
        self.correr()
        cuerpo = mail.outbox[0].body
        self.assertIn("20", cuerpo)
        self.assertNotIn("Sin descuentos por encima del umbral hoy.", cuerpo)

    def test_diferencia_de_caja_aparece(self):
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("19000"), usuario=self.usuario)  # falta 1000
        self.correr()
        cuerpo = mail.outbox[0].body
        self.assertIn("oscar", cuerpo)
        self.assertIn("1.000,00", cuerpo)

    def test_edicion_de_documento_financiero_aparece(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}],
        )
        anular_factura(factura=factura, motivo="prueba", usuario=self.usuario)
        self.correr()
        cuerpo = mail.outbox[0].body
        self.assertIn("ventas.facturaventa", cuerpo)
        self.assertNotIn("Sin ediciones ni borrados sobre documentos financieros hoy.", cuerpo)

    def test_dia_sin_datos_no_rompe_y_manda_correo_con_secciones_vacias(self):
        self.correr()
        self.assertEqual(len(mail.outbox), 1)
        cuerpo = mail.outbox[0].body
        self.assertIn("Sin regalías por encima del tope hoy.", cuerpo)
        self.assertIn("Sin descuentos por encima del umbral hoy.", cuerpo)
        self.assertIn("Ninguna sesión de caja cerrada hoy.", cuerpo)
        self.assertIn("Sin ediciones ni borrados sobre documentos financieros hoy.", cuerpo)

    def test_no_confunde_datos_de_otro_dia(self):
        registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}],
        )
        # Pide el reporte de AYER: la venta de hoy no debe aparecer.
        self.correr(fecha=self.hoy - timedelta(days=1))
        cuerpo = mail.outbox[0].body
        self.assertIn("0 ventas", cuerpo)
        self.assertNotIn("5.000,00", cuerpo)


class DestinatariosYErrores(BaseReporteDiario):
    def test_sin_destinatarios_no_manda_nada(self):
        with override_settings(REPORTE_DIARIO_DESTINATARIOS=[]):
            call_command("reporte_diario", fecha=self.hoy.isoformat(), verbosity=0)
        self.assertEqual(len(mail.outbox), 0)

    def test_usa_destinatarios_del_entorno_si_no_se_pasan_por_argumento(self):
        with override_settings(REPORTE_DIARIO_DESTINATARIOS=["dueno@allpetcr.com"]):
            call_command("reporte_diario", fecha=self.hoy.isoformat(), verbosity=0)
        self.assertEqual(mail.outbox[0].to, ["dueno@allpetcr.com"])

    def test_destinatarios_por_argumento_van_a_ambos(self):
        self.correr(destinatarios="a@x.com,b@x.com")
        self.assertEqual(mail.outbox[0].to, ["a@x.com", "b@x.com"])
