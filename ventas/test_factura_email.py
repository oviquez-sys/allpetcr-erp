from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, Client

from core.models import Empresa, Sucursal
from catalogo.models import Producto
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from caja.services import abrir_caja
from ventas.models import Cliente
from ventas.services import registrar_venta


class FacturaEnviarTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Correo", identificacion="3-101-999999")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.user = User.objects.create_user("cajero_correo", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(empresa=self.empresa, sku="E-1", nombre="Croquetas 5kg",
                                                  precio_venta=Decimal("15000"))
        registrar_movimiento(producto=self.producto, bodega=self.bodega, tipo="INI", cantidad=Decimal("10"),
                              costo_unitario=Decimal("8000"), referencia="INI")
        self.producto.refresh_from_db()
        self.cliente = Cliente.objects.create(empresa=self.empresa, nombre="Cliente Correo",
                                               email="cliente@ejemplo.com", limite_credito=Decimal("0"))
        sesion = abrir_caja(sucursal=self.sucursal, usuario=self.user, monto_apertura=Decimal("10000"))
        self.factura = registrar_venta(sesion_caja=sesion, medio_pago="EFE", usuario=self.user, cliente=self.cliente,
                                        lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])
        self.client_django = Client()
        self.client_django.force_login(self.user)

    def test_envio_exitoso(self):
        resp = self.client_django.post(f"/pos/factura/{self.factura.pk}/enviar/",
                                        {"destinatario": "cliente@ejemplo.com"})
        print("STATUS:", resp.status_code)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        enviado = mail.outbox[0]
        print("Para:", enviado.to, "Asunto:", enviado.subject)
        self.assertEqual(enviado.to, ["cliente@ejemplo.com"])
        self.assertIn(self.factura.numero, enviado.subject)
        self.assertIn(self.factura.numero, enviado.body)
        self.assertIn("3-101-999999", enviado.body)  # cédula en el cuerpo
        self.assertEqual(enviado.content_subtype, "html")
        self.assertContains(resp, "Factura enviada a cliente@ejemplo.com")

    def test_sin_destinatario_no_manda_nada(self):
        resp = self.client_django.post(f"/pos/factura/{self.factura.pk}/enviar/", {"destinatario": ""})
        print("STATUS sin destinatario:", resp.status_code)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(resp, "Falta el correo")

    @mock.patch("ventas.views.EmailMessage.send", side_effect=OSError("Servidor no responde"))
    def test_falla_de_envio_no_truena(self, _mock_send):
        resp = self.client_django.post(f"/pos/factura/{self.factura.pk}/enviar/",
                                        {"destinatario": "cliente@ejemplo.com"})
        print("STATUS con fallo SMTP:", resp.status_code)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No se pudo enviar")
        self.assertEqual(len(mail.outbox), 0)

    def test_email_no_incluye_boton_imprimir_ni_form(self):
        resp = self.client_django.post(f"/pos/factura/{self.factura.pk}/enviar/",
                                        {"destinatario": "cliente@ejemplo.com"})
        self.assertEqual(len(mail.outbox), 1)
        cuerpo = mail.outbox[0].body
        print("Contiene boton Imprimir:", "Imprimir" in cuerpo)
        print("Contiene form Enviar por correo:", "Enviar por correo" in cuerpo)
        self.assertNotIn("Imprimir", cuerpo)
        self.assertNotIn("Enviar por correo", cuerpo)

    def test_pagina_normal_prellena_email_del_cliente(self):
        resp = self.client_django.get(f"/pos/factura/{self.factura.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="cliente@ejemplo.com"')
