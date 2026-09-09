"""Pruebas de compras: recepción, costo promedio y asiento automático (S6)."""
import json
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from catalogo.models import CambioPrecio, Categoria, Producto
from contabilidad.models import LineaAsiento
from contabilidad.services import cuenta
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .admin import CompraAdmin, LineaCompraInline
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


class PermisosDeAdminTest(BaseCompras):
    """SEC-002 (auditoría 2026-08-10): Compra era el único documento de los
    8 admin de "documento" del proyecto (FacturaVenta, Asiento,
    MovimientoInventario...) sin add/change/delete bloqueados en su
    ModelAdmin. Borrar una Compra RECIBIDA desde /admin/ no revierte
    MovimientoInventario ni Asiento (no tienen FK a Compra, solo una
    referencia de texto) ni el saldo del proveedor — deja el documento
    huérfano y el libro descuadrado. Estas pruebas verifican que el camino
    quedó cerrado."""

    def setUp(self):
        super().setUp()
        self.compra = self.nueva_compra("5", "10000", forma="CRE")
        recibir_compra(compra=self.compra, usuario=self.usuario)
        self.request = RequestFactory().get("/admin/compras/compra/")
        self.request.user = self.usuario

    def test_compra_admin_bloquea_add_change_delete(self):
        admin_compra = CompraAdmin(Compra, admin.site)
        self.assertFalse(admin_compra.has_add_permission(self.request))
        self.assertFalse(admin_compra.has_change_permission(self.request, self.compra))
        self.assertFalse(admin_compra.has_delete_permission(self.request, self.compra))

    def test_linea_compra_inline_no_permite_borrar_ni_agregar(self):
        inline = LineaCompraInline(Compra, admin.site)
        self.assertFalse(inline.can_delete)
        self.assertFalse(inline.has_add_permission(self.request, self.compra))


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


