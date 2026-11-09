"""Catálogo para redes (06/11/2026).

Lo que no se puede romper: el .zip trae todo lo prometido (PDFs, fotos de
1080 × 1080 limpias, publicaciones 1080 × 1350 con
precio, CSV de Facebook y Excel de WhatsApp); lo
que no tiene foto no entra; la promoción sale con su precio de oferta; y solo
el gerente lo arma.
"""
import csv
import io
import tempfile
import zipfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from inventario.services import registrar_movimiento
from ventas.test_auditoria_2026_09 import Base

from . import redes
from .models import Categoria, PaqueteRedes, Producto, Promocion, PromocionProducto
from .promociones import activar


def _foto(color=(200, 40, 40), tam=(600, 800)):
    im = Image.new("RGB", tam, "white")
    im.paste(Image.new("RGB", (tam[0] // 2, tam[1] // 2), color), (tam[0] // 4, tam[1] // 4))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), CATALOGO_REDES_EN_HILO=False)
class CatalogoRedes(Base):
    def setUp(self):
        super().setUp()
        Group.objects.get_or_create(name="Gerente")[0].user_set.add(self.usuario)
        self.snacks = Categoria.objects.create(nombre="Snacks y premios", orden=20)
        self.juguetes = Categoria.objects.create(nombre="Juguetes", orden=30)
        self.a = self._prod("S1", "Waldo Premios Queso 150 g", self.snacks, "Perro", 2290)
        self.b = self._prod("S2", "Waldo Cat Pillows / Salmón", self.snacks, "Gato", 1490)
        self.c = self._prod("J1", "Peluche dona", self.juguetes, "Perro y gato", 2190)
        self.sin_foto = self._prod("J2", "Sin foto", self.juguetes, "Perro", 1000, foto=False)

    def _prod(self, sku, nombre, cat, mascota, precio, foto=True):
        p = Producto.objects.create(empresa=self.empresa, sku=sku, nombre=nombre, categoria=cat, mascota=mascota,
                                    precio_venta=Decimal(precio), impuesto=self.iva, cabys="2921001000000",
                                    presentacion="150 g")
        if foto:
            p.imagen = default_storage.save(f"productos/{sku}.jpg", ContentFile(_foto()))
            p.save(update_fields=["imagen"])
        registrar_movimiento(producto=p, bodega=self.bodega, tipo="INI", cantidad=Decimal("5"),
                             costo_unitario=Decimal("500"), referencia="INI")
        return p

    def _armar(self, **filtros):
        self.client.force_login(self.usuario)
        datos = {"solo_existencia": "1", "con_precio": "1"}
        datos.update(filtros)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("catalogo:redes"), datos)
        self.assertEqual(r.status_code, 302)
        p = PaqueteRedes.objects.get()
        self.assertEqual(p.estado, "LIS", p.error)
        with default_storage.open(p.archivo, "rb") as f:
            return p, zipfile.ZipFile(io.BytesIO(f.read()))

    def test_el_zip_trae_todo(self):
        p, z = self._armar()
        nombres = z.namelist()
        self.assertEqual(p.productos, 3)
        self.assertEqual(p.sin_foto, 2)                     # «Sin foto» y el arnés de Base
        raiz = nombres[0].split("/")[0]
        for esperado in ("PDF/Catalogo_completo.pdf", "PDF/Snacks y premios - Perro.pdf",
                         "PDF/Snacks y premios - Gato.pdf", "PDF/Juguetes - Perro.pdf", "PDF/Juguetes - Gato.pdf",
                         "Para_WhatsApp_y_Facebook/Snacks y premios/S2 Waldo Cat Pillows Salmón.jpg",
                         "Para_estados_y_publicaciones/Juguetes/J1 Peluche dona.jpg",
                         "catalogo_facebook.csv", "lista_whatsapp.xlsx", "LEAME.txt"):
            self.assertIn(f"{raiz}/{esperado}", nombres)
        self.assertFalse(any("Sin foto" in n for n in nombres))
        im = Image.open(io.BytesIO(z.read(f"{raiz}/Para_WhatsApp_y_Facebook/Juguetes/J1 Peluche dona.jpg")))
        self.assertEqual(im.size, (1080, 1080))
        # 09/11/2026: las publicaciones reemplazaron a la tarjeta 1080 × 1080.
        # Una sola, 1080 × 1350, para todas las redes (Oscar, 09/11/2026).
        im = Image.open(io.BytesIO(z.read(f"{raiz}/Para_estados_y_publicaciones/Juguetes/J1 Peluche dona.jpg")))
        self.assertEqual(im.size, (1080, 1350))
        self.assertTrue(z.read(f"{raiz}/PDF/Catalogo_completo.pdf").startswith(b"%PDF"))
        filas = list(csv.DictReader(io.StringIO(z.read(f"{raiz}/catalogo_facebook.csv").decode("utf-8-sig"))))
        self.assertEqual({f["id"] for f in filas}, {"S1", "S2", "J1"})
        self.assertEqual(next(f for f in filas if f["id"] == "S1")["price"], "2290.00 CRC")
        self.assertTrue(next(f for f in filas if f["id"] == "S1")["link"].endswith("/producto/S1"))

    def test_la_promocion_sale_con_su_precio(self):
        hoy = timezone.localdate()
        promo = Promocion.objects.create(empresa=self.empresa, nombre="Noviembre loco", descuento_pct=40,
                                         inicio=hoy, fin=hoy + timedelta(days=10))
        PromocionProducto.objects.create(promocion=promo, producto=self.c)
        activar(promo)
        items, _ = redes.productos(self.empresa)
        dona = next(i for i in items if i.producto == self.c)
        self.assertLess(dona.precio, Decimal("2190"))
        p, z = self._armar(solo_ofertas="1")
        self.assertEqual(p.productos, 1)
        raiz = z.namelist()[0].split("/")[0]
        fila = next(csv.DictReader(io.StringIO(z.read(f"{raiz}/catalogo_facebook.csv").decode("utf-8-sig"))))
        self.assertEqual(fila["price"], "2190.00 CRC")
        self.assertEqual(fila["sale_price"], f"{dona.precio:.2f} CRC")

    def test_por_categoria(self):
        p, z = self._armar(categoria=str(self.juguetes.pk))
        self.assertEqual(p.productos, 1)

    def test_solo_gerente(self):
        cajero = User.objects.create_user("maria", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        self.assertNotEqual(self.client.get(reverse("catalogo:redes")).status_code, 200)

    def test_un_paquete_colgado_se_da_por_perdido(self):
        p = PaqueteRedes.objects.create(empresa=self.empresa)
        PaqueteRedes.objects.filter(pk=p.pk).update(creado_en=timezone.now() - timedelta(hours=1))
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("catalogo:redes"))
        self.assertContains(r, "Se interrumpió")

    def test_descargar(self):
        p, _ = self._armar()
        r = self.client.get(reverse("catalogo:redes_descargar", args=[p.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])

    def test_si_no_entra_nada_lo_dice(self):
        self.client.force_login(self.usuario)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("catalogo:redes"), {"solo_existencia": "1", "solo_ofertas": "1"})
        p = PaqueteRedes.objects.get()
        self.assertEqual(p.estado, "ERR")
        self.assertIn("Ningún producto", p.error)

    def test_eliminar_un_paquete(self):
        p, _ = self._armar()
        archivo = p.archivo
        self.assertTrue(default_storage.exists(archivo))
        r = self.client.post(reverse("catalogo:redes_borrar", args=[p.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PaqueteRedes.objects.filter(pk=p.pk).exists())
        self.assertFalse(default_storage.exists(archivo))

    def test_uno_que_se_esta_armando_no_se_elimina(self):
        self.client.force_login(self.usuario)
        p = PaqueteRedes.objects.create(empresa=self.empresa)
        self.client.post(reverse("catalogo:redes_borrar", args=[p.pk]))
        self.assertTrue(PaqueteRedes.objects.filter(pk=p.pk).exists())

    def test_eliminar_solo_gerente_y_solo_por_post(self):
        p, _ = self._armar()
        self.client.get(reverse("catalogo:redes_borrar", args=[p.pk]))
        self.assertTrue(PaqueteRedes.objects.filter(pk=p.pk).exists())
        cajero = User.objects.create_user("maria", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        self.client.post(reverse("catalogo:redes_borrar", args=[p.pk]))
        self.assertTrue(PaqueteRedes.objects.filter(pk=p.pk).exists())

    def test_sin_senal_de_vida_por_10_minutos_se_da_por_perdido(self):
        """Un reinicio del servidor mata el hilo: no hay que esperar 30 min."""
        self.client.force_login(self.usuario)
        vivo = PaqueteRedes.objects.create(empresa=self.empresa)
        PaqueteRedes.objects.filter(pk=vivo.pk).update(creado_en=timezone.now() - timedelta(minutes=25),
                                                       senal_en=timezone.now() - timedelta(minutes=2))
        self.client.get(reverse("catalogo:redes"))
        self.assertEqual(PaqueteRedes.objects.get(pk=vivo.pk).estado, "ARM")      # largo pero vivo
        PaqueteRedes.objects.filter(pk=vivo.pk).update(senal_en=timezone.now() - timedelta(minutes=11))
        r = self.client.get(reverse("catalogo:redes"))
        self.assertEqual(PaqueteRedes.objects.get(pk=vivo.pk).estado, "ERR")
        self.assertContains(r, "Se interrumpió")
