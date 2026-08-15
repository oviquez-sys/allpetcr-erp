"""Pruebas del sistema de respaldo/restauración (Sprint G).

El comando respalda el ARCHIVO de base de datos SQLite, no la conexión ORM.
Como el runner de tests corre con SQLite en memoria, aquí probamos la mecánica
contra un archivo SQLite temporal real (creado a mano), apuntando la
configuración a él con override_settings. Así validamos fielmente:
respaldo consistente, inclusión de fotos, rotación y ciclo respaldar→restaurar.
"""
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


def _crear_db(path: Path, valor: str):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE IF NOT EXISTS marca (dato TEXT)")
    con.execute("DELETE FROM marca")
    con.execute("INSERT INTO marca (dato) VALUES (?)", (valor,))
    con.commit()
    con.close()


def _leer_db(path: Path) -> str:
    con = sqlite3.connect(str(path))
    fila = con.execute("SELECT dato FROM marca").fetchone()
    con.close()
    return fila[0] if fila else None


class RespaldoBase(SimpleTestCase):
    """SimpleTestCase: no tocamos el ORM, solo archivos."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.db = self.raiz / "db.sqlite3"
        self.media = self.raiz / "media"
        self.resp = self.raiz / "respaldos"
        self.media.mkdir()
        _crear_db(self.db, "ORIGINAL")
        self._ctx = override_settings(
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(self.db)}},
            MEDIA_ROOT=str(self.media),
        )
        self._ctx.enable()

    def tearDown(self):
        self._ctx.disable()
        self._tmp.cleanup()

    def _respaldar(self, **kw):
        call_command("respaldar", destino=str(self.resp), verbosity=0, **kw)


class RespaldoTest(RespaldoBase):
    def test_crea_zip_con_base_y_marca(self):
        self._respaldar()
        zips = list(self.resp.glob("respaldo_allpetcr_*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as z:
            self.assertIn("db.sqlite3", z.namelist())
            self.assertIn("RESPALDO.txt", z.namelist())

    def test_incluye_fotos_de_media(self):
        (self.media / "foto.txt").write_text("foto falsa")
        self._respaldar()
        z = zipfile.ZipFile(next(self.resp.glob("*.zip")))
        self.assertIn("media/foto.txt", z.namelist())

    def test_snapshot_es_una_base_valida(self):
        self._respaldar()
        with tempfile.TemporaryDirectory() as t:
            with zipfile.ZipFile(next(self.resp.glob("*.zip"))) as z:
                z.extract("db.sqlite3", t)
            self.assertEqual(_leer_db(Path(t) / "db.sqlite3"), "ORIGINAL")

    def test_rotacion_conserva_solo_los_ultimos(self):
        import os
        import time
        self.resp.mkdir(parents=True, exist_ok=True)
        for i in range(4):
            f = self.resp / f"respaldo_allpetcr_2026010{i}_000000.zip"
            with zipfile.ZipFile(f, "w") as z:
                z.writestr("db.sqlite3", "x")
            os.utime(f, (time.time() + i, time.time() + i))
        self._respaldar(conservar=2)
        self.assertEqual(len(list(self.resp.glob("respaldo_allpetcr_*.zip"))), 2)

    def test_ciclo_respaldar_restaurar_recupera_datos(self):
        self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name
        # "Daño" del archivo real.
        _crear_db(self.db, "DAÑADO")
        self.assertEqual(_leer_db(self.db), "DAÑADO")
        # Restauro.
        call_command("restaurar", archivo=zip_name, destino=str(self.resp),
                     confirmar=True, verbosity=0)
        self.assertEqual(_leer_db(self.db), "ORIGINAL")

    def test_restaurar_guarda_copia_previa(self):
        self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name
        _crear_db(self.db, "ESTADO_ACTUAL")
        call_command("restaurar", archivo=zip_name, destino=str(self.resp),
                     confirmar=True, verbosity=0)
        previas = list(self.resp.glob("antes_de_restaurar_*"))
        self.assertTrue(previas, "Debe guardar copia del estado previo antes de restaurar")
        self.assertEqual(_leer_db(previas[0] / "db.sqlite3"), "ESTADO_ACTUAL")

    def test_restaurar_sin_confirmar_no_toca_nada(self):
        self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name
        _crear_db(self.db, "SIN_TOCAR")
        call_command("restaurar", archivo=zip_name, destino=str(self.resp), verbosity=0)
        self.assertEqual(_leer_db(self.db), "SIN_TOCAR")


_VARS_B2 = {
    "B2_BUCKET": "allpetcr-respaldos-prueba",
    "B2_KEY_ID": "keyid-de-prueba",
    "B2_APPLICATION_KEY": "applicationkey-de-prueba",
    "B2_ENDPOINT": "s3.us-west-004.backblazeb2.com",
}


class RespaldoB2Test(RespaldoBase):
    """FRA-005: el envío a B2 nunca debe tocar la red real en un test —
    se mockea boto3.client por completo. Lo que se prueba es que el
    comando arma la llamada correcta y que el respaldo local no depende
    de que B2 funcione."""

    def test_sin_variables_b2_no_llama_a_boto3(self):
        with mock.patch("core.management.commands.respaldar.boto3.client") as cliente_mock:
            self._respaldar()
        cliente_mock.assert_not_called()

    def test_con_variables_b2_sube_el_zip_correcto(self):
        with mock.patch.dict(os.environ, _VARS_B2), \
             mock.patch("core.management.commands.respaldar.boto3.client") as cliente_mock:
            self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name

        cliente_mock.assert_called_once_with(
            "s3",
            endpoint_url="https://s3.us-west-004.backblazeb2.com",
            aws_access_key_id="keyid-de-prueba",
            aws_secret_access_key="applicationkey-de-prueba",
        )
        cliente_mock.return_value.upload_file.assert_called_once()
        args, _ = cliente_mock.return_value.upload_file.call_args
        self.assertTrue(args[0].endswith(zip_name))
        self.assertEqual(args[1], "allpetcr-respaldos-prueba")
        self.assertEqual(args[2], zip_name)

    def test_fallo_de_subida_no_pierde_el_respaldo_local(self):
        with mock.patch.dict(os.environ, _VARS_B2), \
             mock.patch("core.management.commands.respaldar.boto3.client") as cliente_mock:
            cliente_mock.return_value.upload_file.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denegado"}}, "PutObject"
            )
            with self.assertRaises(CommandError):
                self._respaldar()

        # El zip local ya se había creado y rotado ANTES de intentar subir
        # a B2 — un fallo de red/credenciales no debe perderlo.
        zips = list(self.resp.glob("respaldo_allpetcr_*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as z:
            self.assertIn("db.sqlite3", z.namelist())