class BonificacionDelProveedor(BaseCompras):
    """Promociones "12+1", "100+20" (01/09/2026).

    El proveedor factura 12 y manda 13. Las dos cifras tienen que ir a
    lugares distintos: la factura y la contabilidad reconocen 12, la bodega
    recibe 13, y el costo real por unidad baja porque el mismo dinero se
    reparte entre más unidades.
    """

    def setUp(self):
        super().setUp()
        # Producto en cero para que la aritmética del costo promedio no
        # arrastre la carga inicial del caso base.
        self.saco = Producto.objects.create(
            empresa=self.empresa, sku="SACO-15", nombre="Alimento perro 15 kg",
            precio_venta=Decimal("25000"),
        )

    def _compra(self, cantidad, bonificada, costo, forma="CON"):
        return crear_compra(
            proveedor=self.proveedor, sucursal=self.sucursal, forma_pago=forma,
            usuario=self.usuario,
            lineas=[{
                "producto": self.saco,
                "cantidad": Decimal(cantidad),
                "cantidad_bonificada": Decimal(bonificada),
                "costo_unitario": Decimal(costo),
            }],
        )

    # ── la factura ────────────────────────────────────────────────────
    def test_el_total_es_solo_lo_facturado(self):
        """13 sacos en bodega, pero el proveedor cobra 12."""
        compra = self._compra("12", "1", "1000")
        self.assertEqual(compra.total, Decimal("12000.00"))

    def test_el_asiento_contable_cuadra_con_la_factura(self):
        compra = self._compra("12", "1", "1000")
        recibir_compra(compra=compra, usuario=self.usuario)
        debe, _ = self.saldo("inventario")
        # ₡12.000, no ₡13.000: el inventario vale lo que se pagó por él.
        self.assertEqual(debe, Decimal("12000.00"))

    # ── la bodega ─────────────────────────────────────────────────────
    def test_entran_todas_las_unidades_que_llegaron(self):
        compra = self._compra("12", "1", "1000")
        recibir_compra(compra=compra, usuario=self.usuario)
        self.saco.refresh_from_db()
        self.assertEqual(self.saco.stock_actual, Decimal("13"))

    def test_el_costo_real_reparte_la_bonificacion(self):
        """₡12.000 entre 13 sacos = ₡923,08, no ₡1.000."""
        compra = self._compra("12", "1", "1000")
        recibir_compra(compra=compra, usuario=self.usuario)
        self.saco.refresh_from_db()
        self.assertEqual(self.saco.costo_promedio, Decimal("923.08"))

    def test_el_costo_real_es_menor_que_el_facturado(self):
        """La prueba que importa para el precio de venta: la promoción tiene
        que llegar al costo, o el descuento se pierde en el camino."""
        compra = self._compra("100", "20", "5000")
        recibir_compra(compra=compra, usuario=self.usuario)
        self.saco.refresh_from_db()
        self.assertLess(self.saco.costo_promedio, Decimal("5000"))
        # ₡500.000 entre 120 sacos
        self.assertEqual(self.saco.costo_promedio, Decimal("4166.67"))
        self.assertEqual(self.saco.stock_actual, Decimal("120"))

    # ── el descuento equivalente ──────────────────────────────────────
    def test_doce_mas_uno_equivale_a_769_por_ciento(self):
        """No es 8,33% (1/12): es 7,69% (1/13). El descuento se mide sobre lo
        que se recibe, no sobre lo que se paga."""
        compra = self._compra("12", "1", "1000")
        linea = compra.lineas.get()
        self.assertEqual(linea.descuento_efectivo_pct, Decimal("7.69"))

    def test_cien_mas_veinte_equivale_a_1667_por_ciento(self):
        compra = self._compra("100", "20", "5000")
        self.assertEqual(compra.lineas.get().descuento_efectivo_pct, Decimal("16.67"))

    def test_sin_bonificacion_el_descuento_es_cero(self):
        compra = self._compra("12", "0", "1000")
        self.assertEqual(compra.lineas.get().descuento_efectivo_pct, Decimal("0"))

    # ── anulación ─────────────────────────────────────────────────────
    def test_anular_saca_tambien_las_bonificadas(self):
        compra = self._compra("12", "1", "1000")
        recibir_compra(compra=compra, usuario=self.usuario)
        anular_compra(compra=compra, motivo="Llegó dañado", usuario=self.usuario)
        self.saco.refresh_from_db()
        self.assertEqual(self.saco.stock_actual, Decimal("0"))

    # ── que nada de lo viejo se rompa ─────────────────────────────────
    def test_una_compra_sin_bonificacion_se_comporta_igual_que_siempre(self):
        compra = self._compra("10", "0", "1000")
        recibir_compra(compra=compra, usuario=self.usuario)
        self.saco.refresh_from_db()
        self.assertEqual(compra.total, Decimal("10000.00"))
        self.assertEqual(self.saco.stock_actual, Decimal("10"))
        self.assertEqual(self.saco.costo_promedio, Decimal("1000.00"))

    def test_bonificacion_negativa_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self._compra("12", "-1", "1000")

    # ── desde la pantalla ─────────────────────────────────────────────
    def test_la_pantalla_registra_la_bonificacion(self):
        self.client.force_login(self.usuario)
        r = self.client.post(
            reverse("compras:registrar"),
            data=json.dumps({
                "proveedor_id": self.proveedor.id,
                "forma_pago": "CON",
                "factura_proveedor": "F-777",
                "lineas": [{
                    "producto_id": self.saco.id, "cantidad": 12,
                    "cantidad_bonificada": 1, "costo_unitario": 1000,
                }],
            }),
            content_type="application/json",
        )
        d = r.json()
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["total"], 12000.0)  # la factura, no la bodega
        self.saco.refresh_from_db()
        self.assertEqual(self.saco.stock_actual, Decimal("13"))
        self.assertEqual(self.saco.costo_promedio, Decimal("923.08"))


