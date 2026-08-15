"""Endurece permisos de PostgreSQL sobre kardex/libro contable/documentos de
negocio (FRA-001, auditoría 2026-08-15). Complementa a endurecer_auditlog
(FRA-002), que hace lo mismo para core_auditlog exclusivamente.

Dos grupos, verificados leyendo cada services.py (no asumidos) — Y
verificando además qué otras tablas apuntan a cada una con FK, que resultó
igual de importante que si la app la edita (ver nota sobre contabilidad_
asiento más abajo, descubierta probando esto antes de aplicarlo):

  GRUPO_APPEND_ONLY — nunca se editan tras crearse, y ninguna otra tabla
  tiene una FK apuntando a ellas (confirmado: ninguna línea de código las
  toca con `.save()` después del `.create()` inicial, y
  `grep ForeignKey(...)` en todo el repo no encuentra ninguna FK hacia
  ellas). Reciben REVOKE UPDATE, DELETE:
    - inventario_movimientoinventario (kardex)
    - caja_movimientocaja
    - contabilidad_lineaasiento (evidencia propia, distinta de asiento:
      contabilidad/services.py:209 — solo .create(); las otras dos
      referencias, contabilidad/views.py:36,114, son SELECT de reportes)
    - ventas_abono (si ya tiene abonos, cancelar_cxc_por_anulacion
      BLOQUEA la anulación en vez de tocar el abono — ventas/cxc.py:97-101)

  GRUPO_DOCUMENTOS — no toleran REVOKE UPDATE sin romper funcionalidad
  real, por dos motivos distintos. Reciben solo REVOKE DELETE:
    - ventas_facturaventa, ventas_devolucionventa, ventas_documentocxc,
      compras_compra, caja_sesioncaja: cambian de estado con el tiempo
      (anulación, recepción, abonos, cierre de caja) — la app misma las
      edita con `.save()`.
    - contabilidad_asiento: la app NUNCA la edita (confirmado, igual que
      el grupo de arriba) — pero SÍ tiene una FK apuntando a ella
      (`LineaAsiento.asiento`, contabilidad/models.py:120), y PostgreSQL
      exige privilegio UPDATE (o DELETE/TRUNCATE) sobre la tabla
      REFERENCIADA para el lock `FOR KEY SHARE` que corre en cada INSERT
      de una fila que la referencia — sin importar que la app nunca la
      edite. Se confirmó probando: con UPDATE revocado, CADA venta se
      rompe al crear su LineaAsiento (asentar_venta), porque eso inserta
      una fila que referencia un Asiento recién creado. Ninguna otra
      tabla de este comando tiene este problema (verificado: ningún
      `ForeignKey(...)` del repo apunta a inventario_movimientoinventario,
      caja_movimientocaja, contabilidad_lineaasiento ni ventas_abono).

ADVERTENCIA IMPORTANTE, documentada a propósito: REVOKE DELETE sin UPDATE
es protección PARCIAL. Un UPDATE por SQL directo o QuerySet.update() (que
no dispara las señales de auditoría, ver core/signals.py) puede vaciar los
montos de un documento sin borrar la fila — por ejemplo
`UPDATE ventas_facturaventa SET total=0 WHERE id=X` — sin dejar rastro en
AuditLog y sin que este REVOKE lo impida. Cerrar ESE hueco necesitaría
volver estas tablas append-only de verdad (nunca editar, solo crear
documentos de reversa) — cambio de diseño más grande, fuera de alcance de
este REVOKE. Lo que este comando sí logra: nadie puede borrar la fila
completa (ocultar que la venta/compra/sesión existió), que era la mitad
más grave del hallazgo original.

Mismo límite que FRA-002 (ver endurecer_auditlog.py): si el rol de la app
es SUPERUSUARIO, el REVOKE no sirve de nada (se aborta). Si es dueño de
las tablas (caso típico, las creó al migrar), el REVOKE es real pero
reversible por ese mismo rol (GRANT de vuelta) — sube el costo de
manipular estos datos, no lo vuelve imposible.

Uso:
    python manage.py endurecer_documentos                # solo muestra el estado
    python manage.py endurecer_documentos --confirmar     # aplica los REVOKE
"""
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

