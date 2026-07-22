"""Pruebas de códigos de barras y etiquetas (S7)."""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa

from .models import CambioPrecio, Categoria, Producto
from .services import cambiar_precio


class AsignarCodigosBarras(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cat = Categoria.objects.create(nombre="Accesorios")

    def _producto(self, sku, barras=""):
        return Producto.objects.create(
            empresa=self.empresa, sku=sku, nombre=f"Producto {sku}",
            categoria=self.cat, codigo_barras=barras, precio_venta=Decimal("1000"),
        )

    def test_rellena_solo_los_vacios(self):
        con = self._producto("100", barras="7850000000017")
        sin = self._producto("200")
        call_command("asignar_codigos_barras", stdout=StringIO())
        con.refresh_from_db(); sin.refresh_from_db()
        self.assertEqual(con.codigo_barras, "7850000000017")  # no se toca
        self.assertEqual(sin.codigo_barras, "200")            # usa el SKU

    def test_codigos_resultantes_son_unicos(self):
        # Colisión: un producto ya usa "500" como código; otro producto vacío
        # tiene SKU "500". El comando debe desambiguar sin repetir.
        self._producto("400", barras="500")
        self._producto("500")  # SKU coincide con el código de arriba
        call_command("asignar_codigos_barras", stdout=StringIO())
        codigos = list(Producto.objects.exclude(codigo_barras="").values_list("codigo_barras", flat=True))
        self.assertEqual(len(codigos), len(set(codigos)))  # todos únicos
        self.assertEqual(len(codigos), 2)


class PaginaEtiquetas(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cat = Categoria.objects.create(nombre="Accesorios")
        self.staff = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        Producto.objects.create(
            empresa=self.empresa, sku="75564", nombre="Mochila higiénica",
            categoria=self.cat, codigo_barras="75564", precio_venta=Decimal("700"),
        )

    def test_requiere_login(self):
        r = self.client.get(reverse("inventario:etiquetas"))
        self.assertEqual(r.status_code, 302)

    def test_genera_barra_svg(self):
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Mochila higiénica")
        self.assertContains(r, "<svg")  # el código de barras se dibujó
        self.assertContains(r, "₡700")

    def test_copias_multiplica_etiquetas(self):
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"), {"copias": "3"})
        self.assertEqual(r.context["total"], 3)

    def test_omite_productos_sin_codigo(self):
        # Producto legado sin código de barras: se fuerza con .update() para
        # saltarse el save() del modelo (que hoy asigna código automáticamente).
        p = Producto.objects.create(
            empresa=self.empresa, sku="999", nombre="Sin código",
            categoria=self.cat, precio_venta=Decimal("500"),
        )
        Producto.objects.filter(pk=p.pk).update(codigo_barras="")
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"))
        self.assertEqual(r.context["faltan_codigo"], 1)
        self.assertNotContains(r, "Sin código")

    def test_producto_nuevo_recibe_codigo_automatico(self):
        """Todo producto creado sin código recibe uno solo (= su SKU), listo
        para imprimir la etiqueta. Aplica a cualquier vía de creación."""
        p = Producto.objects.create(
            empresa=self.empresa, sku="ABC123", nombre="Collar nuevo",
            categoria=self.cat, precio_venta=Decimal("3000"),
        )
        self.assertEqual(p.codigo_barras, "ABC123")

    def test_no_pisa_codigo_de_proveedor(self):
        """Si el producto ya trae código (EAN del proveedor), no se toca."""
        p = Producto.objects.create(
            empresa=self.empresa, sku="XYZ", nombre="Con EAN",
            categoria=self.cat, codigo_barras="7501234567890", precio_venta=Decimal("100"),
        )
        self.assertEqual(p.codigo_barras, "7501234567890")

    def test_codigo_automatico_desambigua_colision(self):
        """Si el SKU ya está usado como código de otro producto, agrega sufijo."""
        Producto.objects.create(
            empresa=self.empresa, sku="OTRO", nombre="Primero",
            categoria=self.cat, codigo_barras="DUP", precio_venta=Decimal("100"),
        )
        p = Producto.objects.create(
            empresa=self.empresa, sku="DUP", nombre="Segundo",
            categoria=self.cat, precio_venta=Decimal("100"),
        )
        self.assertEqual(p.codigo_barras, "DUP-1")


class HistorialDePrecios(TestCase):
    """Sprint C: cambiar el precio de venta deja siempre rastro (quién, cuándo,
    de cuánto a cuánto)."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.gerente = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Cama",
            precio_venta=Decimal("10000"), costo_promedio=Decimal("6000"),
        )

    def test_cambiar_precio_actualiza_y_registra(self):
        cambiar_precio(producto=self.producto, nuevo_precio="12000", usuario=self.gerente, motivo="subió el costo")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("12000"))
        c = CambioPrecio.objects.get(producto=self.producto)
        self.assertEqual(c.valor_anterior, Decimal("10000"))
        self.assertEqual(c.valor_nuevo, Decimal("12000"))
        self.assertEqual(c.costo_al_momento, Decimal("6000"))  # captura el margen histórico
        self.assertEqual(c.usuario, self.gerente)
        self.assertEqual(c.motivo, "subió el costo")

    def test_variacion_calculada(self):
        cambiar_precio(producto=self.producto, nuevo_precio="9000", usuario=self.gerente)
        c = CambioPrecio.objects.get(producto=self.producto)
        self.assertEqual(c.variacion, Decimal("-1000"))  # bajó

    def test_rechaza_precio_igual(self):
        with self.assertRaises(ValidationError):
            cambiar_precio(producto=self.producto, nuevo_precio="10000", usuario=self.gerente)
        self.assertFalse(CambioPrecio.objects.exists())  # no registra un "cambio" vacío

    def test_rechaza_precio_negativo(self):
        with self.assertRaises(ValidationError):
            cambiar_precio(producto=self.producto, nuevo_precio="-5", usuario=self.gerente)

    def test_varios_cambios_quedan_ordenados(self):
        cambiar_precio(producto=self.producto, nuevo_precio="11000", usuario=self.gerente)
        self.producto.refresh_from_db()
        cambiar_precio(producto=self.producto, nuevo_precio="12500", usuario=self.gerente)
        self.assertEqual(CambioPrecio.objects.filter(producto=self.producto).count(), 2)
        # El más reciente primero (ordering por -fecha, -id)
        ultimo = CambioPrecio.objects.filter(producto=self.producto).first()
        self.assertEqual(ultimo.valor_nuevo, Decimal("12500"))


class PermisosDePrecios(TestCase):
    """Solo gerente puede entrar a precios; un cajero es rebotado."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Cama", precio_venta=Decimal("10000")
        )
        grp = Group.objects.get_or_create(name="Cajero")[0]
        self.cajero = User.objects.create_user("maria", password="x", is_staff=True)
        self.cajero.groups.add(grp)
        self.gerente = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)

    def test_cajero_no_entra_a_precios(self):
        self.client.login(username="maria", password="x")
        r = self.client.get(reverse("catalogo:precios"))
        self.assertEqual(r.status_code, 302)  # redirigido al dashboard

    def test_cajero_no_puede_cambiar_precio_por_post(self):
        self.client.login(username="maria", password="x")
        self.client.post(reverse("catalogo:precio_producto", args=[self.producto.pk]),
                         {"nuevo_precio": "1", "motivo": "hack"})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("10000"))  # no cambió
        self.assertFalse(CambioPrecio.objects.exists())

    def test_gerente_cambia_precio_por_post(self):
        self.client.login(username="oscar", password="x")
        self.client.post(reverse("catalogo:precio_producto", args=[self.producto.pk]),
                         {"nuevo_precio": "13000", "motivo": "ajuste"})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("13000"))
        self.assertTrue(CambioPrecio.objects.filter(producto=self.producto).exists())


