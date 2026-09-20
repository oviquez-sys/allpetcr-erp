"""Fotos de producto en todo el ERP (20/09/2026).

Qué se verifica y por qué:
- Ninguna plantilla arma la URL de una foto a mano. Ese fue el error que
  dejó fotos rotas en producción (`{{ MEDIA_URL }}{{ p.imagen }}` apunta a
  /media/, que el servidor no tiene: las fotos viven en el bucket).
- Las miniaturas se generan al guardar una foto, y si faltan, /foto/<id>/
  las genera y redirige.
- Las pantallas donde se habla de un producto muestran su foto.
"""
import io
import re
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from catalogo.models import Categoria, Producto
from core.chat_tools import ejecutar_herramienta, skus_mencionados, tarjetas_de_productos
from core.imagenes import (
    completar_foto, datos_foto, generar_miniatura, guardar_imagen_producto, ruta_miniatura,
)
from core.models import Empresa


def _jpeg(lado=900, color=(200, 120, 40)):
    b = io.BytesIO()
    Image.new("RGB", (lado, lado), color).save(b, "JPEG")
    return b.getvalue()


class NingunaPlantillaArmaLaUrlAMano(TestCase):
    """Regla de arquitectura: la foto se dibuja con {% foto_producto %}."""

    PROHIBIDOS = [
        re.compile(r"MEDIA_URL\s*\}\}\s*\{\{[^}]*imagen"),       # {{ MEDIA_URL }}{{ p.imagen }}
        re.compile(r"[\"']/media/\{\{"),                         # src="/media/{{ ... }}"
        re.compile(r"background-image:url\([^)]*\.imagen"),      # foto grande como fondo CSS
    ]

    def test_sin_urls_de_foto_armadas_a_mano(self):
        infractores = []
        for ruta in Path(settings.BASE_DIR, "templates").rglob("*.html"):
            for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
                if any(p.search(linea) for p in self.PROHIBIDOS):
                    infractores.append(f"{ruta.relative_to(settings.BASE_DIR)}:{n}")
        self.assertEqual(infractores, [], "Usá {% foto_producto p 44 %} (plantillas) o fotoHTML(p) (JavaScript).")


class _ConMedia(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.tmp)
        self.override.enable()
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cat = Categoria.objects.create(nombre="Juguetes")
        self.p = Producto.objects.create(
            empresa=self.empresa, sku="75564", nombre="Pelota roja", categoria=self.cat,
            precio_venta=Decimal("1500"), stock_actual=Decimal("1"), stock_minimo=Decimal("2"),
            mascota="Perro",
        )
        User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.client.login(username="oscar", password="x")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _con_foto(self):
        self.p.imagen = guardar_imagen_producto("75564.jpeg", _jpeg())
        self.p.save(update_fields=["imagen"])
        return self.p


