"""Publicaciones de alimentos (09/11/2026).

Lo que no se puede romper:
- Los datos salen de la ficha VERIFICADA, en el orden declarado; sin ficha
  publicable la pieza lleva solo foto, nombre, peso y precio (nada inventado).
- Nada se sale de la pieza ni se encima con el precio, aun con nombres e
  ingredientes larguísimos.
- La descarga solo lleva lo aprobado, y si algo cambió desde la vista previa
  (precio, promoción, ficha o foto) no se descarga: se marca «Desactualizada».
- Solo el gerente; y generar no cambia precios, inventario ni fichas.
"""
import io
import json
import re
import tempfile
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from inventario.services import registrar_movimiento
from ventas.test_auditoria_2026_09 import Base

from . import publicacion as pub
from .models import Categoria, FichaAlimento, Producto, Promocion, PromocionProducto
from .promociones import activar

GOSBI = Path(__file__).resolve().parent / "fichas_alimento" / "gosbi-exclusive-grain-free-dog-adult-medium-fish.json"
CAMPOS_FICHA = ("marca", "linea", "nombre", "especie", "tipo", "etapas", "tamanos_raza", "necesidades",
                "beneficios", "ingredientes", "analisis", "estado")


def _foto(tam=(600, 800)):
    im = Image.new("RGB", tam, "white")
    im.paste(Image.new("RGB", (tam[0] // 2, tam[1] // 2), (40, 40, 40)), (tam[0] // 4, tam[1] // 4))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


class Datos(SimpleTestCase):
    def test_ingredientes_en_el_orden_declarado(self):
        texto = json.loads(GOSBI.read_text(encoding="utf-8"))["ingredientes"]
        self.assertEqual(pub.ingredientes_principales(texto),
                         ["Pescado 47 %", "Almidón de papa 19 %", "Lentejas 12 %", "Grasa de pollo"])

    def test_ingredientes_sin_porcentaje_ni_parentesis(self):
        self.assertEqual(pub.ingredientes_principales("pollo deshuesado, harina de pollo (fuente de glucosamina), arroz"),
                         ["Pollo deshuesado", "Harina de pollo", "Arroz"])
        self.assertEqual(pub.ingredientes_principales(""), [])

    def test_ingredientes_en_ingles_salen_en_espanol(self):
        self.assertEqual(pub.ingredientes_principales("Chicken, Duck Meal, Chicken Meal, Turkey Meal, Brown Rice"),
                         ["Pollo", "Harina de pato", "Harina de pollo", "Harina de pavo"])
        self.assertEqual(pub.ingredientes_principales("pollo* (60 %), arroz* (5 %)"), ["Pollo 60 %", "Arroz 5 %"])

    def test_ninguna_ficha_del_repositorio_sale_en_ingles(self):
        """Si falla: agregá la traducción del ingrediente en publicacion.TRADUCCION."""
        carpeta = GOSBI.parent
        quedaron = set()
        for ruta in carpeta.glob("*.json"):
            j = json.loads(ruta.read_text(encoding="utf-8"))
            if j.get("estado") not in pub.ESTADOS_PUBLICABLES:
                continue
            for x in pub.ingredientes_principales(j.get("ingredientes", "")):
                palabras = set(re.findall(r"[a-záéíóúñ]+", x.lower()))
                if palabras & pub.PALABRAS_INGLES:
                    quedaron.add(f"{ruta.name}: {x}")
        self.assertEqual(sorted(quedaron), [])

    def test_numeros_al_estilo_de_costa_rica(self):
        self.assertEqual(pub._numero("6.9"), "6,9")
        self.assertEqual(pub._numero("27.0"), "27")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Publicaciones(Base):
    def setUp(self):
        super().setUp()
        Group.objects.get_or_create(name="Gerente")[0].user_set.add(self.usuario)
        self.alimento = Categoria.objects.create(nombre="Alimento", orden=10)
        j = json.loads(GOSBI.read_text(encoding="utf-8"))
        self.ficha = FichaAlimento.objects.create(clave=j["clave"], **{k: j[k] for k in CAMPOS_FICHA})
        self.gosbi = self._prod("GOS-918", "Gosbi Exclusive Grain Free Adult Fish Medium 3 kg", 22000,
                                ficha=self.ficha, presentacion="3 kg", marca="Gosbi")
        self.balance = self._prod("BEL-1", "Balance Castrado 2 kg", 9990, presentacion="2 kg", marca="Balance")

    def _prod(self, sku, nombre, precio, ficha=None, **kw):
        p = Producto.objects.create(empresa=self.empresa, sku=sku, nombre=nombre, categoria=self.alimento,
                                    mascota="Perro", precio_venta=Decimal(precio), impuesto=self.iva,
                                    cabys="2921001000000", ficha_alimento=ficha, **kw)
        p.imagen = default_storage.save(f"productos/{sku}.jpg", ContentFile(_foto()))
        p.save(update_fields=["imagen"])
        registrar_movimiento(producto=p, bodega=self.bodega, tipo="INI", cantidad=Decimal("4"),
                             costo_unitario=Decimal("500"), referencia="INI")
        return p

    # --- Qué dice la pieza -------------------------------------------------
    def test_con_ficha(self):
        d = pub.datos(self.gosbi, precio=Decimal("22000"), fecha=date(2026, 11, 9))
        self.assertTrue(d.con_ficha)
        self.assertEqual(d.marca, "Gosbi · Exclusive Grain Free Dog")
        self.assertEqual(d.titulo, "Adult Medium Fish")
        self.assertEqual(d.sub, "Perro adulto · raza mediana")
        self.assertEqual(d.peso, "Bolsa de 3 kg")
        self.assertEqual(d.nutricion, [("Proteína bruta", "27 %"), ("Grasa bruta", "18 %"), ("Cereales", "Sin")])
        # Oscar: «piel, pelo y articulaciones» → los dos beneficios verificados.
        self.assertEqual(d.beneficios, ["Omega 3 para piel y pelaje.", "El omega 3 ayuda a mantener las articulaciones."])
        self.assertEqual(pub.datos(self.gosbi, precio=1, claves_beneficio=["articulaciones"]).beneficios,
                         ["El omega 3 ayuda a mantener las articulaciones."])

    def test_sin_ficha_solo_foto_peso_y_precio(self):
        d = pub.datos(self.balance, precio=Decimal("9990"))
        self.assertFalse(d.con_ficha)
        self.assertEqual((d.ingredientes, d.nutricion, d.beneficios), ([], [], []))
        self.assertEqual((d.titulo, d.peso, d.marca), ("Balance Castrado 2 kg", "2 kg", ""))

    def test_ficha_sin_verificar_no_se_usa(self):
        FichaAlimento.objects.filter(pk=self.ficha.pk).update(estado="revisar")
        self.gosbi.refresh_from_db()
        self.assertFalse(pub.datos(self.gosbi, precio=1).con_ficha)

    def test_sin_cereales_solo_si_lo_declara(self):
        FichaAlimento.objects.filter(pk=self.ficha.pk).update(necesidades=[])
        self.gosbi.refresh_from_db()
        self.assertNotIn(("Cereales", "Sin"), pub.datos(self.gosbi, precio=1).nutricion)

    def test_nada_se_sale_aunque_todo_sea_larguisimo(self):
        largo = "Fórmula superpremium holística con proteína hidrolizada de salmón noruego y arroz integral"
        FichaAlimento.objects.filter(pk=self.ficha.pk).update(
            nombre=largo, linea="Línea con un nombre comercial extremadamente largo para probar",
            ingredientes=", ".join([largo] * 8),
            beneficios=[{"clave": "piel_pelaje", "texto": largo + " " + largo},
                        {"clave": "articulaciones", "texto": largo + " " + largo}])
        self.gosbi.refresh_from_db()
        hoy = timezone.localdate()
        oferta = {"precio": Decimal("1234567"), "precio_antes": Decimal("2345678"), "pct": 47, "hasta": hoy}
        foto = Image.open(io.BytesIO(_foto((1600, 300))))           # foto muy ancha (un juguete)
        for p in (self.gosbi, self.balance):
            d = pub.datos(p, precio=oferta["precio"], oferta=oferta, fecha=hoy)
            d.titulo = largo
            for f, tam in pub.FORMATOS.items():
                im, cupo = pub.dibujar(f, d, foto)
                self.assertEqual(im.size, tam)
                self.assertTrue(cupo, f"{p.sku} {f}: algo no cupo")

    # --- Pantalla ----------------------------------------------------------
    def test_solo_gerente(self):
        cajero = User.objects.create_user("maria", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        self.assertNotEqual(self.client.get(reverse("catalogo:redes_alimentos")).status_code, 200)
        self.assertNotEqual(self.client.get(reverse("catalogo:redes_alimentos_imagen",
                                                    args=[self.gosbi.pk, "feed"])).status_code, 200)

    def test_lista_y_vista_previa(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("catalogo:redes_alimentos"), {"q": "gosbi"})
        self.assertContains(r, "GOS-918")
        self.assertNotContains(r, "BEL-1")
        r = self.client.get(reverse("catalogo:redes_alimentos"), {"sel": [self.gosbi.pk, self.balance.pk],
                                                                  "fmt": ["feed", "story"]})
        self.assertContains(r, "Revisá y aprobá")
        self.assertContains(r, "Sin ficha: solo foto, peso y precio")
        for f, tam in pub.FORMATOS.items():
            r = self.client.get(reverse("catalogo:redes_alimentos_imagen", args=[self.gosbi.pk, f]), {"b": "articulaciones"})
            self.assertEqual(r["Content-Type"], "image/jpeg")
            self.assertEqual(Image.open(io.BytesIO(r.content)).size, tam)

    def _huellas(self, *productos):
        r = self.client.get(reverse("catalogo:redes_alimentos"), {"sel": [p.pk for p in productos], "fmt": ["feed", "story"]})
        return {p.pk: r.context["tarjetas"][i]["huella"] for i, p in enumerate(productos)}

    def test_descarga_solo_lo_aprobado(self):
        self.client.force_login(self.usuario)
        h = self._huellas(self.gosbi, self.balance)
        self.gosbi.refresh_from_db()
        precio_antes, stock_antes = self.gosbi.precio_venta, self.gosbi.stock_actual
        r = self.client.post(reverse("catalogo:redes_alimentos"), {
            "sel": [self.gosbi.pk, self.balance.pk], "fmt": ["feed", "story"], "ap": [self.gosbi.pk],
            "b_%d" % self.gosbi.pk: ["piel_pelaje", "articulaciones"],
            "h_%d" % self.gosbi.pk: h[self.gosbi.pk], "h_%d" % self.balance.pk: h[self.balance.pk]})
        self.assertEqual(r["Content-Type"], "application/zip")
        nombres = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        self.assertEqual(len(nombres), 2)
        self.assertTrue(any("Publicaciones_1080x1350/GOS-918" in n for n in nombres))
        self.assertTrue(any("Estados_1080x1920/GOS-918" in n for n in nombres))
        self.gosbi.refresh_from_db()
        self.assertEqual((self.gosbi.precio_venta, self.gosbi.stock_actual), (precio_antes, stock_antes))

    def test_si_cambio_el_precio_no_descarga(self):
        self.client.force_login(self.usuario)
        h = self._huellas(self.gosbi)
        Producto.objects.filter(pk=self.gosbi.pk).update(precio_venta=Decimal("23500"))
        r = self.client.post(reverse("catalogo:redes_alimentos"), {
            "sel": [self.gosbi.pk], "fmt": ["feed"], "ap": [self.gosbi.pk], "h_%d" % self.gosbi.pk: h[self.gosbi.pk]})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Desactualizada")
        self.assertFalse(r.context["tarjetas"][0]["aprobada"])

    def test_si_empezo_una_promocion_no_descarga(self):
        self.client.force_login(self.usuario)
        h = self._huellas(self.gosbi)
        hoy = timezone.localdate()
        promo = Promocion.objects.create(empresa=self.empresa, nombre="Noviembre", descuento_pct=10,
                                         inicio=hoy, fin=hoy + timedelta(days=5))
        PromocionProducto.objects.create(promocion=promo, producto=self.gosbi)
        activar(promo)
        r = self.client.post(reverse("catalogo:redes_alimentos"), {
            "sel": [self.gosbi.pk], "fmt": ["feed"], "ap": [self.gosbi.pk], "h_%d" % self.gosbi.pk: h[self.gosbi.pk]})
        self.assertContains(r, "Desactualizada")

    def test_sin_aprobar_no_descarga(self):
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("catalogo:redes_alimentos"), {"sel": [self.gosbi.pk], "fmt": ["feed"]})
        self.assertContains(r, "Aprobá al menos una")