class EntradaRapidaProductoAdmin(TestCase):
    """Entrada de mercadería desde la ficha del producto (admin): debe pasar
    por el motor de compras — sube stock, recalcula costo promedio y deja la
    compra recibida. No edita el stock a mano."""

    def setUp(self):
        from core.models import Sucursal
        from inventario.models import Bodega
        from inventario.services import registrar_movimiento
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.gerente = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-100", nombre="Cama", precio_venta=Decimal("10000")
        )
        registrar_movimiento(producto=self.producto, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("5"), costo_unitario=Decimal("6000"), referencia="INI")
        self.producto.refresh_from_db()
        self.client.login(username="oscar", password="x")

    def test_entrada_sube_stock_y_recalcula_costo(self):
        from compras.models import Compra
        url = reverse("admin:catalogo_producto_entrada", args=[self.producto.pk])
        r = self.client.post(url, {
            "cantidad": "5", "costo_unitario": "8000",
            "proveedor_nuevo": "Distribuidora X", "forma_pago": "CON",
        })
        self.assertEqual(r.status_code, 302)  # redirige a la ficha
        self.producto.refresh_from_db()
        # 5 @6000 + 5 @8000 = 10 unidades, costo promedio 7000
        self.assertEqual(self.producto.stock_actual, Decimal("10"))
        self.assertEqual(self.producto.costo_promedio, Decimal("7000"))
        self.assertTrue(Compra.objects.filter(estado="REC").exists())

    def test_entrada_sin_proveedor_falla_sin_tocar_stock(self):
        url = reverse("admin:catalogo_producto_entrada", args=[self.producto.pk])
        r = self.client.post(url, {"cantidad": "5", "costo_unitario": "8000", "forma_pago": "CON"})
        self.assertEqual(r.status_code, 200)  # vuelve a mostrar el form con el error
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("5"))  # intacto
