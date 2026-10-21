"""Buscador "inteligente" (pedido de Oscar, 20/10/2026)."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.chat_tools import ejecutar_herramienta
from core.models import Empresa

from .models import Categoria, FichaAlimento, Producto
from .palabras_clave import coincide, etiquetas, filtrar


class BuscadorInteligenteTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        raiz = Categoria.objects.create(nombre="Alimento")
        self.seco = Categoria.objects.create(nombre="Alimento seco", padre=raiz)
        self.humedo = Categoria.objects.create(nombre="Alimento húmedo", padre=raiz)
        self.paseo = Categoria.objects.create(nombre="Paseo")
        self.peluches = Categoria.objects.create(nombre="Peluches")

    def _p(self, nombre, cat, mascota="", ficha=None, presentacion="", **kw):
        n = Producto.objects.count() + 1
        return Producto.objects.create(empresa=self.empresa, sku=f"T{n}", nombre=nombre, categoria=cat, mascota=mascota,
                                       ficha_alimento=ficha, presentacion=presentacion, precio_venta=Decimal("1000"),
                                       stock_actual=Decimal("5"), **kw)

    def _ficha(self, clave, especie, **kw):
        datos = dict(marca="M", nombre=clave, especie=especie, tipo="seco")
        datos.update(kw)
        return FichaAlimento.objects.create(clave=clave, **datos)

    def _busca(self, consulta):
        return [p.nombre for p in filtrar(Producto.objects.filter(empresa=self.empresa), consulta)]

    def test_comida_perro_cachorro_encuentra_puppy_y_cachorro(self):
        self._p("Balance Puppy 2 kg", self.seco, "Perro", self._ficha("bp", "perro", etapas=["cachorro"]), "2 kg")
        self._p("Special Care Cachorro 1 kg", self.seco, "Perro")
        self._p("Balance Adulto 2 kg", self.seco, "Perro", self._ficha("ba", "perro", etapas=["adulto"]))
        self._p("Balance Kitten Cat 2 kg", self.seco, "Gato", self._ficha("bk", "gato", etapas=["gatito"]))
        self._p("Peluche pato", self.peluches, "Perro")
        self.assertEqual(sorted(self._busca("comida para perro cachorro")),
                         ["Balance Puppy 2 kg", "Special Care Cachorro 1 kg"])
        self.assertEqual(self._busca("alimento gatito"), ["Balance Kitten Cat 2 kg"])
        self.assertEqual(sorted(self._busca("cachorros")), ["Balance Puppy 2 kg", "Special Care Cachorro 1 kg"])

    def test_ficha_da_castrado_tamano_y_tipo(self):
        f = self._ficha("st", "gato", etapas=["adulto"], tipo="humedo", necesidades=["esterilizado"], proteina_principal="Pollo")
        self._p("Gosbi Delicat Sterilized Chicken Loaf 70 g", self.humedo, "Gato", f)
        g = self._ficha("toy", "perro", etapas=["adulto"], tamanos_raza=["pequena"])
        self._p("First Choice Perro Adulto Toy & Small Breeds 2 kg", self.seco, "Perro", g)
        self.assertEqual(self._busca("comida húmeda gata castrada"), ["Gosbi Delicat Sterilized Chicken Loaf 70 g"])
        self.assertEqual(self._busca("comida perro raza pequeña"), ["First Choice Perro Adulto Toy & Small Breeds 2 kg"])
        self.assertEqual(self._busca("pollo gato"), ["Gosbi Delicat Sterilized Chicken Loaf 70 g"])

    def test_sin_falsos_parecidos(self):
        self._p("Zapatos de malla con velcro", Categoria.objects.create(nombre="Ropa y accesorios"), "Perro")
        self._p("Gosbi Fresko Cat Adult Tuna 70 g", self.humedo, "Gato")
        self.assertEqual(self._busca("pato"), [])
        self.assertEqual(self._busca("res"), [])
        # un atún es pescado, pero no salmón
        self.assertEqual(self._busca("pescado"), ["Gosbi Fresko Cat Adult Tuna 70 g"])
        self.assertEqual(self._busca("salmon"), [])

    def test_tallas_pesos_y_codigos(self):
        c = self._p("Collar Gotham Zee.Dog talla XS", self.paseo, "Perro", presentacion="Extra Small")
        self._p("Balance Ad Cat Chicken 10 kg", self.seco, "Gato", presentacion="10 kg")
        self.assertEqual(self._busca("collar pequeño"), ["Collar Gotham Zee.Dog talla XS"])
        self.assertEqual(self._busca("10kg"), ["Balance Ad Cat Chicken 10 kg"])
        self.assertEqual(self._busca(c.sku), ["Collar Gotham Zee.Dog talla XS"])

    def test_perro_y_gato_y_coincide_basico(self):
        p = self._p("Cama redonda acolchada", Categoria.objects.create(nombre="Camas"), "Perro y gato")
        self.assertTrue(coincide("cama gato", p.nombre, etiquetas(p)))
        self.assertTrue(coincide("cama perro", p.nombre, etiquetas(p)))
        self.assertTrue(coincide("", "x"))

    def test_chat_usa_el_mismo_buscador(self):
        self._p("Balance Puppy 2 kg", self.seco, "Perro", self._ficha("bp", "perro", etapas=["cachorro"]))
        gerente = User.objects.create_superuser("g", "g@x.com", "x")
        r = ejecutar_herramienta("buscar_producto", {"texto": "comida perro cachorro"}, usuario=gerente)
        self.assertEqual([x["nombre"] for x in r["productos"]], ["Balance Puppy 2 kg"])

    def test_api_y_pos_mandan_etiquetas(self):
        from ventas.views import _filas_pos
        from api.serializers import ProductoListaSerializer
        p = self._p("Balance Puppy 2 kg", self.seco, "Perro", self._ficha("bp", "perro", etapas=["cachorro"]))
        fila = _filas_pos(Producto.objects.filter(pk=p.pk))[0]
        self.assertIn("cachorro", fila["etiquetas"])
        self.assertIn("comida", ProductoListaSerializer(p).data["etiquetas"])
