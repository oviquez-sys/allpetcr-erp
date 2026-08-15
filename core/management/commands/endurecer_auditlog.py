"""Revoca UPDATE/DELETE sobre core_auditlog al rol con el que conecta la app
(FRA-002, auditoría 2026-08-15).

Solo PostgreSQL: SQLite no tiene permisos por rol (toda la seguridad de
archivo es del sistema operativo, fuera del alcance de este comando).

Verificación previa, obligatoria (no se aplica nada si falla):
  - Si el rol de la app es SUPERUSUARIO de PostgreSQL, un REVOKE no hace
    nada — los superusuarios se saltan todos los permisos. El comando
    aborta sin tocar nada y lo explica.

Límite conocido, documentado a propósito (no es un error, es matemática de
permisos de PostgreSQL): el rol de la app es DUEÑO de core_auditlog (lo creó
al correr las migraciones). Un dueño, aunque no sea superusuario, siempre
puede volver a otorgarse permisos sobre lo que le pertenece
(GRANT ON core_auditlog TO <mismo_rol>) y siempre conserva DROP/ALTER TABLE,
que no son parte del sistema de permisos que REVOKE controla. Este comando
sube el costo de editar/borrar la bitácora por SQL directo o manage.py shell
—deja de ser gratis y silencioso, exige un GRANT deliberado antes— pero no
la vuelve imposible para quien administra la base. Blindaje completo
requeriría que core_auditlog fuera propiedad de un rol DISTINTO del que usa
la app (fuera de alcance de este cambio: afecta cómo corren las migraciones).

Uso:
    python manage.py endurecer_auditlog                # solo verifica, no cambia nada
    python manage.py endurecer_auditlog --confirmar     # aplica el REVOKE
"""
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

_TABLA = "core_auditlog"


class Command(BaseCommand):
    help = "Revoca UPDATE/DELETE sobre core_auditlog al rol de la app (FRA-002). Solo PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Aplica el REVOKE de verdad. Sin esto, solo muestra el estado actual.",
        )

    def handle(self, *args, **opts):
        engine = settings.DATABASES["default"]["ENGINE"]
        if "postgresql" not in engine:
            self.stdout.write(self.style.WARNING(
                f"Motor actual: {engine}. Este endurecimiento es solo para PostgreSQL "
                "— SQLite no tiene permisos por rol. No hay nada que hacer."
            ))
            return

        rol_app = settings.DATABASES["default"].get("USER") or ""
        # Nombre de rol viene de la propia configuración (POSTGRES_USER), no
        # de una petición externa — igual se valida antes de interpolarlo en
        # SQL de permisos, que no admite parámetros como una consulta normal.
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rol_app):
            raise CommandError(f"Nombre de rol inesperado: {rol_app!r}. No se ejecuta nada por seguridad.")

        with connection.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            fila = cur.fetchone()
            if fila and fila[0]:
                raise CommandError(
                    f"El rol '{rol_app}' con el que conecta la app es SUPERUSUARIO de "
                    "PostgreSQL: un REVOKE no tiene ningún efecto (los superusuarios se "
                    "saltan todos los permisos). No se aplicó nada. Separá el rol de la "
                    "app de cualquier rol con superusuario antes de que este control sirva."
                )

            cur.execute("SELECT tableowner FROM pg_tables WHERE tablename = %s", [_TABLA])
            fila = cur.fetchone()
            propietario = fila[0] if fila else None
            if propietario == rol_app:
                self.stdout.write(self.style.WARNING(
                    f"Aviso: '{rol_app}' es DUEÑO de {_TABLA}. El REVOKE sí se aplica y "
                    "sí bloquea UPDATE/DELETE normales, pero un dueño siempre puede "
                    "volver a otorgarse el permiso (GRANT) o hacer DROP/ALTER TABLE, que "
                    "no pasan por este control. Ver el docstring de este comando."
                ))

            self._mostrar_permisos(cur, rol_app, "Estado ANTES")

            if not opts["confirmar"]:
                self.stdout.write(
                    "\n[SIMULACIÓN] No se cambió nada. Repetí con --confirmar para aplicar el REVOKE."
                )
                return

            cur.execute(f"REVOKE UPDATE, DELETE ON {_TABLA} FROM {rol_app}")
            self.stdout.write(self.style.SUCCESS(f"\nREVOKE UPDATE, DELETE ON {_TABLA} FROM {rol_app} — aplicado."))
            self._mostrar_permisos(cur, rol_app, "Estado DESPUÉS")

    def _mostrar_permisos(self, cur, rol_app, titulo):
        cur.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = %s AND grantee = %s ORDER BY privilege_type",
            [_TABLA, rol_app],
        )
        privilegios = [f[0] for f in cur.fetchall()]
        self.stdout.write(f"{titulo} — permisos de '{rol_app}' sobre {_TABLA}: {', '.join(privilegios)}")
