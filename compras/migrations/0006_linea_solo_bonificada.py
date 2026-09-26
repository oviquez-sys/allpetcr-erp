# Una línea de compra puede traer solo unidades bonificadas (cantidad
# facturada 0). Ver el comentario en LineaCompra.Meta.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compras", "0005_iva_de_la_factura"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="lineacompra", name="cantidad_compra_positiva"),
        migrations.AddConstraint(
            model_name="lineacompra",
            constraint=models.CheckConstraint(
                condition=models.Q(cantidad__gte=0), name="cantidad_compra_no_negativa"
            ),
        ),
        migrations.AddConstraint(
            model_name="lineacompra",
            constraint=models.CheckConstraint(
                condition=models.Q(cantidad__gt=0) | models.Q(cantidad_bonificada__gt=0),
                name="linea_compra_con_unidades",
            ),
        ),
    ]
