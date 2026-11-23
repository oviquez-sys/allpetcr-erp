"""Reglas de las tareas: qué se ve cada día, cómo se marca y cómo se cuenta.

Las vistas no deciden nada de esto: lo piden acá. Así la pantalla, las
pruebas y cualquier resumen que venga después (el cierre de la semana)
cuentan exactamente igual.

Definiciones:
- **Hecha / No se hizo / Pendiente**: lo que alguien marcó. «No se hizo» es
  una respuesta, no un olvido: sirve para separar lo que se decidió no hacer
  de lo que nadie miró.
- **Quedaron pendientes**: tareas puntuales (no de rutina) de días
  anteriores que siguen sin marcar, de los últimos 30 días. La rutina no
  entra: mañana vuelve a aparecer, y amontonar diez «responder mensajes» de
  días pasados taparía lo que de verdad quedó sin hacer.
- **Filtro por persona**: lo de esa persona más lo de «los dos».
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import Dia, Plan, Responsable, Rutina, Semana, Tarea

logger = logging.getLogger(__name__)

# Hasta cuántos días hacia adelante se crean las tareas de rutina al mirar el
# futuro: alcanza para ver un plan de un mes completo sin fabricar tareas
# para fechas a las que nadie llega.
HORIZONTE_DIAS = 45
# Cuántos días atrás se buscan las tareas que quedaron sin marcar.
VENTANA_PENDIENTES = 30

PERSONAS = (Responsable.OSCAR, Responsable.FRANCISCO)


def hoy():
    return timezone.localdate()


def persona_valida(valor):
    """El filtro de la pantalla: «OSC», «FRA» o vacío (todos)."""
    return valor if valor in PERSONAS else ""


def filtrar_persona(queryset, persona):
    if persona in PERSONAS:
        return queryset.filter(responsable__in=[persona, Responsable.LOS_DOS])
    return queryset


def plan_de(empresa, fecha):
    """El plan activo que cubre esa fecha (el más reciente si hay dos)."""
    return (Plan.objects.filter(empresa=empresa, activo=True, inicio__lte=fecha, fin__gte=fecha)
            .order_by("-inicio", "-id").first())


def dias_del_plan(empresa, desde, hasta):
    """{fecha: Dia} de los planes activos en ese rango."""
    dias = {}
    for dia in (Dia.objects.filter(plan__empresa=empresa, plan__activo=True, fecha__range=(desde, hasta))
                .select_related("plan").order_by("fecha", "-plan__inicio")):
        dias.setdefault(dia.fecha, dia)
    return dias


def semana_de(empresa, fecha):
    return (Semana.objects.filter(plan__empresa=empresa, plan__activo=True, inicio__lte=fecha, fin__gte=fecha)
            .select_related("plan").order_by("-plan__inicio").first())


def _detalle_de_rutina(rutina, dia):
    detalle = rutina.detalle.strip()
    if rutina.con_historias and dia is not None and dia.historias.strip():
        tema = dia.historias.strip()
        cierre = "" if tema[-1] in ".!?…»" else "."
        detalle = f"{detalle} Hoy: {tema}{cierre}".strip()
    return detalle


def asegurar_rutinas(empresa, desde, hasta):
    """Crea, una sola vez, las tareas de rutina de cada día del rango.

    Se llama antes de mostrar o contar días: así el conteo de una semana es
    el mismo la abra quien la abra, aunque nadie haya mirado esos días.

    No crea nada: en un día de tienda cerrada, para una rutina que ese día del
    plan no aplica, fuera de la vigencia de la rutina, ni más allá de
    HORIZONTE_DIAS. Dos personas abriendo el mismo día a la vez no duplican:
    lo impide la restricción única (rutina, fecha) y `ignore_conflicts`.
    Devuelve cuántas tareas intentó crear.
    """
    hasta = min(hasta, hoy() + timedelta(days=HORIZONTE_DIAS))
    if desde > hasta:
        return 0
    rutinas = list(Rutina.objects.filter(empresa=empresa, activa=True))
    if not rutinas:
        return 0
    dias = dias_del_plan(empresa, desde, hasta)
    existentes = set(
        Tarea.objects.filter(empresa=empresa, rutina__in=rutinas, fecha__range=(desde, hasta))
        .values_list("rutina_id", "fecha")
    )
    nuevas = []
    fecha = desde
    while fecha <= hasta:
        dia = dias.get(fecha)
        if not (dia is not None and dia.tienda_cerrada):
            omitir = set(dia.sin_rutinas or []) if dia is not None else set()
            for rutina in rutinas:
                if str(fecha.weekday()) not in rutina.dias:
                    continue
                if fecha < rutina.desde or (rutina.hasta and fecha > rutina.hasta):
                    continue
                if rutina.clave in omitir or (rutina.id, fecha) in existentes:
                    continue
                nuevas.append(Tarea(
                    empresa=empresa, plan=dia.plan if dia is not None else None, rutina=rutina,
                    fecha=fecha, orden=rutina.orden, hora=rutina.hora, titulo=rutina.titulo,
                    detalle=_detalle_de_rutina(rutina, dia), responsable=rutina.responsable,
                    tipo=Tarea.Tipo.RUTINA, minimo=rutina.minimo,
                ))
        fecha += timedelta(days=1)
    if nuevas:
        Tarea.objects.bulk_create(nuevas, ignore_conflicts=True)
    return len(nuevas)


def refrescar_rutina(rutina):
    """Al cambiar una rutina en el admin, sus tareas de hoy en adelante que
    nadie marcó toman el texto nuevo. Lo pasado y lo ya marcado no se toca:
    es historia de lo que se pidió ese día."""
    pendientes = Tarea.objects.filter(rutina=rutina, fecha__gte=hoy(), estado=Tarea.Estado.PENDIENTE)
    if not rutina.activa:
        return pendientes.delete()[0]
    actualizadas = 0
    dias = dias_del_plan(rutina.empresa, hoy(), hoy() + timedelta(days=HORIZONTE_DIAS))
    for tarea in pendientes:
        tarea.orden, tarea.hora, tarea.titulo = rutina.orden, rutina.hora, rutina.titulo
        tarea.detalle = _detalle_de_rutina(rutina, dias.get(tarea.fecha))
        tarea.responsable, tarea.minimo = rutina.responsable, rutina.minimo
        tarea.save(update_fields=["orden", "hora", "titulo", "detalle", "responsable", "minimo", "actualizada_en"])
        actualizadas += 1
    return actualizadas


def marcar(tarea, estado, usuario):
    """Marca la tarea. Quién y cuándo los pone el sistema, no la pantalla."""
    if estado not in Tarea.Estado.values:
        raise ValueError(f"Estado desconocido: {estado!r}")
    tarea.estado = estado
    if estado == Tarea.Estado.PENDIENTE:
        tarea.marcada_por, tarea.marcada_en = None, None
    else:
        tarea.marcada_por, tarea.marcada_en = usuario, timezone.now()
    tarea.save(update_fields=["estado", "marcada_por", "marcada_en", "actualizada_en"])
    return tarea


def conteo(tareas):
    """{total, hechas, no} de una lista ya filtrada."""
    r = {"total": 0, "hechas": 0, "no": 0}
    for t in tareas:
        r["total"] += 1
        if t.estado == Tarea.Estado.HECHA:
            r["hechas"] += 1
        elif t.estado == Tarea.Estado.NO_SE_HIZO:
            r["no"] += 1
    return r


def conteo_por_dia(empresa, desde, hasta, persona=""):
    """{fecha: {total, hechas, no}} en una sola consulta."""
    qs = filtrar_persona(Tarea.objects.filter(empresa=empresa, fecha__range=(desde, hasta)), persona)
    resultado = defaultdict(lambda: {"total": 0, "hechas": 0, "no": 0})
    for fila in qs.values("fecha", "estado").annotate(n=Count("id")):
        c = resultado[fila["fecha"]]
        c["total"] += fila["n"]
        if fila["estado"] == Tarea.Estado.HECHA:
            c["hechas"] += fila["n"]
        elif fila["estado"] == Tarea.Estado.NO_SE_HIZO:
            c["no"] += fila["n"]
    return resultado


def pendientes_anteriores(empresa, fecha, persona=""):
    qs = (Tarea.objects.filter(empresa=empresa, rutina__isnull=True, fecha__lt=fecha,
                               fecha__gte=fecha - timedelta(days=VENTANA_PENDIENTES),
                               estado=Tarea.Estado.PENDIENTE)
          .exclude(tipo=Tarea.Tipo.RUTINA))
    return filtrar_persona(qs, persona).select_related("marcada_por").order_by("fecha", "orden", "id")


def rango_de_la_franja(empresa, fecha):
    """Los días que muestra la franja de arriba: el plan que cubre la fecha
    o, si no hay, de lunes a domingo de esa semana y la siguiente."""
    plan = plan_de(empresa, fecha)
    if plan is not None:
        return plan.inicio, plan.fin, plan
    lunes = fecha - timedelta(days=fecha.weekday())
    return lunes, lunes + timedelta(days=13), None


def nombre_de(usuario, quien_mira=None):
    if usuario is None:
        return ""
    if quien_mira is not None and usuario.pk == quien_mira.pk:
        return "vos"
    return usuario.get_short_name() or usuario.get_username()
