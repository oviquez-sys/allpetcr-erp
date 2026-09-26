"""Pruebas de las correcciones de la auditoría del 26/09/2026 (Fase 2).

Cada prueba lleva el código del hallazgo que fija (ver AUDITORIA_ERP_FASE2.md).
Si alguna falla, el error que corrigió volvió.
"""
import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse

from caja.models import MovimientoCaja
from caja.services import abrir_caja
from catalogo.models import Impuesto, Producto
from contabilidad.models import LineaAsiento
from contabilidad.services import cuenta
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .devoluciones import registrar_devolucion
from .models import Cliente, FacturaVenta, PagoVenta
from .pagos import por_medio
from .services import anular_factura, registrar_venta


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM", regimen=Empresa.Regimen.TRADICIONAL)
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        self.usuario = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.iva = Impuesto.objects.create(nombre="IVA general", tarifa=Decimal("13"))
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P1", nombre="Arnés", precio_venta=Decimal("5300"),
            impuesto=self.iva, cabys="2921001000000",
        )
        registrar_movimiento(producto=self.producto, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("10"), costo_unitario=Decimal("1500"), referencia="INI")
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("10000"))

    def vender(self, medio="EFE", cantidad=1, **extra):
        return registrar_venta(sesion_caja=self.sesion, medio_pago=medio, usuario=self.usuario,
                               lineas=[{"producto_id": self.producto.pk, "cantidad": cantidad}], **extra)

    def efectivo_en_caja(self):
        return MovimientoCaja.objects.filter(sesion=self.sesion).aggregate(t=Sum("monto"))["t"]


class AnularConDevoluciones(Base):
    """VEN-01: anular una venta con devolución parcial duplicaba plata e inventario."""

    def test_no_se_anula_una_venta_con_devolucion(self):
        f = self.vender(cantidad=2)
        registrar_devolucion(factura=f, lineas=[{"linea_venta_id": f.lineas.get().pk, "cantidad": 1}],
                             motivo="no le quedó", usuario=self.usuario)
        with self.assertRaises(ValidationError):
            anular_factura(factura=f, motivo="error", usuario=self.usuario)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("9"))       # 10 − 2 + 1, sin unidad fantasma
        self.assertEqual(self.efectivo_en_caja(), Decimal("10000") + Decimal("10600") - Decimal("5300"))

    def test_actividad_no_ofrece_anular_si_hay_devolucion(self):
        f = self.vender(cantidad=2)
        registrar_devolucion(factura=f, lineas=[{"linea_venta_id": f.lineas.get().pk, "cantidad": 1}],
                             motivo="x", usuario=self.usuario)
        self.client.force_login(self.usuario)
        html = self.client.get(reverse("core:actividad")).content.decode()
        self.assertNotIn(f"anular('venta', {f.id}", html)


class DobleCobro(Base):
    """VEN-02: dos envíos del mismo cobro creaban dos ventas."""

    def cobrar(self, clave):
        cuerpo = {"medio_pago": "EFE", "clave": clave,
                  "lineas": [{"producto_id": self.producto.pk, "cantidad": 1}]}
        return self.client.post(reverse("ventas:vender"), json.dumps(cuerpo), content_type="application/json")

    @override_settings(TIQUETE_AUTOMATICO=False)
    def test_la_misma_clave_no_crea_otra_venta(self):
        self.client.force_login(self.usuario)
        r1, r2 = self.cobrar("abc-123"), self.cobrar("abc-123")
        self.assertEqual(r1.json()["numero"], r2.json()["numero"])
        self.assertTrue(r2.json()["repetida"])
        self.assertEqual(FacturaVenta.objects.count(), 1)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("9"))

    @override_settings(TIQUETE_AUTOMATICO=True)
    def test_la_venta_repetida_no_vuelve_a_imprimir(self):
        self.client.force_login(self.usuario)
        with mock.patch("impresion.servicio.imprimir_tiquete", return_value=None) as imprimir:
            self.cobrar("xyz")
            self.cobrar("xyz")
        self.assertEqual(imprimir.call_count, 1)

    @override_settings(TIQUETE_AUTOMATICO=False)
    def test_claves_distintas_son_ventas_distintas(self):
        self.client.force_login(self.usuario)
        self.cobrar("uno")
        self.cobrar("dos")
        self.assertEqual(FacturaVenta.objects.count(), 2)

    def test_el_pos_bloquea_cobros_simultaneos(self):
        """F1/F2/F3 saltaban el bloqueo de los botones: ahora hay un candado."""
        self.client.force_login(self.usuario)
        html = self.client.get(reverse("ventas:pos")).content.decode()
        self.assertIn("if (cobrando) return;", html)
        self.assertIn("clave = nuevaClave()", html)


