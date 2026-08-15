"""Pruebas de FRA-002: REVOKE UPDATE, DELETE sobre core_auditlog.

Corre contra la base de pruebas real (PostgreSQL, no SQLite en memoria —
este proyecto ya usa Postgres también para los tests, ver CLAUDE.md). Los
permisos de una tabla son propios de la base de datos en la que vive esa
tabla, así que tocar los permisos de la tabla test_allpetcr.core_auditlog
NO afecta a la base real de producción (misma tabla, distinta base).

No hace falta limpiar el REVOKE a mano al final: TestCase envuelve cada
prueba en una transacción que se revierte sola al terminar, y GRANT/REVOKE
en PostgreSQL es transaccional como cualquier otro cambio — el mismo
mecanismo de aislamiento del que ya dependen todas las demás pruebas.

Se salta entera si el motor no es PostgreSQL (por ejemplo, si alguien corre
los tests con SQLite): el hallazgo mismo no aplica ahí.
"""
from django.db import connection
from django.db.utils import ProgrammingError
from django.test import TestCase, skipUnlessDBFeature

from core.models import AuditLog


@skipUnlessDBFeature("supports_transactions")
class EndurecerAuditLogTest(TestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("FRA-002 (REVOKE de permisos) es solo para PostgreSQL.")
        # Estado conocido al empezar: por si una corrida anterior dejó el
        # REVOKE aplicado (no debería, por el aislamiento transaccional,
        # pero no cuesta nada partir de un estado explícito).
        with connection.cursor() as cur:
            cur.execute(f"GRANT UPDATE, DELETE ON core_auditlog TO {connection.settings_dict['USER']}")

    def _permisos_actuales(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'core_auditlog' AND grantee = current_user"
            )
            return {f[0] for f in cur.fetchall()}

    def test_sin_confirmar_no_cambia_nada(self):
        from django.core.management import call_command
        call_command("endurecer_auditlog", verbosity=0)
        self.assertIn("UPDATE", self._permisos_actuales())
        self.assertIn("DELETE", self._permisos_actuales())

    def test_confirmar_revoca_update_y_delete_pero_no_select_ni_insert(self):
        from django.core.management import call_command
        call_command("endurecer_auditlog", confirmar=True, verbosity=0)

        permisos = self._permisos_actuales()
        self.assertNotIn("UPDATE", permisos)
        self.assertNotIn("DELETE", permisos)
        self.assertIn("SELECT", permisos, "No debe tocar SELECT")
        self.assertIn("INSERT", permisos, "No debe tocar INSERT — el kardex de auditoría solo agrega filas")

    def test_postgres_realmente_rechaza_el_update_tras_el_revoke(self):
        from django.core.management import call_command
        from django.db import transaction

        call_command("endurecer_auditlog", confirmar=True, verbosity=0)
        log = AuditLog.objects.create(tabla="x.prueba", objeto_id="1", accion="crear")

        with self.assertRaises(ProgrammingError):
            # Savepoint propio: sin esto, el error de Postgres deja la
            # transacción de la prueba abortada para lo que venga después.
            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("UPDATE core_auditlog SET accion = 'editar' WHERE id = %s", [log.pk])

        # La prueba sigue viva gracias al savepoint: confirmar que el UPDATE
        # rechazado no cambió nada.
        log.refresh_from_db()
        self.assertEqual(log.accion, "crear")

    def test_sqlite_no_hace_nada(self):
        from django.core.management import call_command
        from django.test import override_settings

        with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}):
            call_command("endurecer_auditlog", confirmar=True, verbosity=0)  # no debe lanzar excepción
