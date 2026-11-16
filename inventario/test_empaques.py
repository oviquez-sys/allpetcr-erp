"""Abrir cajas para vender por unidad (pedido de Oscar, 16/11/2026).

Lo que fijan estas pruebas: abrir una caja saca la caja y mete sus unidades
en UN documento; el costo viaja con la mercadería; no se abre lo que no hay;
y la unidad suelta se crea copiando de la caja lo que es igual en las dos.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Producto
from core.models import Empresa, Sucursal

from . import empaques
from .models import Agotamiento, Bodega, MovimientoInventario
from .services import registrar_movimiento


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=sucursal, nombre="Principal")
        self.caja = Producto.objects.create(
            empresa=self.empresa, sku="BEL-900", nombre="Whiskas sobres pollo caja x12",
            precio_venta=Decimal("8990"), marca="Whiskas", mascota="Gato", cabys="2399000000100",
            descripcion="Alimento húmedo", imagen="productos/BEL-900.webp",
        )
        # 3 cajas a ₡6.000 c/u → el sobre debe entrar a ₡500.
        registrar_movimiento(producto=self.caja, bodega=self.bodega, tipo="COM", cantidad=Decimal(3),
                             costo_unitario=Decimal("6000"), referencia="OC-1")
        self.caja.refresh_from_db()
        User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.client.login(username="oscar", password="x")

    def crear_sobre(self, **extra):
        datos = dict(empaque=self.caja, unidades=12, nombre="Whiskas sobre pollo 85 g",
                     precio_venta="990", codigo_barras="7501234567890", presentacion="85 g")
        datos.update(extra)
        return empaques.crear_unidad(**datos)


class CrearLaUnidad(Base):
    def test_copia_de_la_caja_lo_que_es_igual_y_pide_lo_demas(self):
        sobre = self.crear_sobre()
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.unidad_suelta, sobre)
        self.assertEqual(self.caja.unidades_por_empaque, 12)
        self.assertEqual(sobre.sku, "BEL-900-U")
        self.assertEqual((sobre.marca, sobre.mascota, sobre.cabys, sobre.imagen),
                         ("Whiskas", "Gato", "2399000000100", "productos/BEL-900.webp"))
        self.assertEqual(sobre.precio_venta, Decimal("990"))
        self.assertEqual(sobre.codigo_barras, "7501234567890")
        self.assertEqual(sobre.stock_actual, 0)

    def test_sin_codigo_de_barras_recibe_uno_interno(self):
        sobre = self.crear_sobre(codigo_barras="")
        self.assertTrue(sobre.codigo_barras)

    def test_codigo_de_barras_repetido_no_crea_duplicado(self):
        with self.assertRaises(ValidationError):
            self.crear_sobre(codigo_barras=self.caja.codigo_barras)
        self.assertFalse(Producto.objects.filter(sku="BEL-900-U").exists())

    def test_sin_precio_o_con_una_sola_unidad_no_se_crea(self):
        with self.assertRaises(ValidationError):
            self.crear_sobre(precio_venta="")
        with self.assertRaises(ValidationError):
            self.crear_sobre(unidades=1)

    def test_no_puede_ser_ella_misma_ni_en_circulo(self):
        with self.assertRaises(ValidationError):
            empaques.vincular_unidad(empaque=self.caja, unidad=self.caja, unidades=12)
        sobre = self.crear_sobre()
        with self.assertRaises(ValidationError):
            empaques.vincular_unidad(empaque=sobre, unidad=self.caja, unidades=2)


class Abrir(Base):
    def setUp(self):
        super().setUp()
        self.sobre = self.crear_sobre()

    def test_sale_la_caja_y_entran_las_unidades_en_un_documento(self):
        r = empaques.abrir_empaque(empaque=self.caja, cajas=2, bodega=self.bodega)
        self.caja.refresh_from_db(); self.sobre.refresh_from_db()
        self.assertEqual(self.caja.stock_actual, 1)
        self.assertEqual(self.sobre.stock_actual, 24)
        movs = MovimientoInventario.objects.filter(referencia=r["referencia"])
        self.assertEqual(movs.count(), 2)
        self.assertEqual(set(movs.values_list("tipo", flat=True)), {"ABR"})

    def test_el_costo_viaja_con_la_mercaderia(self):
        empaques.abrir_empaque(empaque=self.caja, cajas=1, bodega=self.bodega)
        self.sobre.refresh_from_db(); self.caja.refresh_from_db()
        self.assertEqual(self.sobre.costo_promedio, Decimal("500.00"))
        # La caja que queda no cambia de costo por abrir otra.
        self.assertEqual(self.caja.costo_promedio, Decimal("6000.00"))

    def test_no_se_abre_lo_que_no_hay_y_no_queda_nada_a_medias(self):
        with self.assertRaises(ValidationError):
            empaques.abrir_empaque(empaque=self.caja, cajas=4, bodega=self.bodega)
        self.sobre.refresh_from_db(); self.caja.refresh_from_db()
        self.assertEqual((self.caja.stock_actual, self.sobre.stock_actual), (3, 0))
        self.assertFalse(MovimientoInventario.objects.filter(tipo="ABR").exists())

    def test_sin_configurar_no_abre(self):
        otra = Producto.objects.create(empresa=self.empresa, sku="X-1", nombre="Caja suelta", precio_venta=1)
        with self.assertRaises(ValidationError):
            empaques.abrir_empaque(empaque=otra, cajas=1, bodega=self.bodega)

    def test_abrir_la_ultima_caja_avisa_que_se_agoto(self):
        empaques.abrir_empaque(empaque=self.caja, cajas=3, bodega=self.bodega)
        self.assertTrue(Agotamiento.objects.filter(producto=self.caja, repuesto_en__isnull=True).exists())

    def test_las_unidades_que_entran_cierran_el_aviso_del_sobre(self):
        empaques.abrir_empaque(empaque=self.caja, cajas=1, bodega=self.bodega)
        registrar_movimiento(producto=self.sobre, bodega=self.bodega, tipo="VEN", cantidad=Decimal(-12))
        self.assertTrue(Agotamiento.objects.filter(producto=self.sobre, repuesto_en__isnull=True).exists())
        empaques.abrir_empaque(empaque=self.caja, cajas=1, bodega=self.bodega)
        self.assertFalse(Agotamiento.objects.filter(producto=self.sobre, repuesto_en__isnull=True).exists())


class Pantalla(Base):
    def test_se_llega_desde_recibir_mercaderia_y_desde_administracion(self):
        self.assertContains(self.client.get(reverse("compras:nueva")), reverse("inventario:abrir"))
        self.assertContains(self.client.get("/admin/"), reverse("inventario:abrir"))

    def test_configurar_y_abrir_desde_la_pantalla(self):
        url = reverse("inventario:abrir_producto", args=[self.caja.pk])
        self.assertContains(self.client.get(url), "¿Qué se vende suelto de esta caja?")
        r = self.client.post(url, {"accion": "crear", "unidades": "12", "nombre": "Sobre pollo",
                                   "precio_venta": "990", "codigo_barras": "", "presentacion": "85 g"})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(url, {"accion": "abrir", "cajas": "1"}, follow=True)
        self.assertContains(r, "entraron 12 unidades")
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.unidad_suelta.stock_actual, 12)

    def test_vincular_escaneando_un_producto_que_ya_existe(self):
        sobre = Producto.objects.create(empresa=self.empresa, sku="BEL-901", nombre="Sobre suelto",
                                        codigo_barras="7509999999999", precio_venta=990)
        url = reverse("inventario:abrir_producto", args=[self.caja.pk])
        self.client.post(url, {"accion": "vincular", "codigo": "7509999999999", "unidades": "12"})
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.unidad_suelta, sobre)

    def test_un_error_se_muestra_y_no_se_pierde_lo_escrito(self):
        url = reverse("inventario:abrir_producto", args=[self.caja.pk])
        r = self.client.post(url, {"accion": "crear", "unidades": "12", "nombre": "Sobre pollo",
                                   "precio_venta": "", "codigo_barras": "", "presentacion": "85 g"})
        self.assertContains(r, "Poné el precio de venta")
        self.assertContains(r, 'value="85 g"')

    def test_el_cajero_no_entra(self):
        from django.contrib.auth.models import Group
        cajero = User.objects.create_user("caja", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        r = self.client.get(reverse("inventario:abrir"))
        self.assertNotEqual(r.status_code, 200)
