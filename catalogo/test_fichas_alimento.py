"""Fichas de alimento (26/09/2026): modelo, carga desde JSON y publicación en la API."""
import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from catalogo.management.commands.cargar_fichas_alimento import CARPETA, peso_de
from catalogo.models import FichaAlimento, Producto
from core.models import Empresa
from django.contrib.auth.models import User


def ficha_minima(**cambios):
    datos = {
        "clave": "prueba-adulto", "marca": "Marca", "nombre": "Adulto Pollo", "especie": "perro",
        "tipo": "seco", "etapas": ["adulto"], "beneficios": [{"clave": "digestion", "texto": "x"}],
        "analisis": [{"clave": "proteina", "calificador": "min", "valor": "26", "unidad": "%"}],
    }
    datos.update(cambios)
    return datos


class ModeloFicha(TestCase):
    def test_rechaza_claves_fuera_del_vocabulario(self):
        f = FichaAlimento(**ficha_minima(etapas=["adultos"], necesidades=["urinario"]))
        with self.assertRaises(ValidationError) as e:
            f.full_clean()
        self.assertIn("etapas", e.exception.message_dict)
        self.assertIn("necesidades", e.exception.message_dict)

    def test_verificada_exige_fuente_y_fecha(self):
        f = FichaAlimento(**ficha_minima(estado="verificado"))
        with self.assertRaises(ValidationError):
            f.full_clean()
        f.fuentes = [{"url": "https://fabricante.example", "tipo": "fabricante"}]
        f.verificado_en = "2026-09-26"
        f.full_clean()

    def test_peso_desde_la_presentacion(self):
        self.assertEqual(peso_de("12 lb"), (Decimal("12"), "lb"))
        self.assertEqual(peso_de("14.97 kg"), (Decimal("14.97"), "kg"))
        self.assertEqual(peso_de("Paquete: 3 / Caja: 6"), (None, ""))


