"""Pruebas de los hallazgos de seguridad de la auditoría 2026-07-28.

Cubre SEG-03 (cabeceras CSP y Permissions-Policy), SEG-05 (falsificación de
IP en la auditoría) y SEG-08 (expiración de sesión).

Por qué estas pruebas y no otras: cada una fija un comportamiento que hoy es
correcto pero que se rompe con un cambio de una línea en settings o en el
middleware, sin que nadie lo note hasta que sea tarde. Una regla que no se
verifica automáticamente se rompe en tres meses.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings

from core.middleware import ip_de_la_peticion


class CabecerasDeSeguridadTest(TestCase):
    """SEG-03 — la respuesta debe traer CSP y Permissions-Policy."""

    def setUp(self):
        self.client = Client()

    def test_permissions_policy_presente(self):
        r = self.client.get("/admin/login/")
        self.assertIn("Permissions-Policy", r.headers)
        self.assertIn("camera=()", r.headers["Permissions-Policy"])

    def test_csp_bloquea_lo_que_no_rompe_nada(self):
        """Las directivas seguras van en bloqueo desde ya."""
        r = self.client.get("/admin/login/")
        csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        self.assertIn("form-action 'self'", csp)

    def test_csp_completa_va_en_modo_reporte(self):
        """El resto se observa sin bloquear, para no tumbar el POS."""
        r = self.client.get("/admin/login/")
        reporte = r.headers.get("Content-Security-Policy-Report-Only", "")
        self.assertIn("default-src 'self'", reporte)
        self.assertIn("script-src", reporte)

    @override_settings(CSP_ESTRICTA=True)
    def test_modo_estricto_manda_todo_en_bloqueo(self):
        """Con DJANGO_CSP_ESTRICTA=1 no debe quedar cabecera de solo reporte."""
        r = Client().get("/admin/login/")
        self.assertIn("default-src 'self'", r.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("Content-Security-Policy-Report-Only", r.headers)


class IpDeAuditoriaTest(TestCase):
    """SEG-05 — la IP del AuditLog no debe ser falsificable por el cliente."""

    def setUp(self):
        self.rf = RequestFactory()

    def test_ignora_x_forwarded_for_sin_proxy_declarado(self):
        """Sin proxies de confianza configurados, la cabecera no vale nada."""
        req = self.rf.get("/", HTTP_X_FORWARDED_FOR="8.8.8.8", REMOTE_ADDR="10.0.0.5")
        self.assertEqual(ip_de_la_peticion(req), "10.0.0.5")

    @override_settings(PROXIES_CONFIABLES=("127.0.0.1",))
    def test_ignora_x_forwarded_for_de_origen_no_confiable(self):
        """La petición no viene del proxy conocido: se usa REMOTE_ADDR."""
        req = self.rf.get("/", HTTP_X_FORWARDED_FOR="8.8.8.8", REMOTE_ADDR="203.0.113.9")
        self.assertEqual(ip_de_la_peticion(req), "203.0.113.9")

    @override_settings(PROXIES_CONFIABLES=("127.0.0.1",))
    def test_toma_la_ultima_entrada_cuando_viene_del_proxy(self):
        """La primera entrada la puede inyectar el cliente; la última la anexa
        nuestro nginx. Por eso se lee de atrás hacia adelante."""
        req = self.rf.get(
            "/", HTTP_X_FORWARDED_FOR="8.8.8.8, 198.51.100.7", REMOTE_ADDR="127.0.0.1"
        )
        self.assertEqual(ip_de_la_peticion(req), "198.51.100.7")

    @override_settings(PROXIES_CONFIABLES=("127.0.0.1",))
    def test_sin_cabecera_usa_remote_addr(self):
        req = self.rf.get("/", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(ip_de_la_peticion(req), "127.0.0.1")


class ExpiracionDeSesionTest(TestCase):
    """SEG-08 — una sesión de POS no puede durar dos semanas."""

    def test_sesion_dura_una_jornada_no_dos_semanas(self):
        self.assertLessEqual(
            settings.SESSION_COOKIE_AGE,
            24 * 3600,
            "Una sesión de más de un día permite que el turno siguiente opere "
            "con la identidad del cajero anterior y rompe la trazabilidad.",
        )

    def test_la_sesion_se_renueva_con_la_actividad(self):
        """Si no, al cajero se le cierra la sesión a mitad de jornada aunque
        esté trabajando."""
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    def test_cookie_de_sesion_no_accesible_desde_javascript(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)


class FotoDeProductoTest(TestCase):
    """SEG-06 — no se acepta cualquier cosa que el cliente llame 'imagen'."""

    def test_rechaza_svg_disfrazado_de_imagen(self):
        """Un SVG puede llevar <script> dentro y MEDIA se sirve desde el mismo
        dominio del ERP: sería XSS almacenado."""
        from django.core.exceptions import ValidationError

        from compras.views import _validar_foto

        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with self.assertRaises(ValidationError):
            _validar_foto(svg)

    def test_rechaza_html(self):
        from django.core.exceptions import ValidationError

        from compras.views import _validar_foto

        with self.assertRaises(ValidationError):
            _validar_foto(b"<html><body>no soy una foto</body></html>")

    def test_rechaza_archivo_demasiado_grande(self):
        from django.core.exceptions import ValidationError

        from compras.views import TAMANO_MAX_FOTO, _validar_foto

        gigante = b"\x89PNG\r\n\x1a\n" + b"\x00" * (TAMANO_MAX_FOTO + 1)
        with self.assertRaises(ValidationError):
            _validar_foto(gigante)

    def test_acepta_png_real_y_deduce_la_extension_del_contenido(self):
        """La extensión sale de los bytes, no de lo que declare el navegador."""
        from compras.views import _extension_real

        # PNG mínimo válido (1x1 transparente).
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
        self.assertEqual(_extension_real(png), ".png")

    def test_acepta_jpeg_real(self):
        from compras.views import _extension_real

        self.assertEqual(_extension_real(b"\xff\xd8\xff\xe0" + b"\x00" * 20), ".jpg")

    def test_acepta_webp_real(self):
        from compras.views import _extension_real

        self.assertEqual(_extension_real(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8), ".webp")


class EscapeEnPlantillasTest(TestCase):
    """SEG-02 — el JavaScript del POS y de compras debe escapar antes de
    insertar datos en el DOM.

    Es una prueba de código fuente, no de comportamiento: no puedo ejecutar el
    navegador desde la suite. Lo que fija es que nadie vuelva a interpolar
    `${p.nombre}` sin pasar por esc(), que es exactamente como apareció el
    fallo la primera vez.
    """

    PLANTILLAS = ["templates/ventas/pos.html", "templates/compras/nueva.html"]

    def _leer(self, ruta):
        return (settings.BASE_DIR / ruta).read_text(encoding="utf-8")

    def test_las_plantillas_definen_esc(self):
        for ruta in self.PLANTILLAS:
            with self.subTest(plantilla=ruta):
                self.assertIn("const esc =", self._leer(ruta))

    def test_no_hay_interpolacion_cruda_de_datos_de_producto(self):
        """Ningún dato de producto puede interpolarse sin esc() en una cadena
        que termine en innerHTML.

        Se excluyen las líneas que llaman a msg(): ese helper escribe con
        textContent, que no interpreta HTML, así que ahí la interpolación es
        segura — y aplicarle esc() mostraría "&lt;" literal al usuario, que
        sería un error visual. Que msg use textContent lo fija la prueba
        test_los_avisos_usan_textcontent de esta misma clase; si alguien lo
        devuelve a innerHTML, esa prueba falla.
        """
        crudos = ["${p.nombre}", "${p.categoria}", "${p.presentacion}", "${p.imagen}"]
        for ruta in self.PLANTILLAS:
            lineas = [ln for ln in self._leer(ruta).splitlines() if "msg(" not in ln]
            contenido = "\n".join(lineas)
            for patron in crudos:
                with self.subTest(plantilla=ruta, patron=patron):
                    self.assertNotIn(
                        patron,
                        contenido,
                        f"{ruta} interpola {patron} sin escapar. Usá esc() o escUrl().",
                    )

    def test_los_avisos_usan_textcontent(self):
        """msg() recibe nombres de producto y errores del servidor."""
        for ruta in self.PLANTILLAS:
            with self.subTest(plantilla=ruta):
                self.assertIn("m.textContent=t", self._leer(ruta))
