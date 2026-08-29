"""core/imagenes.py: punto único de lectura/escritura de fotos de producto,
para que el backend de almacenamiento (disco local o S3-compatible) se
pueda cambiar solo con configuración. Bloque 1, 2026-08-28."""
import tempfile

from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from .imagenes import guardar_imagen_producto, url_imagen_producto


class GuardarImagenProducto(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Aísla los archivos de esta prueba del media/ real del proyecto.
        self.override = override_settings(MEDIA_ROOT=self._tmp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_guarda_y_la_ruta_es_relativa_a_productos(self):
        ruta = guardar_imagen_producto("ABC-1.png", b"contenido-falso")
        self.assertEqual(ruta, "productos/ABC-1.png")
        self.assertTrue(default_storage.exists(ruta))
        with default_storage.open(ruta, "rb") as f:
            self.assertEqual(f.read(), b"contenido-falso")

    def test_guardar_dos_veces_sobrescribe_no_duplica(self):
        guardar_imagen_producto("ABC-2.png", b"version-vieja")
        ruta = guardar_imagen_producto("ABC-2.png", b"version-nueva")
        self.assertEqual(ruta, "productos/ABC-2.png")  # mismo nombre, no "ABC-2_xyz.png"
        with default_storage.open(ruta, "rb") as f:
            self.assertEqual(f.read(), b"version-nueva")


class UrlImagenProducto(TestCase):
    def test_ruta_vacia_da_url_vacia(self):
        self.assertEqual(url_imagen_producto(""), "")

    def test_ruta_con_valor_da_una_url(self):
        # Con el backend local (por defecto en pruebas), la URL cuelga de
        # MEDIA_URL — el mismo resultado que antes tenía el código a mano.
        self.assertEqual(url_imagen_producto("productos/x.png"), "/media/productos/x.png")