class CargaDeFichas(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.bolsa = Producto.objects.create(
            empresa=self.empresa, sku="BEL-1", nombre="Adulto 12 lb", presentacion="12 lb",
            precio_venta=Decimal("21975"), stock_actual=Decimal("4"), codigo_barras="123",
        )
        self.carpeta = Path(tempfile.mkdtemp())
        (self.carpeta / "prueba-adulto.json").write_text(
            json.dumps(ficha_minima(skus=["BEL-1", "NO-EXISTE"])), encoding="utf-8")

    def cargar(self, *extra):
        salida = StringIO()
        call_command("cargar_fichas_alimento", "--carpeta", str(self.carpeta), *extra, stdout=salida)
        return salida.getvalue()

    def test_vincula_y_completa_el_peso_sin_tocar_precio_stock_ni_codigos(self):
        salida = self.cargar()
        self.bolsa.refresh_from_db()
        self.assertEqual(self.bolsa.ficha_alimento.clave, "prueba-adulto")
        self.assertEqual((self.bolsa.peso_valor, self.bolsa.peso_unidad), (Decimal("12.000"), "lb"))
        self.assertEqual(self.bolsa.precio_venta, Decimal("21975"))
        self.assertEqual(self.bolsa.stock_actual, Decimal("4"))
        self.assertEqual((self.bolsa.sku, self.bolsa.codigo_barras, self.bolsa.nombre), ("BEL-1", "123", "Adulto 12 lb"))
        self.assertIn("NO-EXISTE", salida)

    def test_simulacion_no_escribe(self):
        self.cargar("--dry-run")
        self.assertFalse(FichaAlimento.objects.exists())
        self.bolsa.refresh_from_db()
        self.assertIsNone(self.bolsa.ficha_alimento)

    def test_una_ficha_invalida_detiene_toda_la_carga(self):
        (self.carpeta / "zz-mala.json").write_text(json.dumps(ficha_minima(clave="mala", etapas=["x"])), encoding="utf-8")
        with self.assertRaises(CommandError):
            self.cargar()
        self.assertFalse(FichaAlimento.objects.exists())

    def test_volver_a_cargar_actualiza_en_vez_de_duplicar(self):
        self.cargar()
        self.cargar()
        self.assertEqual(FichaAlimento.objects.count(), 1)


class FichasDelRepositorio(TestCase):
    """Las fichas reales que se cargan en el servidor: todas deben pasar la
    validación del modelo, traer fuente con fecha si están verificadas y no
    repetir SKU entre fórmulas."""

    def test_todas_las_fichas_son_validas(self):
        vistos = {}
        archivos = sorted(CARPETA.glob("*.json"))
        self.assertGreater(len(archivos), 0)
        for archivo in archivos:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
            ficha = FichaAlimento(**{k: (str(v) if isinstance(v, float) else v) for k, v in datos.items() if k != "skus"})
            try:
                ficha.full_clean()
            except ValidationError as e:
                self.fail(f"{archivo.name}: {e.message_dict}")
            # Formato único para los valores: punto decimal y sin separador de
            # miles. NutriSource escribe "1,800" (mil ochocientos) y Gosbi
            # "8,5" (ocho coma cinco): guardados tal cual, la misma coma
            # significaría cosas distintas según la marca.
            for n in datos.get("analisis", []):
                self.assertRegex(n["valor"], r"^\d+(\.\d+)?( millones| mil millones)?$", f"{archivo.name}: {n}")
            for fuente in datos.get("fuentes", []):
                self.assertTrue(fuente.get("url", "").startswith("https://"), archivo.name)
            for sku in datos.get("skus", []):
                self.assertNotIn(sku, vistos, f"{sku} está en {archivo.name} y en {vistos.get(sku)}")
                vistos[sku] = archivo.name


class LasFichasRealesSeGuardan(TestCase):
    """Validar no alcanza: full_clean() acepta None en un campo de texto con
    blank=True y la base después lo rechaza (pasó con 'aditivos' de Gosbi,
    26/09/2026). Esta prueba CARGA todas las fichas reales en una base."""

    def test_carga_completa_de_la_carpeta_real(self):
        salida = StringIO()
        call_command("cargar_fichas_alimento", stdout=salida)
        self.assertEqual(FichaAlimento.objects.count(), len(list(CARPETA.glob("*.json"))))


class ApiFicha(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.ficha = FichaAlimento.objects.create(**ficha_minima(
            estado="verificado", verificado_en="2026-09-26",
            fuentes=[{"url": "https://fabricante.example"}], notas_internas="secreto"))
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="BEL-1", nombre="Adulto", precio_venta=Decimal("1000"), ficha_alimento=self.ficha)
        token = Token.objects.create(user=User.objects.create_user("sitio-web"))
        self.cliente = APIClient()
        self.cliente.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def detalle(self):
        return self.cliente.get(reverse("api:catalogo_producto_detalle", args=["BEL-1"])).json()

    def test_el_detalle_trae_la_ficha_con_etiquetas_resueltas(self):
        ficha = self.detalle()["ficha_alimento"]
        self.assertEqual(ficha["etapas"], [{"clave": "adulto", "etiqueta": "Adulto"}])
        self.assertEqual(ficha["beneficios"][0]["etiqueta"], "Digestión saludable")
        self.assertEqual(ficha["analisis"][0], {"clave": "proteina", "etiqueta": "Proteína cruda",
                                                "calificador": "mín.", "valor": "26", "unidad": "%"})

    def test_no_publica_fuentes_notas_ni_estado(self):
        ficha = self.detalle()["ficha_alimento"]
        for campo in ("fuentes", "notas_internas", "estado", "verificado_en"):
            self.assertNotIn(campo, ficha)

    def test_ficha_sin_investigar_o_a_revisar_no_se_publica(self):
        for estado in ("sin_investigar", "revisar"):
            self.ficha.estado = estado
            self.ficha.save()
            self.assertIsNone(self.detalle()["ficha_alimento"])

    def test_la_lista_no_carga_la_ficha(self):
        lista = self.cliente.get(reverse("api:catalogo_productos")).json()
        self.assertNotIn("ficha_alimento", lista["results"][0] if lista.get("results") else {})