GRUPO_APPEND_ONLY = {
    "inventario_movimientoinventario": ("UPDATE", "DELETE"),
    "caja_movimientocaja": ("UPDATE", "DELETE"),
    "contabilidad_lineaasiento": ("UPDATE", "DELETE"),
    "ventas_abono": ("UPDATE", "DELETE"),
}
GRUPO_DOCUMENTOS = {
    "ventas_facturaventa": ("DELETE",),
    "ventas_devolucionventa": ("DELETE",),
    "ventas_documentocxc": ("DELETE",),
    "compras_compra": ("DELETE",),
    "caja_sesioncaja": ("DELETE",),
    # No la edita la app — pierde UPDATE por LineaAsiento.asiento (FK):
    # ver docstring del módulo.
    "contabilidad_asiento": ("DELETE",),
}


class Command(BaseCommand):
    help = "Revoca UPDATE/DELETE (kardex y libro contable) y DELETE (documentos) según FRA-001. Solo PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Aplica los REVOKE de verdad. Sin esto, solo muestra el estado actual.",
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
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rol_app):
            raise CommandError(f"Nombre de rol inesperado: {rol_app!r}. No se ejecuta nada por seguridad.")

        with connection.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            fila = cur.fetchone()
            if fila and fila[0]:
                raise CommandError(
                    f"El rol '{rol_app}' con el que conecta la app es SUPERUSUARIO de "
                    "PostgreSQL: un REVOKE no tiene ningún efecto. No se aplicó nada."
                )

            self.stdout.write("Grupo append-only (REVOKE UPDATE, DELETE):")
            for tabla, privilegios in GRUPO_APPEND_ONLY.items():
                self._procesar_tabla(cur, rol_app, tabla, privilegios, opts["confirmar"])

            self.stdout.write("\nGrupo documentos (REVOKE DELETE — ver advertencia de protección parcial abajo):")
            for tabla, privilegios in GRUPO_DOCUMENTOS.items():
                self._procesar_tabla(cur, rol_app, tabla, privilegios, opts["confirmar"])

        self.stdout.write(self.style.WARNING(
            "\nAdvertencia (documentada en el docstring de este comando): sobre el "
            "grupo documentos, REVOKE DELETE es protección PARCIAL. Un UPDATE por SQL "
            "directo o QuerySet.update() puede vaciar los montos de un documento sin "
            "borrar la fila, sin dejar rastro en AuditLog y sin que este REVOKE lo "
            "impida. Este comando cierra el borrado de filas, no la manipulación de "
            "montos por UPDATE en las tablas del grupo documentos."
        ))

        if not opts["confirmar"]:
            self.stdout.write("\n[SIMULACIÓN] No se cambió nada. Repetí con --confirmar para aplicar los REVOKE.")

    def _procesar_tabla(self, cur, rol_app, tabla, privilegios, confirmar):
        cur.execute("SELECT tableowner FROM pg_tables WHERE tablename = %s", [tabla])
        fila = cur.fetchone()
        if fila is None:
            self.stdout.write(self.style.WARNING(f"  {tabla}: no existe, se salta."))
            return
        if fila[0] == rol_app:
            self.stdout.write(f"  {tabla}: '{rol_app}' es dueño (REVOKE real pero reversible por ese rol).")

        privilegios_sql = ", ".join(privilegios)
        if confirmar:
            cur.execute(f"REVOKE {privilegios_sql} ON {tabla} FROM {rol_app}")

        cur.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = %s AND grantee = %s ORDER BY privilege_type",
            [tabla, rol_app],
        )
        actuales = [f[0] for f in cur.fetchall()]
        estado = "aplicado" if confirmar else "ANTES"
        self.stdout.write(f"  {tabla} [{estado}]: {', '.join(actuales)}")
