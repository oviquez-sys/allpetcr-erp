"""El formato de moneda es el mismo lo dibuje el servidor o el navegador.

El defecto que fija esta prueba
-------------------------------
En el POS un arnés de ₡4000 se veía "₡4000" y uno de ₡12.500 sí llevaba punto.
No era un bug del código sino de la suposición: `toLocaleString('es-ES')` NO
agrupa los miles hasta los cinco dígitos, porque el español de España define
`minimumGroupingDigits = 2` en el CLDR. El servidor, en cambio, siempre agrupó
desde los cuatro dígitos.

O sea que el MISMO producto se veía distinto según qué pantalla lo dibujara.

Se prueba de dos maneras, y ninguna sobra:

1. El filtro `crc` del servidor, con casos numéricos concretos — incluido el de
   cuatro dígitos, que era el que fallaba del otro lado.
2. Que ninguna plantilla vuelva a formatear moneda con `toLocaleString`. Esta
   es una prueba SOBRE EL CÓDIGO FUENTE, no sobre el comportamiento: no
   ejecuta JavaScript y no puede afirmar qué ve el cajero en pantalla. Sirve
   para que el atajo no reaparezca dentro de seis meses, que es exactamente
   como apareció la primera vez.
"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from core.templatetags.formato import crc, crc_abs


class FiltroCRC(TestCase):

    def test_agrupa_desde_cuatro_digitos(self):
        """El caso exacto que se veía mal en el POS."""
        self.assertEqual(crc(4000), "4.000")
        self.assertEqual(crc(3300), "3.300")
        self.assertEqual(crc(1300), "1.300")

    def test_no_agrupa_lo_que_no_llega_a_mil(self):
        self.assertEqual(crc(900), "900")
        self.assertEqual(crc(0), "0")

    def test_grupos_grandes(self):
        self.assertEqual(crc(12500), "12.500")
        self.assertEqual(crc(184350), "184.350")
        self.assertEqual(crc(1000000), "1.000.000")

    def test_decimales_con_coma(self):
        self.assertEqual(crc(Decimal("1234567.89"), 2), "1.234.567,89")

    def test_redondea_a_la_mitad_par(self):
        """Comportamiento heredado, documentado para que no sorprenda.

        El filtro usa el formateo de Python, que redondea "a la mitad par"
        (38,25 → 38,2 y 38,35 → 38,4) en vez de "siempre para arriba". Es sólo
        formato de PANTALLA: los montos guardados no pasan por acá.

        No se cambia a propósito. Pasar a redondeo hacia arriba movería un
        colón en cifras que ya se vienen mostrando y leyendo, y ganaría muy
        poco: la diferencia aparece únicamente en el empate exacto.
        """
        self.assertEqual(crc(Decimal("38.25"), 1), "38,2")
        self.assertEqual(crc(Decimal("38.35"), 1), "38,4")

    def test_negativos_conservan_el_signo(self):
        self.assertEqual(crc(-5000), "-5.000")

    def test_crc_abs_saca_el_signo(self):
        """Los egresos de caja se guardan negativos y el signo se dibuja
        aparte, con su color. Sin este filtro salía «−₡-500»."""
        self.assertEqual(crc_abs(-5000), "5.000")
        self.assertEqual(crc_abs(5000), "5.000")

    def test_no_revienta_con_basura(self):
        self.assertEqual(crc(None), "")
        self.assertEqual(crc(""), "")
        self.assertEqual(crc("hola"), "hola")


class NingunaPlantillaFormateaMonedaPorSuCuenta(TestCase):
    """Guardia contra la reaparición del atajo.

    LÍMITE DE ESTA PRUEBA: lee archivos, no ejecuta JavaScript. Que pase no
    demuestra que el cajero vea "₡4.000" — demuestra que nadie volvió a usar
    la función que producía "₡4000". Comprobar lo primero exige abrir el POS
    en un navegador de verdad.
    """

    @staticmethod
    def _plantillas():
        raiz = Path(settings.BASE_DIR) / "templates"
        return list(raiz.rglob("*.html"))

    def test_ninguna_plantilla_usa_toLocaleString(self):
        culpables = []
        for archivo in self._plantillas():
            texto = archivo.read_text(encoding="utf-8")
            # Se ignoran los comentarios de plantilla, que SÍ nombran la
            # función para explicar por qué no se usa.
            sin_comentarios = re.sub(
                r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", texto, flags=re.S
            )
            if "toLocaleString" in sin_comentarios:
                culpables.append(str(archivo.relative_to(settings.BASE_DIR)))

        self.assertEqual(
            culpables, [],
            "Estas plantillas formatean números con toLocaleString. En español "
            "de España eso NO agrupa los miles hasta los cinco dígitos (₡4000 "
            "pero ₡12.500). Usá fmt() de static/js/formato.js: "
            + ", ".join(culpables),
        )

    def test_el_ayudante_de_formato_existe_y_lo_cargan_las_pantallas_que_lo_usan(self):
        ayudante = Path(settings.BASE_DIR) / "static" / "js" / "formato.js"
        self.assertTrue(ayudante.exists(), "falta static/js/formato.js")

        for ruta in ("ventas/pos.html", "compras/nueva.html", "core/dashboard.html"):
            archivo = Path(settings.BASE_DIR) / "templates" / ruta
            texto = archivo.read_text(encoding="utf-8")
            with self.subTest(plantilla=ruta):
                self.assertIn(
                    "js/formato.js", texto,
                    f"{ruta} usa fmt() pero no carga el ayudante que lo define",
                )
