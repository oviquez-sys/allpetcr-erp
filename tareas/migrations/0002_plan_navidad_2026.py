"""Carga el plan de mercadeo de Navidad 2026 (23/11/2026, pedido de Oscar).

Lo que crea: el plan, sus 5 semanas, sus 32 días con sus tareas puntuales y
la rutina de lunes a sábado vigente del 23/11 al 24/12. Las tareas de rutina
de cada día NO se crean acá: las crea la pantalla la primera vez que alguien
mira ese día (`tareas.servicios.asegurar_rutinas`).

Se puede correr de nuevo sin duplicar: todo se busca por su clave y lo que ya
existe no se toca (alguien pudo haberlo corregido desde el admin, o marcado).

En una base vacía (las de las pruebas, una instalación nueva) no hay empresa
y no hace nada.
"""
from datetime import date

from django.db import migrations


def _f(texto):
    return date.fromisoformat(texto) if texto else None


def cargar(apps, schema_editor):
    from tareas import plan_navidad_2026 as datos

    Empresa = apps.get_model("core", "Empresa")
    Plan = apps.get_model("tareas", "Plan")
    Semana = apps.get_model("tareas", "Semana")
    Dia = apps.get_model("tareas", "Dia")
    Rutina = apps.get_model("tareas", "Rutina")
    Tarea = apps.get_model("tareas", "Tarea")

    empresa = Empresa.objects.order_by("id").first()
    if empresa is None:
        return

    plan, _ = Plan.objects.get_or_create(
        empresa=empresa, clave=datos.CLAVE,
        defaults={"nombre": datos.NOMBRE, "inicio": _f(datos.INICIO), "fin": _f(datos.FIN),
                  "hito": datos.HITO, "hito_fecha": _f(datos.HITO_FECHA), "enlace": datos.ENLACE},
    )
    for s in datos.SEMANAS:
        Semana.objects.get_or_create(
            plan=plan, inicio=_f(s["inicio"]),
            defaults={"nombre": s["nombre"], "titulo": s["titulo"], "fin": _f(s["fin"]),
                      "objetivo": s["objetivo"], "meta": s["meta"], "anuncios": s["anuncios"], "nota": s["nota"]},
        )
    for r in datos.RUTINAS:
        Rutina.objects.get_or_create(
            empresa=empresa, clave=r["clave"],
            defaults={"orden": r["orden"], "hora": r["hora"], "titulo": r["titulo"], "detalle": r["detalle"],
                      "responsable": r["responsable"], "dias": r["dias"], "minimo": r["minimo"],
                      "con_historias": r["con_historias"], "desde": _f(datos.INICIO), "hasta": _f(datos.FIN)},
        )
    for d in datos.DIAS:
        fecha = _f(d["fecha"])
        Dia.objects.get_or_create(
            plan=plan, fecha=fecha,
            defaults={"etiqueta": d["etiqueta"], "historias": d["historias"], "claude": d["claude"],
                      "nota": d["nota"], "tienda_cerrada": d["tienda_cerrada"], "sin_rutinas": d["sin_rutinas"]},
        )
        for t in d["tareas"]:
            Tarea.objects.get_or_create(
                empresa=empresa, clave=t["clave"],
                defaults={"plan": plan, "fecha": fecha, "orden": t["orden"], "hora": t["hora"],
                          "titulo": t["titulo"], "detalle": t["detalle"], "responsable": t["responsable"],
                          "tipo": t["tipo"]},
            )


class Migration(migrations.Migration):

    dependencies = [
        ("tareas", "0001_tareas_del_dia"),
    ]

    operations = [
        migrations.RunPython(cargar, migrations.RunPython.noop),
    ]
