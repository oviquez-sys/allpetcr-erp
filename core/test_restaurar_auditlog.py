"""Pruebas de FRA-003: `restaurar` no debe pisar core_auditlog de la base viva.

Mismo enfoque que test_respaldos.py: SimpleTestCase contra un archivo SQLite
temporal real (no el runner de tests, que usa la base de Postgres del
proyecto) — acá además se crea a mano una tabla core_auditlog con la forma
real del modelo (core/models.py:AuditLog), para poder probar la mecánica de
lectura/reescritura sin depender de las migraciones completas.
"""
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

_CREAR_AUDITLOG = """
CREATE TABLE core_auditlog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NULL,
    ip TEXT NULL,
    fecha TEXT NOT NULL,
    tabla VARCHAR(80) NOT NULL,
    objeto_id VARCHAR(40) NOT NULL,
    accion VARCHAR(10) NOT NULL,
    antes TEXT NULL,
    despues TEXT NULL
)
"""
_CREAR_USUARIOS = """
CREATE TABLE auth_user (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)
"""


def _crear_db(path: Path):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE IF NOT EXISTS marca (dato TEXT)")
    con.execute(_CREAR_USUARIOS)
    con.execute(_CREAR_AUDITLOG)
    con.execute("INSERT INTO auth_user (id, username) VALUES (1, 'oscar')")
    con.commit()
    con.close()


def _insertar_marca(path: Path, valor: str):
    con = sqlite3.connect(str(path))
    con.execute("DELETE FROM marca")
    con.execute("INSERT INTO marca (dato) VALUES (?)", (valor,))
    con.commit()
    con.close()


def _insertar_auditlog(path: Path, tabla, objeto_id, usuario_id=1):
    con = sqlite3.connect(str(path))
    con.execute(
        "INSERT INTO core_auditlog (usuario_id, ip, fecha, tabla, objeto_id, accion, antes, despues) "
        "VALUES (?, '127.0.0.1', '2026-08-15T10:00:00', ?, ?, 'crear', NULL, '{}')",
        (usuario_id, tabla, objeto_id),
    )
    con.commit()
    con.close()


def _leer_auditlog(path: Path):
    con = sqlite3.connect(str(path))
    filas = con.execute("SELECT usuario_id, tabla, objeto_id FROM core_auditlog ORDER BY id").fetchall()
    con.close()
    return filas


class RestaurarPreservaAuditLog(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.db = self.raiz / "db.sqlite3"
        self.media = self.raiz / "media"
        self.resp = self.raiz / "respaldos"
        self.media.mkdir()
        _crear_db(self.db)
        self._ctx = override_settings(
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(self.db)}},
            MEDIA_ROOT=str(self.media),
        )
        self._ctx.enable()

    def tearDown(self):
        self._ctx.disable()
        self._tmp.cleanup()

    def _respaldar(self):
        call_command("respaldar", destino=str(self.resp), verbosity=0)

    def _restaurar(self, zip_name):
        call_command("restaurar", archivo=zip_name, destino=str(self.resp), confirmar=True, verbosity=0)

    def test_registro_posterior_al_respaldo_sobrevive_la_restauracion(self):
        _insertar_marca(self.db, "ORIGINAL")
        _insertar_auditlog(self.db, "ventas.facturaventa", "1")
        self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name

        # Actividad DESPUÉS del respaldo: una venta nueva, y (el caso que
        # importa) alguien anulando una — exactamente lo que un restaurar
        # a un respaldo viejo borraría sin esta corrección.
        _insertar_marca(self.db, "DAÑADO")
        _insertar_auditlog(self.db, "ventas.facturaventa", "2")
        _insertar_auditlog(self.db, "ventas.facturaventa", "1")  # anulación de la #1, después del respaldo

        self._restaurar(zip_name)

        # El resto de la base SÍ vuelve al respaldo (comportamiento ya
        # existente, sin cambios).
        con = sqlite3.connect(str(self.db))
        self.assertEqual(con.execute("SELECT dato FROM marca").fetchone()[0], "ORIGINAL")
        con.close()

        # Pero la bitácora conserva TODO lo que tenía la base viva, no lo
        # que traía el zip (que solo tenía la fila objeto_id=1 original).
        filas = _leer_auditlog(self.db)
        self.assertEqual(len(filas), 3)
        self.assertEqual([f[2] for f in filas], ["1", "2", "1"])

    def test_usuario_inexistente_en_la_base_restaurada_queda_nulo(self):
        _insertar_marca(self.db, "ORIGINAL")
        self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name

        # Un usuario creado DESPUÉS del respaldo elegido genera actividad;
        # ese usuario no existe en la base que se está por restaurar.
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO auth_user (id, username) VALUES (99, 'nuevo_empleado')")
        con.commit()
        con.close()
        _insertar_auditlog(self.db, "ventas.facturaventa", "5", usuario_id=99)

        self._restaurar(zip_name)

        con = sqlite3.connect(str(self.db))
        fila = con.execute("SELECT usuario_id FROM core_auditlog WHERE objeto_id='5'").fetchone()
        con.close()
        self.assertIsNone(fila[0], "Un usuario que no existe en la base restaurada debe quedar NULL, no romper la restauración")

    def test_sin_tabla_auditlog_no_rompe_la_restauracion(self):
        # Mismo escenario que test_respaldos.py: una base sin core_auditlog
        # (instalación nueva, o de pruebas) — restaurar debe seguir
        # funcionando exactamente igual que antes de FRA-003.
        con = sqlite3.connect(str(self.db))
        con.execute("DROP TABLE core_auditlog")
        con.commit()
        con.close()
        _insertar_marca(self.db, "ORIGINAL")
        self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name
        _insertar_marca(self.db, "DAÑADO")

        self._restaurar(zip_name)  # no debe lanzar excepción

        con = sqlite3.connect(str(self.db))
        self.assertEqual(con.execute("SELECT dato FROM marca").fetchone()[0], "ORIGINAL")
        con.close()

    def test_respaldo_sin_actividad_posterior_no_pierde_nada(self):
        _insertar_marca(self.db, "ORIGINAL")
        _insertar_auditlog(self.db, "ventas.facturaventa", "1")
        self._respaldar()
        zip_name = next(self.resp.glob("*.zip")).name
        _insertar_marca(self.db, "DAÑADO")
        # Sin actividad nueva de auditoría entre el respaldo y la restauración.

        self._restaurar(zip_name)

        filas = _leer_auditlog(self.db)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0][2], "1")
