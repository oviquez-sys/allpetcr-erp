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

    @mock.patch("ventas.views.html_a_pdf", return_value=b"%PDF-1.4 recibo de prueba")
    def test_envio_exitoso(self, _pdf):
        """El recibo viaja como PDF adjunto y el cuerpo es texto (02/09/2026).

        Antes el cuerpo era el HTML del recibo; Outlook lo dibuja con el motor
        de Word y las columnas se montaban unas sobre otras. La prueba se
        quedó pidiendo el comportamiento viejo y falló hasta el 05/09/2026.

        El PDF se sustituye por un doble a propósito: si dependiera de que
        Chromium esté instalado, la prueba pasaría o fallaría según la máquina
        y dejaría de decir nada sobre el código.
        """
        resp = self.client_django.post(f"/pos/factura/{self.factura.pk}/enviar/",
                                        {"destinatario": "cliente@ejemplo.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        enviado = mail.outbox[0]
        self.assertEqual(enviado.to, ["cliente@ejemplo.com"])
        self.assertIn(self.factura.numero, enviado.subject)
        self.assertIn(self.factura.numero, enviado.body)
        # La cédula jurídica va en el cuerpo: es lo que identifica al emisor
        # ante el cliente y ante Hacienda.
        self.assertIn("3-101-999999", enviado.body)
        self.assertEqual(enviado.content_subtype, "plain")
        adjuntos = [nombre for nombre, _, _ in enviado.attachments]
        self.assertEqual(adjuntos, [f"Recibo-{self.factura.numero}.pdf"])
        self.assertContains(resp, "Factura enviada a cliente@ejemplo.com")

    def test_sin_destinatario_no_manda_nada(self):
        """400: falta un dato que debía mandar el cliente.

        Antes respondía 200 (auditoría 2026-07-28, BE-07). El mensaje en
        pantalla no cambió; lo que cambió es que ahora la respuesta dice la
        verdad y un monitoreo puede detectarlo.
        """
        resp = self.client_django.post(f"/pos/factura/{self.factura.pk}/enviar/", {"destinatario": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(resp, "Falta el correo", status_code=400)

    @mock.patch("ventas.views.EmailMessage.send", side_effect=OSError("Servidor no responde"))
    def test_falla_de_envio_no_truena_pero_lo_reporta(self, _mock_send):
        """502: el servicio de correo falló, no el usuario ni la aplicación.

        Antes devolvía 200 (auditoría 2026-07-28, BE-07), así que las facturas
        podían dejar de salir durante días sin que nada lo detectara. La
        pantalla sigue mostrando el aviso amable: lo que cambia es el estado.
        """
        resp = self.client_django.post(f"/pos/factura/{self.factura.pk}/enviar/",
                                        {"destinatario": "cliente@ejemplo.com"})
        self.assertEqual(resp.status_code, 502)
        self.assertContains(resp, "No se pudo enviar", status_code=502)
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