class RecibirMercaderiaMejoras(BaseCompras):
    """Cambios pedidos por Oscar el 02/09/2026 en 'Recibir mercadería':
    crear categorías desde la pantalla y fijar el precio por margen."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    # ── 1. categorías ──────────────────────────────────────────────────
    def test_la_pantalla_manda_tambien_las_categorias_vacias(self):
        """El caso que motivó el cambio: 'Alimento' existe pero no tiene ni un
        producto, y aun así hay que poder elegirla. Antes la lista se armaba de
        los productos, así que una categoría vacía era inalcanzable."""
        Categoria.objects.create(nombre="Alimento", orden=10)
        r = self.client.get(reverse("compras:nueva"))
        nombres = [c["nombre"] for c in r.context["categorias"]]
        self.assertIn("Alimento", nombres)

    def test_las_categorias_vienen_en_el_orden_del_erp(self):
        Categoria.objects.create(nombre="Alimento", orden=10)
        Categoria.objects.create(nombre="Juguetes", orden=30)
        r = self.client.get(reverse("compras:nueva"))
        nombres = [c["nombre"] for c in r.context["categorias"]]
        self.assertLess(nombres.index("Alimento"), nombres.index("Juguetes"))

    def test_producto_nuevo_crea_la_categoria_colgando_de_su_madre(self):
        madre = Categoria.objects.create(nombre="Alimento", orden=10)
        r = self.client.post(
            reverse("compras:producto_nuevo"),
            data=json.dumps({
                "nombre": "Dog Chow Adulto 15kg", "precio_venta": 18000,
                "categoria": "Alimento seco", "categoria_padre": "Alimento",
            }),
            content_type="application/json",
        )
        self.assertTrue(r.json()["ok"], r.json())
        hija = Categoria.objects.get(nombre="Alimento seco")
        self.assertEqual(hija.padre_id, madre.id)
        self.assertEqual(hija.orden, madre.orden + 1)  # queda pegada a su madre

    def test_categoria_nueva_sin_madre_queda_como_principal(self):
        self.client.post(
            reverse("compras:producto_nuevo"),
            data=json.dumps({"nombre": "Algo", "precio_venta": 1000, "categoria": "Farmacia"}),
            content_type="application/json",
        )
        nueva = Categoria.objects.get(nombre="Farmacia")
        self.assertIsNone(nueva.padre)
        self.assertEqual(nueva.orden, 900)  # al final, para no colarse antes de las de siempre

    # ── 2. precio por margen ───────────────────────────────────────────
    def _recibir(self, **extra):
        linea = {"producto_id": self.producto.id, "cantidad": 10, "costo_unitario": 12000}
        linea.update(extra)
        return self.client.post(
            reverse("compras:registrar"),
            data=json.dumps({"proveedor_id": self.proveedor.id, "forma_pago": "CON", "lineas": [linea]}),
            content_type="application/json",
        )

    def test_sin_ganancia_el_precio_no_se_toca(self):
        """Comportamiento de siempre: recibir mercadería no cambia precios."""
        antes = self.producto.precio_venta
        self.assertTrue(self._recibir().json()["ok"])
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, antes)
        self.assertEqual(CambioPrecio.objects.count(), 0)

    def test_con_precio_calculado_se_aplica_y_queda_firmado(self):
        r = self._recibir(precio_venta=25200)
        self.assertTrue(r.json()["ok"], r.json())
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("25200"))
        cambio = CambioPrecio.objects.get(producto=self.producto)
        self.assertIn("Recepción de mercadería", cambio.motivo)
        self.assertEqual(cambio.usuario, self.usuario)

    def test_el_precio_se_aplica_despues_de_que_entro_el_stock(self):
        """Si la recepción fallara, el precio tampoco debe haber cambiado."""
        self.assertTrue(self._recibir(precio_venta=25200).json()["ok"])
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("20"))   # 10 iniciales + 10
        self.assertEqual(self.producto.precio_venta, Decimal("25200"))

    def test_un_precio_igual_al_actual_no_rompe_la_compra(self):
        """cambiar_precio rechaza un precio idéntico. Eso no puede tumbar una
        recepción que ya entró bien al inventario."""
        actual = self.producto.precio_venta
        r = self._recibir(precio_venta=float(actual))
        self.assertTrue(r.json()["ok"], r.json())
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("20"))
        self.assertEqual(CambioPrecio.objects.count(), 0)

    def test_la_bonificacion_sigue_funcionando_junto_con_el_precio(self):
        r = self._recibir(cantidad_bonificada=2, precio_venta=25200)
        self.assertTrue(r.json()["ok"], r.json())
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("22"))  # 10 + 10 + 2 gratis
        self.assertEqual(self.producto.precio_venta, Decimal("25200"))
