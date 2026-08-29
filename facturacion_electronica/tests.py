import threading
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from caja.services import abrir_caja
from catalogo.models import Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.services import registrar_venta

from .models import (
    EstadoComprobante,
    FacturaElectronica,
    NotaCreditoElectronica,
    ReciboElectronicoPago,
    TiqueteElectronico,
)
from .services import (
    ConfiguracionPendiente,
    crear_factura_electronica,
    crear_nota_credito,
    crear_recibo_pago,
    crear_tiquete_electronico,
    enviar_a_hacienda,
    firmar_xades_epes,
    guardar_xml_firmado,
    registrar_respuesta_hacienda,
)


class BaseFE(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        from django.contrib.auth.models import User
        self.usuario = User.objects.create_user("cajera")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="FE-1", nombre="Producto FE", precio_venta=Decimal("5000"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("10"), costo_unitario=Decimal("1000"), referencia="INI",
        )
        sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))
        self.factura_venta = registrar_venta(
            sesion_caja=sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}],
        )


class CreacionDeComprobantes(BaseFE):
    def test_crear_factura_electronica_nace_pendiente_de_firma(self):
        fe = crear_factura_electronica(self.factura_venta)
        self.assertEqual(fe.estado, EstadoComprobante.PENDIENTE_FIRMA)
        self.assertTrue(fe.numero_interno.startswith("FE-"))
        self.assertEqual(fe.clave, "")  # nadie inventa la clave todavía

    def test_crear_tiquete_electronico(self):
        te = crear_tiquete_electronico(self.factura_venta)
        self.assertEqual(te.estado, EstadoComprobante.PENDIENTE_FIRMA)
        self.assertTrue(te.numero_interno.startswith("TE-"))

    def test_numero_interno_es_texto_no_entero(self):
        fe = crear_factura_electronica(self.factura_venta)
        self.assertIsInstance(fe.numero_interno, str)

    def test_clave_es_texto_max_50(self):
        campo = FacturaElectronica._meta.get_field("clave")
        self.assertEqual(campo.__class__.__name__, "CharField")
        self.assertEqual(campo.max_length, 50)

    def test_nota_credito_exige_exactamente_un_comprobante(self):
        fe = crear_factura_electronica(self.factura_venta)
        with self.assertRaises(ValidationError):
            crear_nota_credito(empresa=self.empresa, motivo="Devolución")  # ninguno
        nc = crear_nota_credito(empresa=self.empresa, motivo="Devolución", factura_electronica=fe)
        self.assertEqual(nc.factura_electronica, fe)

    def test_nota_credito_no_acepta_los_dos_a_la_vez(self):
        fe = crear_factura_electronica(self.factura_venta)
        te = crear_tiquete_electronico(self.factura_venta)
        with self.assertRaises(ValidationError):
            crear_nota_credito(empresa=self.empresa, motivo="x", factura_electronica=fe, tiquete_electronico=te)

    def test_constraint_de_base_rechaza_los_dos_directo_en_el_modelo(self):
        """La validación de services.py es la puerta normal; la constraint
        de base es el respaldo si algo la crea sin pasar por ahí."""
        fe = crear_factura_electronica(self.factura_venta)
        te = crear_tiquete_electronico(self.factura_venta)
        with self.assertRaises(Exception):
            NotaCreditoElectronica.objects.create(
                empresa=self.empresa, numero_interno="NC-TEST", motivo="x",
                factura_electronica=fe, tiquete_electronico=te,
            )

    def test_recibo_pago_referencia_la_factura(self):
        fe = crear_factura_electronica(self.factura_venta)
        rep = crear_recibo_pago(factura_electronica=fe, monto=Decimal("5000"))
        self.assertEqual(rep.factura_electronica, fe)
        self.assertTrue(rep.numero_interno.startswith("REP-"))


class FirmaXAdES(BaseFE):
    def test_sin_configurar_avisa_con_claridad(self):
        fe = crear_factura_electronica(self.factura_venta)
        with self.assertRaises(ConfiguracionPendiente):
            firmar_xades_epes(fe)

    @override_settings()
    def test_con_p12_configurado_igual_avisa_falta_el_generador_de_xml(self):
        import os
        os.environ["HACIENDA_P12_PATH"] = "/no/existe/pero/esta/definida.p12"
        os.environ["HACIENDA_P12_PASSWORD"] = "clave-de-prueba"
        try:
            fe = crear_factura_electronica(self.factura_venta)
            with self.assertRaises(ConfiguracionPendiente):
                firmar_xades_epes(fe)
        finally:
            del os.environ["HACIENDA_P12_PATH"]
            del os.environ["HACIENDA_P12_PASSWORD"]


