# Orden de exhibición de las categorías, compartido por el ERP y el sitio.
# Todo lo existente queda en 100 (el valor por defecto), o sea alfabético como
# hasta ahora; el comando `asegurar_categorias` reparte los números reales.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0005_producto_cabys_producto_marca_producto_peso_unidad_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="categoria",
            name="orden",
            field=models.PositiveSmallIntegerField(
                default=100,
                help_text="Posición en los menús del ERP y del sitio. Menor sale primero.",
            ),
        ),
        migrations.AlterModelOptions(
            name="categoria",
            options={"ordering": ["orden", "nombre"], "verbose_name_plural": "categorías"},
        ),
    ]
