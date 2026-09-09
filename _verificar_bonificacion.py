"""Comprueba contra la base REAL (no la de pruebas) que el campo de
bonificación quedó creado, y contra qué base de datos está hablando el ERP.

Se corre desde CORRER_PRUEBAS.bat / VERIFICAR.bat. No modifica nada.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection  # noqa: E402  (después de django.setup())
from django.db.migrations.recorder import MigrationRecorder  # noqa: E402

cfg = connection.settings_dict
print("Motor .............", cfg["ENGINE"])
print("Base de datos .....", cfg["NAME"])
print("Host ..............", cfg.get("HOST") or "(vacio)")
print()

aplicadas = sorted(
    n for a, n in MigrationRecorder(connection).applied_migrations() if a == "compras"
)
print("Migraciones de compras aplicadas:")
for m in aplicadas:
    print("   -", m)
print()

with connection.cursor() as cur:
    columnas = [c.name for c in connection.introspection.get_table_description(cur, "compras_lineacompra")]
print("Columnas reales de la tabla compras_lineacompra:")
for c in columnas:
    print("   -", c)
print()
print("RESULTADO: cantidad_bonificada existe en la base real:",
      "SI" if "cantidad_bonificada" in columnas else "NO")