class EnvioAsincrono(BaseFE):
    def test_no_se_puede_enviar_sin_firmar(self):
        fe = crear_factura_electronica(self.factura_venta)
        with self.assertRaises(ValidationError):
            enviar_a_hacienda(fe)

    def test_enviado_no_es_valido_todavia(self):
        fe = crear_factura_electronica(self.factura_venta)
        guardar_xml_firmado(fe, b"<xml>falso, solo para probar el flujo</xml>")
        fe.refresh_from_db()
        self.assertEqual(fe.estado, EstadoComprobante.FIRMADO)
        fe = enviar_a_hacienda(fe)
        self.assertEqual(fe.estado, EstadoComprobante.ENVIADO)
        self.assertFalse(fe.valido)  # ítem 25: enviado != válido
        self.assertEqual(fe.intentos_envio, 1)

    def test_aceptado_por_hacienda_es_valido(self):
        fe = crear_factura_electronica(self.factura_venta)
        guardar_xml_firmado(fe, b"<xml/>")
        fe = enviar_a_hacienda(fe)
        fe = registrar_respuesta_hacienda(fe, aceptado=True, mensaje="Comprobante aceptado")
        self.assertTrue(fe.valido)
        self.assertIsNotNone(fe.fecha_aceptacion)

    def test_rechazado_no_es_valido(self):
        fe = crear_factura_electronica(self.factura_venta)
        guardar_xml_firmado(fe, b"<xml/>")
        fe = enviar_a_hacienda(fe)
        fe = registrar_respuesta_hacienda(fe, aceptado=False, mensaje="XML mal formado")
        self.assertFalse(fe.valido)
        self.assertEqual(fe.estado, EstadoComprobante.RECHAZADO)

    def test_no_se_registra_respuesta_sin_haber_enviado(self):
        fe = crear_factura_electronica(self.factura_venta)
        with self.assertRaises(ValidationError):
            registrar_respuesta_hacienda(fe, aceptado=True)

    def test_reintentos_se_agotan(self):
        fe = crear_factura_electronica(self.factura_venta)
        guardar_xml_firmado(fe, b"<xml/>")
        for _ in range(fe.MAXIMO_REINTENTOS):
            fe = enviar_a_hacienda(fe)
        with self.assertRaises(ValidationError):
            enviar_a_hacienda(fe)
        fe.refresh_from_db()
        self.assertEqual(fe.estado, EstadoComprobante.ERROR_ENVIO)


class ConservacionDeXML(BaseFE):
    def test_guardar_xml_firmado_deja_rastro_y_cambia_estado(self):
        fe = crear_factura_electronica(self.factura_venta)
        ruta = guardar_xml_firmado(fe, b"<xml>contenido</xml>")
        fe.refresh_from_db()
        self.assertEqual(fe.ruta_xml_firmado, ruta)
        self.assertEqual(fe.estado, EstadoComprobante.FIRMADO)
        self.assertIsNotNone(fe.firmado_en)

        from django.core.files.storage import default_storage
        with default_storage.open(ruta, "rb") as f:
            self.assertEqual(f.read(), b"<xml>contenido</xml>")


class ConcurrenciaConsecutivo(TransactionTestCase):
    """Ítem 23, literal: 'dos ventas simultáneas no pueden sacar el mismo
    número. Probalo.' — para el consecutivo interno de facturación
    electrónica, con hilos reales sobre PostgreSQL."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        from django.contrib.auth.models import User
        self.usuario = User.objects.create_user("cajera2")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="FE-CONC", nombre="Producto concurrencia", precio_venta=Decimal("1000"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("50"), costo_unitario=Decimal("500"), referencia="INI",
        )

    def test_veinte_facturas_electronicas_simultaneas_no_repiten_numero(self):
        # No hace falta pasar por una venta real de POS para probar la
        # unicidad del consecutivo: se llama directo al numerador, que es
        # justo lo que el ítem 23 pide verificar. Se evita abrir 20 cajas
        # simultáneas (un solo cajero no puede tener 20 sesiones abiertas).
        from ventas.models import Consecutivo

        N = 20
        numeros = []
        lock = threading.Lock()
        barrera = threading.Barrier(N)

        def tomar(i):
            connection.close()
            try:
                barrera.wait(timeout=5)
                numero = Consecutivo.tomar(self.empresa, "FE")
                with lock:
                    numeros.append(numero)
            finally:
                connection.close()

        hilos = [threading.Thread(target=tomar, args=(i,)) for i in range(N)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=15)

        self.assertEqual(len(numeros), N)
        self.assertEqual(len(set(numeros)), N)  # ninguno se repite
