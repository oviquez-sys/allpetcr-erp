"""Pantalla de tareas del día (23/11/2026): ver lo de cada día, marcarlo y
dejar una nota. La usan el gerente y el cajero: las tareas son del trabajo de
la tienda, no de la contabilidad.

Marcar funciona con y sin JavaScript: el botón es un formulario normal que
vuelve a la misma tarea; `static/js/tareas.js` lo manda en segundo plano para
no recargar la página en cada toque. Si ese envío falla, el formulario se
manda igual de la forma normal, así nunca se pierde una marca.
"""
from datetime import date, timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import dateformat, timezone
from django.views.decorators.http import require_POST

from core.roles import CAJERO, GERENTE, es_gerente, rol_requerido
from core.tenancy import documento_de_empresa, empresa_actual

from . import servicios
from .models import Responsable, Tarea

ROLES = (GERENTE, CAJERO)


def _fecha(texto):
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _volver(fecha, persona="", tarea=None, abierta=False):
    url = reverse("tareas:dia") + f"?fecha={fecha:%Y-%m-%d}"
    if persona:
        url += f"&quien={persona}"
    if tarea is not None and abierta:
        url += f"&abierta={tarea.pk}"
    if tarea is not None:
        url += f"#t-{tarea.pk}"
    return url


def _cuando(tarea):
    """La hora en que se marcó; con el día si no fue el mismo día de la tarea."""
    if tarea.marcada_en is None:
        return ""
    local = timezone.localtime(tarea.marcada_en)
    formato = "g:i a" if local.date() == tarea.fecha else "D j/n, g:i a"
    return dateformat.format(local, formato)


def _relativo(fecha, hoy):
    n = (fecha - hoy).days
    if n == 0:
        return "Hoy"
    if n == -1:
        return "Ayer"
    if n == 1:
        return "Mañana"
    return f"Hace {-n} días" if n < 0 else f"En {n} días"


def _cuenta_regresiva(plan, hoy):
    if plan is None or not plan.hito or plan.hito_fecha is None:
        return ""
    n = (plan.hito_fecha - hoy).days
    if n > 1:
        return f"{plan.hito} en {n} días"
    if n == 1:
        return f"{plan.hito} mañana"
    if n == 0:
        return f"Hoy es el {plan.hito.lower()}"
    return ""


def _preparar(tareas, usuario):
    for t in tareas:
        t.quien_marco = servicios.nombre_de(t.marcada_por, usuario)
        t.cuando = _cuando(t)
    return tareas


def _porcentaje(parte, total):
    return round(parte * 100 / total) if total else 0


@rol_requerido(*ROLES)
def dia(request):
    empresa = empresa_actual(request)
    if empresa is None:
        return render(request, "tareas/dia.html", {"sin_empresa": True})

    hoy = servicios.hoy()
    fecha = _fecha(request.GET.get("fecha")) or hoy
    persona = servicios.persona_valida(request.GET.get("quien", ""))
    desde, hasta, plan = servicios.rango_de_la_franja(empresa, fecha)
    semana = servicios.semana_de(empresa, fecha)

    # Todo lo que esta pantalla cuenta (la franja y la semana) necesita su
    # rutina creada; si no, un día que nadie abrió contaría «0 de 0».
    inicio = min(desde, fecha, semana.inicio if semana else fecha)
    fin = max(hasta, fecha, semana.fin if semana else fecha)
    servicios.asegurar_rutinas(empresa, inicio, fin)

    tareas = _preparar(list(
        servicios.filtrar_persona(Tarea.objects.filter(empresa=empresa, fecha=fecha), persona)
        .select_related("marcada_por")
    ), request.user)
    del_dia = [t for t in tareas if not t.es_de_rutina]
    rutina = [t for t in tareas if t.es_de_rutina]
    total = servicios.conteo(tareas)

    conteos = servicios.conteo_por_dia(empresa, inicio, fin, persona)
    dias_plan = servicios.dias_del_plan(empresa, inicio, fin)
    dia_plan = dias_plan.get(fecha)

    franja = []
    d = desde
    while d <= hasta:
        c = conteos.get(d, {"total": 0, "hechas": 0, "no": 0})
        franja.append({
            "fecha": d, "hoy": d == hoy, "elegida": d == fecha,
            "cerrada": bool(dias_plan.get(d) and dias_plan[d].tienda_cerrada),
            "nuevo_mes": d == desde or d.day == 1,
            "pct": _porcentaje(c["hechas"], c["total"]), "hechas": c["hechas"], "total": c["total"],
        })
        d += timedelta(days=1)

    barras, en_semana = [], {"hechas": 0, "no": 0, "sin_marcar": 0}
    if semana is not None:
        d = semana.inicio
        while d <= semana.fin:
            c = conteos.get(d, {"total": 0, "hechas": 0, "no": 0})
            futuro = d > hoy
            if not futuro:
                en_semana["hechas"] += c["hechas"]
                en_semana["no"] += c["no"]
                en_semana["sin_marcar"] += c["total"] - c["hechas"] - c["no"]
            barras.append({"fecha": d, "futuro": futuro, "elegida": d == fecha, "total": c["total"],
                           "hechas": c["hechas"], "pct": _porcentaje(c["hechas"], c["total"])})
            d += timedelta(days=1)

    pendientes = []
    if fecha == hoy:
        pendientes = _preparar(list(servicios.pendientes_anteriores(empresa, hoy, persona)), request.user)

    try:
        abierta = int(request.GET.get("abierta", ""))
    except ValueError:
        abierta = None

    return render(request, "tareas/dia.html", {
        "hoy": hoy, "fecha": fecha, "relativo": _relativo(fecha, hoy),
        "anterior": fecha - timedelta(days=1), "siguiente": fecha + timedelta(days=1),
        "persona": persona, "personas": [(p.value, p.label) for p in servicios.PERSONAS],
        "responsables": Responsable.choices,
        "plan": plan, "semana": semana, "dia_plan": dia_plan,
        "cuenta_regresiva": _cuenta_regresiva(plan or servicios.plan_de(empresa, hoy), hoy),
        "del_dia": del_dia, "rutina": rutina, "total": total,
        "pct_hechas": _porcentaje(total["hechas"], total["total"]),
        "pct_no": _porcentaje(total["no"], total["total"]),
        "franja": franja, "barras": barras, "en_semana": en_semana,
        "pendientes": pendientes, "abierta": abierta,
        "es_gerente": es_gerente(request.user),
    })


