"""Ajustes de inventario (pedido de Oscar, 12/10/2026).

Lo que fijan estas pruebas: la pantalla vive en Administración y ya no en
Etiquetas; se escribe lo que hay DE VERDAD y el sistema saca la diferencia;
los datos y la foto del producto se cambian ahí mismo, y el precio sigue
quedando firmado en su historial.
"""
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from catalogo.models import CambioPrecio, Producto
from core.models import Empresa, Sucursal

from .models import Bodega, MovimientoInventario
from .services import registrar_movimiento


def _png():
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (40, 40), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


class BaseAjustes(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=sucursal, nombre="Principal")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="NP-1", nombre="Arnés acolchado M", precio_venta=Decimal("9900"),
        )
        User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.client.login(username="oscar", password="x")
        self.url = reverse("inventario:ajuste_producto", args=[self.producto.pk])

    def existencia(self, **datos):
        base = {"accion": "existencia", "bodega": self.bodega.pk, "tipo": "Conteo físico",
                "motivo": "Venían en otra factura y no se ingresaron"}
        base.update(datos)
        return self.client.post(self.url, base)


class DondeVive(BaseAjustes):
    def test_esta_en_administracion(self):
        r = self.client.get("/admin/")
        self.assertContains(r, reverse("inventario:ajustes"))
        self.assertContains(r, "Ajustes de inventario")

    def test_ya_no_esta_en_etiquetas(self):
        r = self.client.get(reverse("inventario:etiquetas"))
        self.assertNotContains(r, reverse("inventario:ajuste"))
        self.assertNotContains(r, "Ajustar inventario")

    def test_la_direccion_vieja_lleva_a_la_nueva(self):
        r = self.client.get(reverse("inventario:ajuste"))
        self.assertRedirects(r, reverse("inventario:ajustes"))

    def test_la_lista_muestra_agotados_e_inactivos(self):
        Producto.objects.create(empresa=self.empresa, sku="X-2", nombre="Collar viejo", activo=False)
        r = self.client.get(reverse("inventario:ajustes"))
        self.assertContains(r, "Arnés acolchado M")  # en cero
        self.assertContains(r, "Collar viejo")
        self.assertContains(r, "inactivo")

    def test_el_cajero_no_entra(self):
        cajero = User.objects.create_user("caja", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.login(username="caja", password="x")
        self.assertNotEqual(self.client.get(reverse("inventario:ajustes")).status_code, 200)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)


class CuantasHay(BaseAjustes):
    def test_se_escribe_lo_que_hay_y_el_sistema_saca_la_diferencia(self):
        # El caso real de Oscar: el sistema dice 0 y en el estante hay 12.
        r = self.existencia(cantidad_real="12", costo_unitario="4500")
        self.assertRedirects(r, self.url)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("12"))
        self.assertEqual(self.producto.costo_promedio, Decimal("4500.00"))
        mov = MovimientoInventario.objects.get(tipo="AJU")
        self.assertEqual(mov.cantidad, Decimal("12"))
        self.assertTrue(mov.motivo.startswith("[Conteo físico] "))
        self.assertIsNotNone(mov.usuario)

    def test_sumar_sin_costo_a_un_producto_sin_costo_no_se_permite(self):
        r = self.existencia(cantidad_real="12")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Poné lo que costó cada unidad")
        self.assertFalse(MovimientoInventario.objects.exists())

    def test_sumar_sin_costo_usa_el_costo_promedio_si_ya_tiene(self):
        registrar_movimiento(producto=self.producto, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("2"), costo_unitario=Decimal("4000"), referencia="INI")
        self.existencia(cantidad_real="5")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("5"))
        self.assertEqual(self.producto.costo_promedio, Decimal("4000.00"))

    def test_contar_menos_resta(self):
        registrar_movimiento(producto=self.producto, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("10"), costo_unitario=Decimal("4000"), referencia="INI")
        self.existencia(cantidad_real="7", tipo="Daño", motivo="Tres rotos")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("7"))
        self.assertEqual(MovimientoInventario.objects.get(tipo="AJU").cantidad, Decimal("-3"))

    def test_si_ya_coincide_avisa_y_no_mueve_nada(self):
        r = self.existencia(cantidad_real="0")
        self.assertContains(r, "no hay nada que ajustar")
        self.assertFalse(MovimientoInventario.objects.filter(tipo="AJU").exists())


class DatosDelProducto(BaseAjustes):
    def datos(self, **cambios):
        base = {"accion": "datos", "nombre": self.producto.nombre, "codigo_barras": "",
                "marca": "", "categoria": "", "presentacion": "", "mascota": "Perro",
                "descripcion": "", "peso_valor": "", "peso_unidad": "", "stock_minimo": "2",
                "cabys": "", "activo": "on", "precio_venta": "9900"}
        base.update(cambios)
        return self.client.post(self.url, base)

    def test_cambia_los_datos(self):
        r = self.datos(nombre="Arnés acolchado talla M", marca="Zee.Dog", descripcion="Suave y ajustable.")
        self.assertRedirects(r, self.url)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.nombre, "Arnés acolchado talla M")
        self.assertEqual(self.producto.marca, "Zee.Dog")
        self.assertEqual(self.producto.mascota, "Perro")
        self.assertFalse(CambioPrecio.objects.exists(), "El precio no cambió: no se firma nada")

    def test_el_cambio_de_precio_queda_en_su_historial(self):
        self.datos(precio_venta="10900")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("10900"))
        cambio = CambioPrecio.objects.get()
        self.assertEqual(cambio.valor_anterior, Decimal("9900"))
        self.assertEqual(cambio.valor_nuevo, Decimal("10900"))

    def test_codigo_de_barras_repetido_no_se_guarda(self):
        Producto.objects.create(empresa=self.empresa, sku="X-3", nombre="Otro", codigo_barras="7441000000001")
        r = self.datos(codigo_barras="7441000000001")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ese código ya es de «Otro»")

    def test_no_toca_existencia_ni_costo(self):
        self.client.post(self.url, {"accion": "datos", "nombre": "X", "precio_venta": "9900",
                                    "stock_minimo": "2", "activo": "on",
                                    "stock_actual": "999", "costo_promedio": "1"})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("0"))
        self.assertEqual(self.producto.costo_promedio, Decimal("0"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FotoDelProducto(BaseAjustes):
    def test_cambia_la_foto_con_nombre_nuevo(self):
        r = self.client.post(self.url, {"accion": "foto",
                                        "foto": SimpleUploadedFile("x.png", _png(), "image/png")})
        self.assertRedirects(r, self.url)
        self.producto.refresh_from_db()
        # Nombre con fecha: con el mismo nombre de antes el sitio seguiría
        # mostrando la foto vieja (caché de 30 días).
        self.assertTrue(self.producto.imagen.startswith("productos/NP-1-"))
        self.assertTrue(self.producto.imagen.endswith(".png"))

    def test_un_archivo_que_no_es_foto_se_rechaza(self):
        r = self.client.post(self.url, {"accion": "foto",
                                        "foto": SimpleUploadedFile("x.png", b"<svg></svg>", "image/png")})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "no es una imagen")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.imagen, "")
