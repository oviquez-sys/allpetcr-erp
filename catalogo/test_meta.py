"""Catálogo de WhatsApp por Meta (24/11/2026).

Lo que no se puede romper: el enlace es público pero solo con su clave; trae
lo publicado con foto, también lo agotado (como agotado); lo de salud no
entra; el envío gratis y el sorteo salen de la campaña con sus reglas exactas
(«más de ₡20.000», fechas, zonas) y se quitan solos; la oferta dice hasta
cuándo; y la pantalla es solo del gerente.
"""
import csv
import io
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from campanas.models import Campana
from inventario.services import registrar_movimiento
from ventas.test_auditoria_2026_09 import Base

from . import meta
from .models import CatalogoMeta, Categoria, Producto, Promocion, PromocionProducto
from .promociones import activar
from .test_redes import _foto


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), SITIO_WEB_URL="https://www.allpetcr.com")
class CatalogoWhatsApp(Base):
    def setUp(self):
        super().setUp()
        Group.objects.get_or_create(name="Gerente")[0].user_set.add(self.usuario)
        self.alimento = Categoria.objects.create(nombre="Alimento", orden=10)
        self.seco = Categoria.objects.create(nombre="Alimento seco", padre=self.alimento, orden=11)
        self.juguetes = Categoria.objects.create(nombre="Juguetes", orden=30)
        self.higiene = Categoria.objects.create(nombre="Higiene y aseo", orden=80)
        self.descanso = Categoria.objects.create(nombre="Descanso", orden=70)
        self.salud = Categoria.objects.create(nombre="Salud y cuidado", orden=90)
        self.saco = self._prod("BEL-1", "Balance Adulto 14.97 kg", self.seco, "Perro", 23800,
                               descripcion="Alimento seco completo de Belina para perros adultos.")
        self.justo = self._prod("BEL-2", "Balance Adulto 9.07 kg", self.seco, "Perro", 20000)
        self.dona = self._prod("J1", "Peluche dona", self.juguetes, "Perro y gato", 2190)
        self.cat = self._prod("J2", "Waldo Cat Pillows", self.juguetes, "Gato", 1490)
        self.pipeta = self._prod("S1", "Pipeta para perro", self.salud, "Perro", 9900)
        self.champu = self._prod("H1", "Champú antipulgas 250 ml", self.higiene, "Perro", 4500)
        self.cama = self._prod("C1", "Cama redonda 30 pulgadas", self.descanso, "Perro", 15900)
        self.agotado = self._prod("J3", "Pelota voladora", self.juguetes, "Perro", 2490, stock=False)
        self.sin_foto = self._prod("J4", "Sin foto", self.juguetes, "Perro", 1000, foto=False)
        self.conf = CatalogoMeta.objects.create(empresa=self.empresa)

    def _prod(self, sku, nombre, cat, mascota, precio, foto=True, stock=True, descripcion=""):
        p = Producto.objects.create(empresa=self.empresa, sku=sku, nombre=nombre, categoria=cat, mascota=mascota,
                                    precio_venta=Decimal(precio), impuesto=self.iva, cabys="2921001000000",
                                    descripcion=descripcion, publicar_web=True)
        if foto:
            p.imagen = default_storage.save(f"productos/{sku}.jpg", ContentFile(_foto()))
            p.save(update_fields=["imagen"])
        if stock:
            registrar_movimiento(producto=p, bodega=self.bodega, tipo="INI", cantidad=Decimal("5"),
                                 costo_unitario=Decimal("500"), referencia="INI")
        return p

    def _campana(self, **cambios):
        ahora = timezone.now()
        datos = dict(empresa=self.empresa, nombre="Navidad AllPet 2026", slug="navidad-2026",
                     inicio=ahora - timedelta(days=1), cierre=ahora + timedelta(days=20),
                     sorteo_en=ahora + timedelta(days=21), bases="Bases.", estado=Campana.Estado.ACTIVA)
        datos.update(cambios)
        return Campana.objects.create(**datos)

    def _filas(self, respuesta=None):
        r = respuesta or self.client.get(reverse("catalogo:feed_meta", args=[self.conf.clave]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/csv"))
        texto = r.content.decode("utf-8")
        self.assertFalse(texto.startswith("﻿"), "Meta lee el archivo: sin BOM")
        return {f["id"]: f for f in csv.DictReader(io.StringIO(texto))}

    # --- el enlace --------------------------------------------------------
    def test_el_enlace_es_publico_y_trae_el_catalogo(self):
        filas = self._filas()
        self.assertEqual(set(filas), {"BEL-1", "BEL-2", "J1", "J2", "C1", "J3"})
        saco = filas["BEL-1"]
        self.assertEqual(saco["price"], "23800.00 CRC")
        self.assertEqual(saco["availability"], "in stock")
        self.assertEqual(saco["link"], "https://www.allpetcr.com/producto/BEL-1?o=whatsapp-catalogo")
        self.assertEqual(saco["product_type"], "Alimento > Alimento seco")
        self.assertEqual(saco["custom_label_0"], "Perro")
        self.assertTrue(saco["description"].startswith("Alimento seco completo de Belina"))
        self.assertIn(CatalogoMeta.LINEA_ENTREGA, saco["description"])
        self.assertTrue(saco["description"].endswith("Precio con IVA. Agregalo al carrito y mandanos el pedido."))

    def test_lo_agotado_entra_como_agotado(self):
        self.assertEqual(self._filas()["J3"]["availability"], "out of stock")

    def test_lo_de_salud_no_entra_pero_la_cama_de_pulgadas_si(self):
        filas = self._filas()
        self.assertNotIn("S1", filas)     # categoría Salud y cuidado
        self.assertNotIn("H1", filas)     # antipulgas en Higiene
        self.assertIn("C1", filas)        # «pulgadas» no es «pulgas»
        _, fuera, sin_foto = meta.seleccion(self.empresa)
        self.assertEqual(fuera, 2)

    def test_clave_mala_o_enlace_apagado_no_existe(self):
        self.assertEqual(self.client.get(reverse("catalogo:feed_meta", args=["otra"])).status_code, 404)
        CatalogoMeta.objects.filter(pk=self.conf.pk).update(activo=False)
        self.assertEqual(self.client.get(reverse("catalogo:feed_meta", args=[self.conf.clave])).status_code, 404)

    def test_solo_se_lee(self):
        r = self.client.post(reverse("catalogo:feed_meta", args=[self.conf.clave]))
        self.assertEqual(r.status_code, 405)

    def test_cuenta_las_lecturas_de_meta_y_no_las_del_erp(self):
        self._filas()
        self.conf.refresh_from_db()
        self.assertEqual(self.conf.lecturas, 1)
        self.assertIsNotNone(self.conf.ultima_lectura)
        self.client.force_login(self.usuario)
        self._filas()
        self.conf.refresh_from_db()
        self.assertEqual(self.conf.lecturas, 1)

    def test_el_titulo_dice_la_especie_si_el_nombre_no_la_dice(self):
        filas = self._filas()
        self.assertEqual(filas["J1"]["title"], "Peluche dona · Perro y gato")
        self.assertEqual(filas["J2"]["title"], "Waldo Cat Pillows")

    # --- el cierre ----------------------------------------------------------
    def test_sin_campana_no_promete_envio_ni_sorteo(self):
        d = self._filas()["BEL-1"]["description"]
        self.assertNotIn("envío gratis", d)
        self.assertNotIn("sorteo", d)

    def test_con_campana_usa_sus_reglas_zonas_y_fechas(self):
        c = self._campana()
        filas = self._filas()
        hasta = f"{timezone.localtime(c.cierre):%d/%m}"
        sorteo = f"{timezone.localtime(c.sorteo_en):%d/%m}"
        caro, justo = filas["BEL-1"]["description"], filas["BEL-2"]["description"]
        self.assertIn(f"🎁 Este producto pasa de ₡20.000: envío gratis en Heredia, Mercedes, San Francisco y Ulloa (hasta el {hasta}).", caro)
        self.assertIn(f"🎄 Si estás inscrito en el sorteo del {sorteo}, esta compra te da dos números (compras hasta el {hasta}).", caro)
        # ₡20.000 exactos no pasan el umbral (las bases lo dicen así).
        self.assertIn(f"🎁 Pedido de más de ₡20.000: envío gratis en Heredia, Mercedes, San Francisco y Ulloa (hasta el {hasta}).", justo)
        self.assertIn("cada compra te da un número, y dos si pasa de ₡20.000", justo)

    def test_despues_del_cierre_se_quitan_solos(self):
        ahora = timezone.now()
        self._campana(inicio=ahora - timedelta(days=30), cierre=ahora - timedelta(hours=1), sorteo_en=ahora + timedelta(days=1))
        d = self._filas()["BEL-1"]["description"]
        self.assertNotIn("sorteo", d)
        self.assertNotIn("envío gratis", d)

    def test_la_oferta_lleva_precio_y_hasta_cuando(self):
        hoy = timezone.localdate()
        promo = Promocion.objects.create(empresa=self.empresa, nombre="Navidad", descuento_pct=10,
                                         inicio=hoy, fin=hoy + timedelta(days=5))
        PromocionProducto.objects.create(promocion=promo, producto=self.dona)
        activar(promo)
        f = self._filas()["J1"]
        self.assertEqual(f["price"], "2190.00 CRC")
        self.assertTrue(f["sale_price"].endswith(" CRC"))
        self.assertEqual(f["sale_price_effective_date"],
                         f"{hoy:%Y-%m-%d}T00:00-06:00/{promo.fin:%Y-%m-%d}T23:59-06:00")
        self.assertIn(f"Precio de oferta hasta el {promo.fin:%d/%m} o hasta agotar existencias.", f["description"])

    # --- la pantalla --------------------------------------------------------
    def test_la_pantalla_es_del_gerente(self):
        cajero = User.objects.create_user("caja", password="x", is_staff=True)
        Group.objects.get_or_create(name="Cajero")[0].user_set.add(cajero)
        self.client.force_login(cajero)
        r = self.client.get(reverse("catalogo:redes_whatsapp"))
        self.assertRedirects(r, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_la_pantalla_muestra_el_enlace_y_guarda_la_linea(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("catalogo:redes_whatsapp"))
        self.assertContains(r, self.conf.clave)
        self.assertContains(r, "Meta todavía no lo ha leído")
        self.client.post(reverse("catalogo:redes_whatsapp"), {"accion": "entrega", "linea_entrega": "Retiro gratis en la tienda."})
        self.conf.refresh_from_db()
        self.assertEqual(self.conf.linea_entrega, "Retiro gratis en la tienda.")
        self.assertIn("Retiro gratis en la tienda.", self._filas()["J1"]["description"])

    def test_cambiar_el_enlace_apaga_el_anterior(self):
        vieja = self.conf.clave
        self.client.force_login(self.usuario)
        self.client.post(reverse("catalogo:redes_whatsapp"), {"accion": "clave"})
        self.conf.refresh_from_db()
        self.assertNotEqual(self.conf.clave, vieja)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("catalogo:feed_meta", args=[vieja])).status_code, 404)
        self.assertEqual(self.client.get(reverse("catalogo:feed_meta", args=[self.conf.clave])).status_code, 200)

    def test_la_pantalla_crea_el_enlace_si_no_existe(self):
        CatalogoMeta.objects.all().delete()
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("catalogo:redes_whatsapp")).status_code, 200)
        self.assertEqual(CatalogoMeta.objects.filter(empresa=self.empresa).count(), 1)
