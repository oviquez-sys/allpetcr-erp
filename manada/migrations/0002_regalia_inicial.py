"""La regalía con la que arranca la manada: 10 % en la primera compra, un
solo uso por cliente (decisión de Oscar, 13/10/2026). Se crea acá para que
funcione desde el primer despliegue sin que nadie tenga que entrar al admin.
Después se cambia en Administración → Regalías de bienvenida."""
from decimal import Decimal

from django.db import migrations


def crear(apps, schema_editor):
    Empresa = apps.get_model("core", "Empresa")
    Regalia = apps.get_model("manada", "Regalia")
    for empresa in Empresa.objects.all():
        if not Regalia.objects.filter(empresa=empresa).exists():
            Regalia.objects.create(
                empresa=empresa, nombre="Bienvenida a la manada", porcentaje=Decimal("10"),
                texto_cliente="10 % de descuento en tu primera compra", dias_vigencia=0, activa=True,
            )


class Migration(migrations.Migration):
    dependencies = [("manada", "0001_initial")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
