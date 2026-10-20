"""Asistente: alimentos por necesidad según la ficha técnica (20/10/2026)."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.chat_tools import ejecutar_herramienta, herramientas_para, skus_mencionados
from core.models import Empresa

from .models import Categoria, FichaAlimento, Producto
from .recomendar import buscar, interpretar


class RecomendarAlimentoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.cat = Categoria.objects.create(nombre="Alimento seco")

    def _ficha(self, clave, especie, **kw):
        datos = dict(marca="Marca", nombre=clave, especie=especie, tipo="seco", etapas=["adulto"])
        datos.update(kw)
        return FichaAlimento.objects.create(clave=clave, **datos)

    def _producto(self, sku, ficha=None, stock=5, **kw):
        datos = dict(nombre=f"Producto {sku}", categoria=self.cat, presentacion="2 kg",
                     precio_venta=Decimal("10000"), stock_actual=Decimal(stock), ficha_alimento=ficha)
        datos.update(kw)
        return Producto.objects.create(empresa=self.empresa, sku=sku, **datos)

    def test_bolas_de_pelo_solo_si_el_fabricante_lo_declara(self):
        declara = self._ficha("hairball", "gato", beneficios=[{"clave": "bolas_pelo", "texto": "Fibra para eliminar el pelo."}])
        con_fibra = self._ficha("fibra", "gato", descripcion="Rica en fibra.")
        self._producto("H1", declara)
        self._producto("F1", con_fibra)
        r = buscar(self.empresa, especie="gato", necesidad="mi gato vomita bolas de pelo")
        self.assertEqual([o["ficha"]["nombre"] for o in r["opciones"]], ["hairball"])
        self.assertIn("beneficio declarado: Control de bolas de pelo", r["opciones"][0]["coincide_por"])
        p = r["opciones"][0]["presentaciones"][0]
        self.assertEqual((p["sku"], p["precio_por_kilo"]), ("H1", 5000))
        self.assertEqual(skus_mencionados(r), ["H1"])

    def test_sin_coincidencias_no_rellena_y_ofrece_la_pasta_de_malta(self):
        self._producto("F1", self._ficha("fibra", "gato", descripcion="Rica en fibra."))
        self._producto("MALTA", None, nombre="Tabergat Malta 100 g", mascota="Gato", presentacion="100 g")
        r = buscar(self.empresa, especie="gato", necesidad="bolas de pelo")
        self.assertEqual(r["opciones"], [])
        self.assertEqual([o["sku"] for o in r["otros_productos"]], ["MALTA"])

    def test_solo_lo_que_hay_en_existencia_y_de_la_especie(self):
        castrado = dict(necesidades=["esterilizado"])
        self._producto("SIN", self._ficha("agotado", "gato", **castrado), stock=0)
        self._producto("PER", self._ficha("perro", "perro", **castrado))
        self._producto("SI", self._ficha("gato-ok", "gato", **castrado))
        r = buscar(self.empresa, especie="gato", necesidad="está castrado")
        self.assertEqual([o["ficha"]["nombre"] for o in r["opciones"]], ["gato-ok"])
        r = buscar(self.empresa, especie="gato", necesidad="castrado", solo_en_existencia=False)
        self.assertEqual({o["ficha"]["nombre"] for o in r["opciones"]}, {"agotado", "gato-ok"})

    def test_ingrediente_dice_en_que_lugar_esta(self):
        self._producto("S1", self._ficha("aceite", "perro", ingredientes="Pollo, arroz, maíz, aceite de salmón"))
        self._producto("S2", self._ficha("salmon", "perro", proteina_principal="Salmón", ingredientes="Salmón, papa"))
        r = buscar(self.empresa, especie="perro", texto="salmón")
        self.assertEqual(r["opciones"][0]["ficha"]["nombre"], "salmon")
        self.assertIn("proteína principal: Salmón", r["opciones"][0]["coincide_por"])
        self.assertIn("ingrediente n.º 4 de la lista: «aceite de salmón»", r["opciones"][1]["coincide_por"])

    def test_interpretar_no_confunde_palabras_parecidas(self):
        self.assertIn("piel_sensible", interpretar("se rasca y le pica")[0])
        self.assertNotIn("piel_sensible", interpretar("una comida típica")[0])
        self.assertIn("urinaria", interpretar("tiene cristales en la orina")[0])

    def test_herramientas_por_rol(self):
        cajero = User.objects.create_user("c", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        nombres = {t["name"] for t in herramientas_para(cajero)}
        self.assertIn("buscar_alimento", nombres)
        self.assertNotIn("lo_vendido", nombres)
        self.assertIn("error", ejecutar_herramienta("lo_vendido", {}, usuario=cajero))
        gerente = User.objects.create_superuser("g", "g@x.com", "x")
        r = ejecutar_herramienta("lo_vendido", {"solo_reponer": True}, usuario=gerente)
        self.assertEqual(r["productos_vendidos"], 0)
        r = ejecutar_herramienta("buscar_alimento", {"especie": "gato", "necesidad": "bolas de pelo"}, usuario=cajero)
        self.assertIn("opciones", r)


class AlimentosSinFichaTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        raiz = Categoria.objects.create(nombre="Alimento")
        self.seco = Categoria.objects.create(nombre="Alimento seco", padre=raiz)
        self.otra = Categoria.objects.create(nombre="Juguetes")
        self.ficha = FichaAlimento.objects.create(clave="f", marca="M", nombre="F", especie="gato", tipo="seco", estado="parcial",
                                                  notas_internas="Falta el análisis.")

    def _p(self, sku, cat, ficha=None, **kw):
        return Producto.objects.create(empresa=self.empresa, sku=sku, nombre=sku, categoria=cat, ficha_alimento=ficha,
                                       precio_venta=Decimal("1000"), stock_actual=Decimal("3"), **kw)

    def test_lista_solo_alimentos_activos_sin_ficha(self):
        from .recomendar import alimentos_sin_ficha, fichas_incompletas
        self._p("SIN", self.seco, mascota="Gato")
        self._p("CON", self.seco, self.ficha)
        self._p("JUG", self.otra)
        self._p("INACTIVO", self.seco, activo=False)
        self._p("PERRO", self.seco, mascota="Perro")
        self.assertEqual([p.sku for p in alimentos_sin_ficha(self.empresa)], ["PERRO", "SIN"])
        self.assertEqual([p.sku for p in alimentos_sin_ficha(self.empresa, especie="gato")], ["SIN"])
        self.assertEqual([f.clave for f in fichas_incompletas(self.empresa)], ["f"])
        r = buscar(self.empresa, especie="gato", necesidad="castrado")
        self.assertEqual(r["alimentos_sin_ficha"]["cantidad"], 1)

    def test_pantalla(self):
        self._p("SIN", self.seco)
        self._p("CON", self.seco, self.ficha)
        gerente = User.objects.create_superuser("g", "g@x.com", "x")
        self.client.force_login(gerente)
        from django.urls import reverse
        r = self.client.get(reverse("catalogo:sin_ficha"))
        self.assertContains(r, "SKU SIN")
        self.assertContains(r, "Falta el análisis.")
