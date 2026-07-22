"""Pruebas de compras: recepción, costo promedio y asiento automático (S6)."""
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Producto
from contabilidad.models import LineaAsiento
from contabilidad.services import cuenta
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .models import Compra, Proveedor
from .services import anular_compra, crear_compra, recibir_compra


class BaseCompras(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.proveedor = Proveedor.objects.create(empresa=self.empresa, nombre="Distribuidora Mascotas SA")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Alimento", precio_venta=Decimal("18000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("10"), costo_unitario=Decimal("10000"), referencia="INI",
        )
        self.producto.refresh_from_db()

    def nueva_compra(self, cantidad, costo, forma="CON"):
        return crear_compra(
            proveedor=self.proveedor, sucursal=self.sucursal, forma_pago=forma, usuario=self.usuario,
            lineas=[{"producto": self.producto, "cantidad": Decimal(cantidad), "costo_unitario": Decimal(costo)}],
        )

    def saldo(self, logico):
        c = cuenta(self.empresa, logico)
        debe = sum((l.debe for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        haber = sum((l.haber for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        return debe, haber


class RecepcionDeCompra(BaseCompras):
    def test_borrador_no_toca_inventario(self):
        self.nueva_compra("10", "12000")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # sin cambios

    def test_recepcion_suma_stock(self):
        compra = self.nueva_compra("10", "12000")
        recibir_compra(compra=compra, usuario=self.usuario)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("20"))

    def test_recepcion_recalcula_costo_promedio(self):
        # 10 uds a 10000 + 10 uds a 14000 -> promedio 12000
        compra = self.nueva_compra("10", "14000")
        recibir_compra(compra=compra, usuario=self.usuario)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.costo_promedio, Decimal("12000.00"))

    def test_recepcion_contado_genera_asiento_inventario_bancos(self):
        compra = self.nueva_compra("5", "10000")  # total 50000
        recibir_compra(compra=compra, usuario=self.usuario)
        inv_d, _ = self.saldo("inventario")
        _, bancos_h = self.saldo("bancos")
        self.assertEqual(inv_d, Decimal("50000"))
        self.assertEqual(bancos_h, Decimal("50000"))

    def test_recepcion_credito_sube_saldo_proveedor(self):
        compra = self.nueva_compra("5", "10000", forma="CRE")  # 50000
        recibir_compra(compra=compra, usuario=self.usuario)
        self.proveedor.refresh_from_db()
        self.assertEqual(self.proveedor.saldo, Decimal("50000"))

    def test_no_se_recibe_dos_veces(self):
        compra = self.nueva_compra("5", "10000")
        recibir_compra(compra=compra, usuario=self.usuario)
        with self.assertRaises(ValidationError):
            recibir_compra(compra=compra, usuario=self.usuario)

    def test_asiento_de_compra_cuadra(self):
        compra = self.nueva_compra("7", "9000")
        recibir_compra(compra=compra, usuario=self.usuario)
        from contabilidad.models import Asiento
        a = Asiento.objects.filter(referencia=compra.numero).first()
        self.assertIsNotNone(a)
        self.assertTrue(a.cuadra)


class AnulacionDeCompra(BaseCompras):
    """Sprint D: reversar una compra recibida por error."""

    def _saldo(self, logico):
        from contabilidad.models import LineaAsiento
        from contabilidad.services import cuenta
        c = cuenta(self.empresa, logico)
        debe = sum((l.debe for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        haber = sum((l.haber for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        return debe, haber

    def test_anular_devuelve_el_stock(self):
        compra = self.nueva_compra("3", "12000")   # entran 3, stock pasa 10 -> 13
        recibir_compra(compra=compra, usuario=self.usuario)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("13"))
        anular_compra(compra=compra, motivo="registrada por error", usuario=self.usuario)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))   # vuelve a lo anterior

    def test_anular_marca_estado_y_quien(self):
        compra = self.nueva_compra("2", "10000")
        recibir_compra(compra=compra, usuario=self.usuario)
        anular_compra(compra=compra, motivo="prueba", usuario=self.usuario)
        compra.refresh_from_db()
        self.assertEqual(compra.estado, Compra.Estado.ANULADA)
        self.assertEqual(compra.anulada_por, self.usuario)
        self.assertEqual(compra.motivo_anulacion, "prueba")
        self.assertIsNotNone(compra.anulada_en)

    def test_anular_credito_baja_saldo_proveedor(self):
        compra = self.nueva_compra("5", "10000", forma="CRE")   # saldo prov +50000
        recibir_compra(compra=compra, usuario=self.usuario)
        self.proveedor.refresh_from_db()
        self.assertEqual(self.proveedor.saldo, Decimal("50000"))
        anular_compra(compra=compra, motivo="prueba", usuario=self.usuario)
        self.proveedor.refresh_from_db()
        self.assertEqual(self.proveedor.saldo, Decimal("0"))

    def test_anular_genera_asiento_inverso_que_cuadra(self):
        compra = self.nueva_compra("4", "9000")   # total 36000
        recibir_compra(compra=compra, usuario=self.usuario)
        anular_compra(compra=compra, motivo="prueba", usuario=self.usuario)
        from contabilidad.models import Asiento
        anu = Asiento.objects.filter(referencia=compra.numero, origen="ANU").first()
        self.assertIsNotNone(anu)
        self.assertTrue(anu.cuadra)
        # Inventario: entró 36000 (compra) y salió 36000 (anulación) -> neto 0
        inv_d, inv_h = self._saldo("inventario")
        self.assertEqual(inv_d, inv_h)

    def test_no_se_anula_si_ya_se_vendio(self):
        # Recibo 2, pero solo hay stock para devolver si no se vendió.
        compra = self.nueva_compra("2", "10000")
        recibir_compra(compra=compra, usuario=self.usuario)   # stock 12
        # "Vendo" (saco) 11 -> queda 1, no alcanza para devolver 2
        registrar_movimiento(producto=self.producto, bodega=self.bodega, tipo="VEN",
                             cantidad=Decimal("-11"), referencia="venta")
        with self.assertRaises(ValidationError):
            anular_compra(compra=compra, motivo="prueba", usuario=self.usuario)

    def test_no_se_anula_dos_veces(self):
        compra = self.nueva_compra("2", "10000")
        recibir_compra(compra=compra, usuario=self.usuario)
        anular_compra(compra=compra, motivo="prueba", usuario=self.usuario)
        with self.assertRaises(ValidationError):
            anular_compra(compra=compra, motivo="otra vez", usuario=self.usuario)

    def test_anular_exige_motivo(self):
        compra = self.nueva_compra("2", "10000")
        recibir_compra(compra=compra, usuario=self.usuario)
        with self.assertRaises(ValidationError):
            anular_compra(compra=compra, motivo="   ", usuario=self.usuario)


class MonitorRTS(BaseCompras):
    def test_dashboard_cuenta_compras_del_anio(self):
        from core.dashboard import indicadores
        compra = self.nueva_compra("5", "10000")
        recibir_compra(compra=compra, usuario=self.usuario)
        datos = indicadores(self.empresa)
        self.assertEqual(datos["compras_anio"], Decimal("50000"))
        self.assertGreater(datos["limite_rts"], 0)
        self.assertFalse(datos["alerta_rts"])  # 50000 está lejísimos del límite


class PantallaRecibirMercaderia(BaseCompras):
    """Pruebas de la pantalla 'Recibir mercadería' (S8): un solo paso crea
    y recibe la compra (sube stock, recalcula costo, genera asiento)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_pantalla_carga_con_productos_y_proveedores(self):
        r = self.client.get(reverse("compras:nueva"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.producto.nombre)
        self.assertContains(r, self.proveedor.nombre)

    def test_registrar_con_proveedor_existente_sube_stock_y_costo(self):
        r = self.client.post(
            reverse("compras:registrar"),
            data=json.dumps({
                "proveedor_id": self.proveedor.id,
                "forma_pago": "CON",
                "factura_proveedor": "F-001",
                "lineas": [{"producto_id": self.producto.id, "cantidad": 10, "costo_unitario": 14000}],
            }),
            content_type="application/json",
        )
        d = r.json()
        self.assertTrue(d["ok"], d)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("20"))
        self.assertEqual(self.producto.costo_promedio, Decimal("12000.00"))
        compra = Compra.objects.get(numero=d["numero"])
        self.assertEqual(compra.estado, Compra.Estado.RECIBIDA)  # ya recibida, no queda en borrador

    def test_registrar_con_proveedor_nuevo_lo_crea(self):
        r = self.client.post(
            reverse("compras:registrar"),
            data=json.dumps({
                "proveedor_nuevo": "Proveedor Nuevo SA",
                "forma_pago": "CRE",
                "lineas": [{"producto_id": self.producto.id, "cantidad": 3, "costo_unitario": 9000}],
            }),
            content_type="application/json",
        )
        d = r.json()
        self.assertTrue(d["ok"], d)
        proveedor = Proveedor.objects.get(nombre="Proveedor Nuevo SA", empresa=self.empresa)
        self.assertEqual(proveedor.saldo, Decimal("27000"))

    def test_registrar_sin_proveedor_da_error_claro(self):
        r = self.client.post(
            reverse("compras:registrar"),
            data=json.dumps({
                "forma_pago": "CON",
                "lineas": [{"producto_id": self.producto.id, "cantidad": 1, "costo_unitario": 1000}],
            }),
            content_type="application/json",
        )
        d = r.json()
        self.assertFalse(d["ok"])
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # nada cambió

    def test_registrar_sin_lineas_da_error_claro(self):
        r = self.client.post(
            reverse("compras:registrar"),
            data=json.dumps({"proveedor_id": self.proveedor.id, "forma_pago": "CON", "lineas": []}),
            content_type="application/json",
        )
        d = r.json()
        self.assertFalse(d["ok"])


class AltaRapidaDeProducto(BaseCompras):
    """Producto que nunca se había comprado: se crea al vuelo desde la
    pantalla de compras, sin pasar por el admin (S8)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_crea_producto_con_categoria_nueva(self):
        r = self.client.post(
            reverse("compras:producto_nuevo"),
            data=json.dumps({
                "nombre": "Correa retráctil 5m",
                "precio_venta": 12000,
                "categoria": "Collares, correas y arneses",
                "presentacion": "Talla M",
            }),
            content_type="application/json",
        )
        d = r.json()
        self.assertTrue(d["ok"], d)
        producto = Producto.objects.get(pk=d["producto"]["id"])
        self.assertEqual(producto.nombre, "Correa retráctil 5m")
        self.assertEqual(producto.precio_venta, Decimal("12000"))
        self.assertEqual(producto.categoria.nombre, "Collares, correas y arneses")
        self.assertEqual(producto.stock_actual, Decimal("0"))
        self.assertTrue(producto.codigo_barras)  # queda listo para imprimir etiqueta

    def test_sku_autogenerado_es_unico_entre_dos_altas(self):
        for _ in range(2):
            r = self.client.post(
                reverse("compras:producto_nuevo"),
                data=json.dumps({"nombre": "Juguete cualquiera", "precio_venta": 1000}),
                content_type="application/json",
            )
            self.assertTrue(r.json()["ok"], r.json())
        skus = set(Producto.objects.filter(nombre="Juguete cualquiera").values_list("sku", flat=True))
        self.assertEqual(len(skus), 2)

    def test_sin_nombre_da_error_claro(self):
        r = self.client.post(
            reverse("compras:producto_nuevo"),
            data=json.dumps({"nombre": "", "precio_venta": 1000}),
            content_type="application/json",
        )
        self.assertFalse(r.json()["ok"])

    def test_sin_precio_da_error_claro(self):
        r = self.client.post(
            reverse("compras:producto_nuevo"),
            data=json.dumps({"nombre": "Algo", "precio_venta": 0}),
            content_type="application/json",
        )
        self.assertFalse(r.json()["ok"])

    def test_producto_nuevo_se_puede_recibir_en_la_misma_compra(self):
        alta = self.client.post(
            reverse("compras:producto_nuevo"),
            data=json.dumps({"nombre": "Cama para gato", "precio_venta": 20000}),
            content_type="application/json",
        ).json()
        producto_id = alta["producto"]["id"]
        r = self.client.post(
            reverse("compras:registrar"),
            data=json.dumps({
                "proveedor_id": self.proveedor.id,
                "forma_pago": "CON",
                "lineas": [{"producto_id": producto_id, "cantidad": 4, "costo_unitario": 8000}],
            }),
            content_type="application/json",
        )
        d = r.json()
        self.assertTrue(d["ok"], d)
        producto = Producto.objects.get(pk=producto_id)
        self.assertEqual(producto.stock_actual, Decimal("4"))
        self.assertEqual(producto.costo_promedio, Decimal("8000.00"))

    def test_producto_nuevo_con_foto_en_base64(self):
        # Imagen PNG mínima (1x1 pixel) en base64
        foto_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
        r = self.client.post(
            reverse("compras:producto_nuevo"),
            data=json.dumps({
                "nombre": "Pelota para perro",
                "precio_venta": 5000,
                "foto_base64": foto_png,
            }),
            content_type="application/json",
        )
        d = r.json()
        self.assertTrue(d["ok"], d)
        producto = Producto.objects.get(pk=d["producto"]["id"])
        self.assertTrue(producto.imagen)
        self.assertTrue(producto.imagen.startswith("productos/"))