class Vuelto(Base):
    """VEN-03: efectivo recibido y vuelto."""

    def test_guarda_recibido_y_vuelto(self):
        f = self.vender(monto_recibido="10000")
        self.assertEqual(f.monto_recibido, Decimal("10000"))
        self.assertEqual(f.vuelto, Decimal("4700"))
        # La caja sube por lo cobrado, no por lo recibido.
        self.assertEqual(self.efectivo_en_caja(), Decimal("15300"))

    def test_no_acepta_menos_de_lo_que_cuesta(self):
        with self.assertRaises(ValidationError):
            self.vender(monto_recibido="5000")
        self.assertEqual(FacturaVenta.objects.count(), 0)


class PagoMixto(Base):
    """VEN-04: parte en efectivo y parte por SINPE/tarjeta."""

    def mixta(self, efectivo, sinpe, cantidad=2):
        return self.vender(medio="MIX", cantidad=cantidad,
                           pagos=[{"medio": "EFE", "monto": efectivo}, {"medio": "SIN", "monto": sinpe}])

    def test_solo_el_efectivo_entra_a_la_caja(self):
        f = self.mixta("4000", "6600")
        self.assertEqual(PagoVenta.objects.filter(factura=f).count(), 2)
        self.assertEqual(self.efectivo_en_caja(), Decimal("14000"))

    def test_tiene_que_sumar_exacto(self):
        with self.assertRaises(ValidationError):
            self.mixta("4000", "6000")
        self.assertEqual(FacturaVenta.objects.count(), 0)

    def test_no_se_puede_fiar_una_parte(self):
        with self.assertRaises(ValidationError):
            self.vender(medio="MIX", cantidad=2, pagos=[{"medio": "EFE", "monto": "4000"},
                                                        {"medio": "CRE", "monto": "6600"}])

    def test_asiento_reparte_caja_y_bancos_y_cuadra(self):
        f = self.mixta("4000", "6600")
        lineas = LineaAsiento.objects.filter(asiento__referencia=f.numero, asiento__origen="VEN")
        self.assertEqual(lineas.get(cuenta=cuenta(self.empresa, "caja")).debe, Decimal("4000"))
        self.assertEqual(lineas.get(cuenta=cuenta(self.empresa, "bancos")).debe, Decimal("6600"))
        self.assertEqual(sum(l.debe for l in lineas), sum(l.haber for l in lineas))

    def test_reportes_reparten_por_medio(self):
        self.mixta("4000", "6600")
        self.vender(medio="TAR")
        medios = por_medio(FacturaVenta.objects.all())
        self.assertEqual(medios["EFE"]["t"], Decimal("4000"))
        self.assertEqual(medios["SIN"]["t"], Decimal("6600"))
        self.assertEqual(medios["TAR"]["t"], Decimal("5300"))
        self.assertNotIn("MIX", medios)

    def test_anular_devuelve_solo_el_efectivo(self):
        f = self.mixta("4000", "6600")
        anular_factura(factura=f, motivo="error", usuario=self.usuario)
        self.assertEqual(self.efectivo_en_caja(), Decimal("10000"))
        debe = LineaAsiento.objects.aggregate(t=Sum("debe"))["t"]
        haber = LineaAsiento.objects.aggregate(t=Sum("haber"))["t"]
        self.assertEqual(debe, haber)

    def test_devolucion_reparte_en_proporcion(self):
        f = self.mixta("5300", "5300")            # mitad y mitad
        registrar_devolucion(factura=f, lineas=[{"linea_venta_id": f.lineas.get().pk, "cantidad": 1}],
                             motivo="cambio", usuario=self.usuario)
        # Sale del cajón la mitad de ₡5.300.
        self.assertEqual(self.efectivo_en_caja(), Decimal("10000") + Decimal("5300") - Decimal("2650"))


class FotoFiscalDeLaLinea(Base):
    """VEN-08 / FE-04: la línea guarda tarifa, subtotal, impuesto y CABYS."""

    def test_guarda_el_desglose_al_vender(self):
        linea = self.vender().lineas.get()
        self.assertEqual(linea.tarifa_iva, Decimal("13"))
        self.assertEqual(linea.subtotal, Decimal("4690.27"))
        self.assertEqual(linea.impuesto, Decimal("609.73"))
        self.assertEqual(linea.cabys, "2921001000000")

    def test_si_cambia_la_tarifa_la_venta_vieja_no_cambia(self):
        linea = self.vender().lineas.get()
        self.iva.tarifa = Decimal("4")
        self.iva.save()
        linea.refresh_from_db()
        self.assertEqual(linea.tarifa_iva, Decimal("13"))


