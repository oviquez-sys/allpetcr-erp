"""Crea los grupos de rol (Gerente, Cajero, Contador) si no existen."""
from django.db import migrations


def crear_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nombre in ("Gerente", "Cajero", "Contador"):
        Group.objects.get_or_create(name=nombre)


def borrar_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["Gerente", "Cajero", "Contador"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_auditlog_ip"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(crear_roles, borrar_roles),
    ]
