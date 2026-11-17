"""Deja «Navidad AllPet 2026» creada en BORRADOR, lista para revisar y activar.

Oscar decidió el 17/11/2026 los dos puntos abiertos de las bases (quién no
participa y la publicación del nombre de quien gane) y pidió que quede lista
para activar, sin activarla. Esta migración:

- si la campaña no existe, la crea en borrador con la plantilla de
  `campanas/plantillas.py` (bases sin ningún «[POR DEFINIR]»);
- si ya existe en borrador con un «[POR DEFINIR]» en las bases (alguien tocó
  «Preparar Navidad» antes de esta fecha), le pone las bases nuevas;
- si ya existe y está activa o más allá, o sus bases ya se corrigieron a
  mano, no la toca: lo que el cliente ya aceptó no se cambia por detrás.

En una base vacía (las de las pruebas, una instalación nueva) no hay
empresa y no hace nada.

Nunca la activa: activar es una decisión de Oscar, desde la pantalla.
"""
from django.db import migrations


def preparar(apps, schema_editor):
    from campanas.plantillas import bases_borrador, navidad_2026

    Empresa = apps.get_model("core", "Empresa")
    Campana = apps.get_model("campanas", "Campana")
    empresa = Empresa.objects.order_by("id").first()
    if empresa is None:
        return
    datos = navidad_2026(empresa)
    existente = Campana.objects.filter(empresa=empresa, slug=datos["slug"]).first()
    if existente is None:
        Campana.objects.create(empresa=empresa, estado="BOR", **datos)
    elif existente.estado == "BOR" and "[POR DEFINIR" in existente.bases:
        existente.bases = bases_borrador(empresa)
        existente.save(update_fields=["bases"])


class Migration(migrations.Migration):

    dependencies = [
        ("campanas", "0001_campanas_con_sorteo"),
    ]

    operations = [
        migrations.RunPython(preparar, migrations.RunPython.noop),
    ]