class ProductoPorCodigo(Base):
    """VEN-05: lo que el POS no tiene cargado se busca en el servidor."""

    def buscar(self, q):
        self.client.force_login(self.usuario)
        return self.client.get(reverse("ventas:producto_por_codigo"), {"q": q}).json()

    def test_encuentra_un_producto_nuevo(self):
        nuevo = Producto.objects.create(empresa=self.empresa, sku="N1", nombre="Nuevo", precio_venta=1000)
        registrar_movimiento(producto=nuevo, bodega=self.bodega, tipo="INI", cantidad=Decimal("3"),
                             costo_unitario=Decimal("500"), referencia="INI")
        d = self.buscar(nuevo.codigo_barras)
        self.assertTrue(d["ok"])
        self.assertEqual(d["producto"]["id"], nuevo.id)

    def test_en_cero_dice_que_existe(self):
        Producto.objects.create(empresa=self.empresa, sku="C0", nombre="Sin existencia", precio_venta=1000,
                                codigo_barras="7501234567895")
        d = self.buscar("7501234567895")
        self.assertFalse(d["ok"])
        self.assertTrue(d["existe"])
        self.assertIn("hay 0", d["error"])

    def test_no_existe(self):
        d = self.buscar("999")
        self.assertFalse(d["ok"])
        self.assertFalse(d["existe"])


class ClienteRapidoEHistorial(Base):
    """FE-03 y TIQ-03."""

    def setUp(self):
        super().setUp()
        self.cajero = User.objects.create_user("maria", password="c", is_staff=True)
        self.cajero.groups.add(Group.objects.get(name="Cajero"))

    def test_crea_cliente_sin_credito(self):
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("ventas:cliente_rapido"), json.dumps(
            {"nombre": "Ana", "tipo_identificacion": "FIS", "identificacion": "112340567", "email": "ana@x.com"}),
            content_type="application/json").json()
        self.assertTrue(r["ok"])
        c = Cliente.objects.get(pk=r["cliente"]["id"])
        self.assertEqual((c.limite_credito, c.tipo_identificacion, c.email), (0, "FIS", "ana@x.com"))

    def test_no_duplica_por_cedula(self):
        Cliente.objects.create(empresa=self.empresa, nombre="Ana", identificacion="112340567")
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("ventas:cliente_rapido"), json.dumps(
            {"nombre": "Ana B", "identificacion": "112340567"}), content_type="application/json").json()
        self.assertTrue(r["ya_existia"])
        self.assertEqual(Cliente.objects.count(), 1)

    def test_el_cajero_ve_el_historial_y_busca_por_numero(self):
        f = self.vender()
        self.client.force_login(self.cajero)
        numero = str(int(f.numero.split("-")[1]))
        html = self.client.get(reverse("ventas:historial"), {"q": numero}).content.decode()
        self.assertIn(f.numero, html)
        self.assertIn(reverse("impresion:tiquete", args=[f.pk]), html)   # reimprimir
        self.assertNotIn(reverse("ventas:devolver", args=[f.pk]), html)  # devolver es del gerente


class CorreoDelRecibo(Base):
    """TIQ-06: el recibo desde el POS y sin mentir si el correo no está configurado."""

    def enviar(self, destino="cliente@correo.com"):
        self.client.force_login(self.usuario)
        return self.client.post(reverse("ventas:factura_enviar", args=[self.f.pk]), {"destinatario": destino},
                                HTTP_ACCEPT="application/json")

    def setUp(self):
        super().setUp()
        self.f = self.vender()

    @mock.patch("ventas.views.html_a_pdf", return_value=b"%PDF-1.4 prueba")
    def test_envia_y_contesta_en_json(self, _pdf):
        r = self.enviar()
        self.assertTrue(r.json()["ok"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments[0][0], f"Recibo-{self.f.numero}.pdf")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend", DEBUG=False)
    def test_sin_correo_configurado_no_dice_enviado(self):
        r = self.enviar()
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.json()["ok"])

    def test_correo_invalido(self):
        r = self.enviar("no-es-un-correo")
        self.assertEqual(r.status_code, 400)


class TiqueteEnPantalla(Base):
    def test_muestra_vuelto_y_quien_atendio(self):
        f = self.vender(monto_recibido="10000")
        self.client.force_login(self.usuario)
        html = self.client.get(reverse("ventas:tiquete", args=[f.pk])).content.decode()
        self.assertIn("Vuelto", html)
        self.assertIn("4.700", html)
        self.assertIn("Atendió", html)
