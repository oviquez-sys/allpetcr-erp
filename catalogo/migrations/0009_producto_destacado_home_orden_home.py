from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0008_producto_etiqueta_impresa_en"),
    ]

    operations = [
        migrations.AddField(
            model_name="producto",
            name="destacado_home",
            field=models.BooleanField(
                default=False,
                help_text="Aparece primero en «La vitrina» de la portada del sitio, "
                          "en el lugar que diga 'Orden en home'.",
            ),
        ),
        migrations.AddField(
            model_name="producto",
            name="orden_home",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                help_text="Lugar dentro de «La vitrina». Menor sale primero. Solo se "
                          "usa si «Destacado en home» está marcado.",
            ),
        ),
        migrations.AddConstraint(
            model_name="producto",
            constraint=models.UniqueConstraint(
                condition=models.Q(destacado_home=True),
                fields=("empresa", "orden_home"),
                name="orden_home_unico_por_empresa",
                violation_error_message="Ya hay otro producto destacado en ese mismo lugar de la vitrina.",
            ),
        ),
    ]