@require_POST
@rol_requerido(*ROLES)
def marcar(request, pk):
    tarea = documento_de_empresa(Tarea, request, pk=pk)
    persona = servicios.persona_valida(request.POST.get("quien", ""))
    estado = request.POST.get("estado", "")
    en_segundo_plano = request.headers.get("X-Requested-With") == "fetch"
    if estado not in Tarea.Estado.values:
        if en_segundo_plano:
            return JsonResponse({"ok": False, "error": "Estado desconocido."}, status=400)
        messages.error(request, "No se entendió la marca. Probá de nuevo.")
        return redirect(_volver(tarea.fecha, persona, tarea))

    servicios.marcar(tarea, estado, request.user)
    if en_segundo_plano:
        del_dia = servicios.filtrar_persona(Tarea.objects.filter(empresa=tarea.empresa, fecha=tarea.fecha), persona)
        return JsonResponse({
            "ok": True, "estado": tarea.estado, "estado_texto": tarea.get_estado_display(),
            "quien": servicios.nombre_de(tarea.marcada_por, request.user), "cuando": _cuando(tarea),
            "dia": servicios.conteo(del_dia),
        })
    return redirect(_volver(tarea.fecha, persona, tarea))


@require_POST
@rol_requerido(*ROLES)
def guardar(request, pk):
    """La nota y quién la hace. Quién la hace se puede cambiar porque el plan
    propuso un reparto que el negocio todavía puede ajustar."""
    tarea = documento_de_empresa(Tarea, request, pk=pk)
    persona = servicios.persona_valida(request.POST.get("quien", ""))
    campos = []
    if "nota" in request.POST:
        tarea.nota = request.POST["nota"].strip()[:1000]
        campos.append("nota")
    if request.POST.get("responsable") in Responsable.values:
        tarea.responsable = request.POST["responsable"]
        campos.append("responsable")
    if campos:
        tarea.save(update_fields=campos + ["actualizada_en"])
        messages.success(request, "Listo, quedó guardado.")
    return redirect(_volver(tarea.fecha, persona, tarea, abierta=True))


@require_POST
@rol_requerido(*ROLES)
def agregar(request):
    empresa = empresa_actual(request)
    fecha = _fecha(request.POST.get("fecha")) or servicios.hoy()
    persona = servicios.persona_valida(request.POST.get("quien", ""))
    titulo = (request.POST.get("titulo") or "").strip()[:200]
    if not titulo:
        messages.error(request, "Escribí qué hay que hacer para poder agregar la tarea.")
        return redirect(_volver(fecha, persona))
    responsable = request.POST.get("responsable")
    tarea = Tarea.objects.create(
        empresa=empresa, plan=servicios.plan_de(empresa, fecha), fecha=fecha, orden=900,
        titulo=titulo, responsable=responsable if responsable in Responsable.values else Responsable.LOS_DOS,
        tipo=Tarea.Tipo.OTRA, a_mano=True, creada_por=request.user,
    )
    messages.success(request, "Tarea agregada.")
    return redirect(_volver(fecha, persona, tarea))


@require_POST
@rol_requerido(*ROLES)
def borrar(request, pk):
    """Solo lo agregado a mano: lo del plan y la rutina se marca «No se hizo»,
    no se borra, para que el cierre de la semana vea lo que se decidió no hacer."""
    tarea = documento_de_empresa(Tarea, request, pk=pk)
    persona = servicios.persona_valida(request.POST.get("quien", ""))
    if not tarea.a_mano:
        messages.error(request, "Las tareas del plan no se borran: marcala «No se hizo».")
        return redirect(_volver(tarea.fecha, persona, tarea))
    if not (es_gerente(request.user) or tarea.creada_por_id == request.user.pk):
        messages.error(request, "Solo quien la agregó o un gerente puede borrarla.")
        return redirect(_volver(tarea.fecha, persona, tarea))
    fecha = tarea.fecha
    tarea.delete()
    messages.success(request, "Tarea borrada.")
    return redirect(_volver(fecha, persona))
