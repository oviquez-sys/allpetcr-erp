"""Que el texto de la regalía diga la condición nueva (05/11/2026).

Solo cambia el texto de las regalías (lo que ven los que se registren desde
hoy). Los cupones ya entregados guardaron su propio texto al emitirse y no se
tocan: se respetan como se ofrecieron.
"""
from django.db import migrations, models


def agregar_condicion(apps, schema_editor):
    Regalia = apps.get_model("manada", "Regalia")
    for r in Regalia.objects.filter(excluye_alimentos=True):
        if "aliment" not in r.texto_cliente.lower():
            texto = f"{r.texto_cliente.strip()} (no aplica a alimentos)"
            if len(texto) <= 160:
                r.texto_cliente = texto
                r.save(update_fields=["texto_cliente"])


class Migration(migrations.Migration):
    dependencies = [("manada", "0006_cupon_sin_alimentos")]
    operations = [
        migrations.AlterField(
            model_name="regalia", name="texto_cliente",
            field=models.CharField(
                default="10 % de descuento en tu primera compra (no aplica a alimentos)",
                help_text="Así aparece en la página y en el correo. Debe coincidir con el porcentaje.",
                max_length=160, verbose_name="texto que ve el cliente"),
        ),
        migrations.RunPython(agregar_condicion, migrations.RunPython.noop),
    ]
