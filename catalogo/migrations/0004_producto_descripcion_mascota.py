"""Descripción pública y especie destino del producto.

Los trae el inventario del 02/08/2026 (data/INVENTARIO_ALLPETCR.xlsx), que
por primera vez tiene texto de venta y clasificación por especie para los 532
productos. Sin estos dos campos el sitio web no puede mostrar una ficha de
producto de verdad ni navegar por Perros / Gatos.

Ambos van vacíos por defecto: la migración no toca ningún dato existente. Los
llena `manage.py sincronizar_inventario`.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0003_cambioprecio"),
    ]

    operations = [
        migrations.AddField(
            model_name="producto",
            name="descripcion",
            field=models.TextField(
                blank=True,
                help_text="Descripción pública del producto (la publica el sitio web)",
            ),
        ),
        migrations.AddField(
            model_name="producto",
            name="mascota",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=30,
                help_text="Especie destino: Perro, Gato, Perro y gato, Peces, Tortugas, Otros",
            ),
        ),
    ]
