# Bonificación del proveedor ("12+1", "100+20"): las unidades regaladas se
# guardan aparte de las facturadas. Las compras que ya existen quedan en 0,
# que es exactamente lo que eran: compras sin bonificación.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compras", "0003_compra_compra_recibida_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="lineacompra",
            name="cantidad_bonificada",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=12,
                help_text="Unidades que el proveedor regala y no factura (el +1 de un 12+1).",
                verbose_name="cantidad bonificada",
            ),
        ),
        migrations.AlterField(
            model_name="lineacompra",
            name="cantidad",
            field=models.DecimalField(
                decimal_places=2, max_digits=12,
                help_text="Unidades facturadas por el proveedor",
            ),
        ),
        migrations.AlterField(
            model_name="lineacompra",
            name="costo_unitario",
            field=models.DecimalField(
                decimal_places=2, max_digits=12, help_text="Costo facturado por unidad",
            ),
        ),
        migrations.AlterField(
            model_name="lineacompra",
            name="total",
            field=models.DecimalField(
                decimal_places=2, max_digits=12,
                help_text="Lo que cobra la factura: cantidad × costo_unitario",
            ),
        ),
        migrations.AddConstraint(
            model_name="lineacompra",
            constraint=models.CheckConstraint(
                condition=models.Q(cantidad_bonificada__gte=0), name="bonificada_no_negativa"
            ),
        ),
    ]
