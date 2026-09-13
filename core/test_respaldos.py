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

    def test_sin_ningun_destino_configurado_no_llama_a_boto3(self):
        with _sin_destinos_en_la_nube(), \
             mock.patch("core.management.commands.respaldar.boto3.client") as cliente_mock:
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


_VARS_SPACES = {
    "AWS_STORAGE_BUCKET_NAME": "allpetcr-fotos-prueba",
    "AWS_S3_ENDPOINT_URL": "https://nyc3.digitaloceanspaces.com",
    "AWS_S3_REGION_NAME": "nyc3",
    "AWS_ACCESS_KEY_ID": "llave-de-prueba",
    "AWS_SECRET_ACCESS_KEY": "secreto-de-prueba",
}

# Las variables de los dos destinos pueden estar puestas en la máquina donde
# corren las pruebas (la de Oscar tiene las de Spaces en el entorno). Quitarlas
# explícitamente es lo que hace que estas pruebas den lo mismo acá, en el
# servidor y en la computadora de la tienda.
def _sin_destinos_en_la_nube():
    from core.management.commands.respaldar import _VARIABLES_B2, _VARIABLES_SPACES

    return mock.patch.dict(
        os.environ,
        {v: "" for v in (*_VARIABLES_B2, *_VARIABLES_SPACES, "DJANGO_PRODUCTION")},
    )


class RespaldoALaNubeTest(RespaldoBase):
    """El respaldo del SERVIDOR (12/09/2026).

    El ERP dejó de correr en la tienda: corre en un contenedor que se borra
    entero en cada despliegue. Un respaldo que solo queda en ese disco no
    existe. Estas pruebas cuidan las tres reglas de esa decisión."""

    def test_manda_la_copia_al_bucket_con_permiso_privado(self):
        """En ese bucket las fotos son públicas. Si el zip saliera con el mismo
        permiso, ventas, clientes y contabilidad quedarían en internet."""
        with _sin_destinos_en_la_nube(), mock.patch.dict(os.environ, _VARS_SPACES), \
             mock.patch("core.management.commands.respaldar.boto3.client") as cliente_mock:
            cliente_mock.return_value.list_objects_v2.return_value = {"Contents": []}
            self._respaldar()

        zip_name = next(self.resp.glob("*.zip")).name
        subir = cliente_mock.return_value.upload_file
        subir.assert_called_once()
        args, kwargs = subir.call_args
        self.assertEqual(args[1], "allpetcr-fotos-prueba")
        self.assertEqual(args[2], "respaldos/" + zip_name)
        self.assertEqual(kwargs["ExtraArgs"]["ACL"], "private")

    def test_b2_manda_y_el_bucket_no(self):
        """Con los dos configurados gana B2: es el único destino que ni un
        administrador del servidor puede borrar."""
        with _sin_destinos_en_la_nube(), \
             mock.patch.dict(os.environ, {**_VARS_SPACES, **_VARS_B2}), \
             mock.patch("core.management.commands.respaldar.boto3.client") as cliente_mock:
            self._respaldar()

        args, kwargs = cliente_mock.return_value.upload_file.call_args
        self.assertEqual(args[1], "allpetcr-respaldos-prueba")
        self.assertNotIn("ExtraArgs", kwargs)

    def test_borra_las_copias_viejas_del_bucket(self):
        """Sin rotación la carpeta crece todos los días para siempre."""
        viejos = [{"Key": f"respaldos/respaldo_allpetcr_2026090{i}_000000.zip",
                   "LastModified": i} for i in range(1, 6)]
        with _sin_destinos_en_la_nube(), mock.patch.dict(os.environ, _VARS_SPACES), \
             mock.patch("core.management.commands.respaldar.boto3.client") as cliente_mock:
            cliente_mock.return_value.list_objects_v2.return_value = {"Contents": viejos}
            self._respaldar(conservar=2)

        borradas = [k["Key"] for _, k in
                    [(c.args, c.kwargs) for c in
                     cliente_mock.return_value.delete_object.call_args_list]]
        self.assertEqual(len(borradas), 3)
        # Se borran los MÁS VIEJOS, nunca los recientes.
        self.assertIn("respaldos/respaldo_allpetcr_20260901_000000.zip", borradas)
        self.assertNotIn("respaldos/respaldo_allpetcr_20260905_000000.zip", borradas)

    def test_en_el_servidor_sin_destino_el_respaldo_falla(self):
        """La trampa que esto evita: la tarea programada diría "listo" todos los
        días mientras el archivo se borra con el siguiente despliegue. Mejor en
        rojo y a la vista."""
        with _sin_destinos_en_la_nube(), \
             mock.patch.dict(os.environ, {"DJANGO_PRODUCTION": "1"}):
            with self.assertRaises(CommandError):
                self._respaldar()

    def test_en_la_computadora_de_la_tienda_sin_destino_sigue_estando_bien(self):
        """Ahí el disco no se borra solo: el zip local ES el respaldo."""
        with _sin_destinos_en_la_nube():
            self._respaldar()
        self.assertEqual(len(list(self.resp.glob("*.zip"))), 1)