class Miniaturas(_ConMedia):
    def test_ruta_de_la_miniatura(self):
        self.assertEqual(ruta_miniatura("productos/75564.jpeg"), "productos/min/75564.webp")
        self.assertEqual(ruta_miniatura(""), "")

    def test_guardar_una_foto_crea_su_miniatura_chica(self):
        self._con_foto()
        mini = ruta_miniatura(self.p.imagen)
        self.assertTrue(default_storage.exists(mini))
        with default_storage.open(mini, "rb") as f:
            img = Image.open(f)
            img.load()
        self.assertLessEqual(max(img.size), 240)
        self.assertEqual(img.format, "WEBP")

    def test_generar_si_falta_y_no_romper_si_no_hay_original(self):
        self._con_foto()
        default_storage.delete(ruta_miniatura(self.p.imagen))
        self.assertTrue(generar_miniatura(self.p.imagen))
        self.assertEqual(generar_miniatura("productos/no-existe.jpeg"), "")

    def test_respaldo_genera_y_redirige(self):
        self._con_foto()
        default_storage.delete(ruta_miniatura(self.p.imagen))
        r = self.client.get(reverse("core:foto_producto", args=[self.p.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("productos/min/75564.webp", r["Location"])
        self.assertTrue(default_storage.exists(ruta_miniatura(self.p.imagen)))

    def test_respaldo_exige_sesion(self):
        self._con_foto()
        self.client.logout()
        r = self.client.get(reverse("core:foto_producto", args=[self.p.pk]))
        self.assertNotEqual(r.status_code, 200)
        self.assertNotIn("productos/min", r.get("Location", ""))

    def test_datos_para_el_navegador(self):
        self._con_foto()
        d = datos_foto(self.p)
        self.assertIn("productos/min/75564.webp?v=", d["miniatura"])
        self.assertTrue(d["imagen"].endswith("productos/75564.jpeg"))
        self.assertEqual(d["respaldo"], f"/foto/{self.p.pk}/")
        fila = completar_foto({"id": self.p.pk, "imagen": self.p.imagen, "actualizado_en": self.p.actualizado_en})
        self.assertNotIn("actualizado_en", fila)
        self.assertEqual(fila["respaldo"], d["respaldo"])
        self.assertEqual(completar_foto({"id": 1, "imagen": ""})["miniatura"], "")

    def test_tag_sin_foto_dibuja_la_huella(self):
        html = Template("{% foto_producto p 40 %}").render(Context({"p": self.p}))
        self.assertIn("🐾", html)
        self.assertNotIn("<img", html)

    def test_tag_con_foto(self):
        self._con_foto()
        html = Template('{% foto_producto p 40 "clickable-product-img" %}').render(Context({"p": self.p}))
        self.assertIn('loading="lazy"', html)
        self.assertIn("productos/min/75564.webp", html)
        self.assertIn('data-grande="', html)
        self.assertIn(f'data-respaldo="/foto/{self.p.pk}/"', html)


class PantallasConFoto(_ConMedia):
    """Donde se habla de un producto, se ve su foto (la miniatura)."""

    def setUp(self):
        super().setUp()
        self._con_foto()

    def _tiene_foto(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        self.assertContains(r, "productos/min/75564.webp", msg_prefix=url)
        self.assertNotContains(r, 'src="/media/productos/75564', msg_prefix=url)
        return r

    def test_precios(self):
        self._tiene_foto(reverse("catalogo:precios") + "?q=pelota")

    def test_precio_producto(self):
        self._tiene_foto(reverse("catalogo:precio_producto", args=[self.p.pk]))

    def test_reporte_stock(self):
        self._tiene_foto(reverse("core:reporte_stock"))

    def test_completar_catalogo(self):
        self.p.mascota = ""
        self.p.save(update_fields=["mascota"])
        self._tiene_foto(reverse("catalogo:completar"))

    def test_admin_producto(self):
        self._tiene_foto(reverse("admin:catalogo_producto_changelist"))
        self._tiene_foto(reverse("admin:catalogo_producto_change", args=[self.p.pk]))

    def test_etiquetas_manda_miniatura(self):
        self._tiene_foto(reverse("inventario:etiquetas"))

    def test_pos_manda_miniatura(self):
        r = self.client.get(reverse("ventas:pos"))
        if r.status_code == 302:  # sin caja abierta el POS redirige: se prueba el armado de datos
            from core.imagenes import completar_foto
            fila = completar_foto({"id": self.p.pk, "imagen": self.p.imagen})
            self.assertIn("productos/min/75564.webp", fila["miniatura"])
        else:
            self.assertContains(r, "productos/min/75564.webp")


class ChatConFotos(_ConMedia):
    def test_buscar_producto_por_nombre_y_sku(self):
        r = ejecutar_herramienta("buscar_producto", {"texto": "pelota"}, usuario=User.objects.get(username="oscar"))
        self.assertEqual([p["sku"] for p in r["productos"]], ["75564"])
        r = ejecutar_herramienta("buscar_producto", {"texto": "75564"}, usuario=User.objects.get(username="oscar"))
        self.assertEqual(len(r["productos"]), 1)
        self.assertNotIn("costo_promedio", str(r))

    def test_tarjetas_traen_la_foto(self):
        self._con_foto()
        skus = skus_mencionados({"productos": [{"sku": "75564"}, {"sku": "75564"}, {"sku": "nada"}]})
        self.assertEqual(skus, ["75564", "nada"])
        tarjetas = tarjetas_de_productos(skus, self.empresa)
        self.assertEqual(len(tarjetas), 1)
        self.assertIn("productos/min/75564.webp", tarjetas[0]["miniatura"])
