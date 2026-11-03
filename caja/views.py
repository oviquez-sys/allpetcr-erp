import logging
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.roles import CAJERO, GERENTE, es_gerente, rol_requerido
from core.tenancy import empresa_actual

from . import services
from .forms import AbrirCajaForm, CerrarCajaForm, JustificarForm
from .models import SesionCaja
from .resumen import texto_diferencia

logger = logging.getLogger(__name__)


@rol_requerido(CAJERO, GERENTE)
def abrir(request):
    if services.sesion_abierta_de(request.user):
        messages.info(request, "Ya tiene una caja abierta.")
        return redirect("ventas:pos")
    form = AbrirCajaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            sesion = services.abrir_caja(
                sucursal=form.cleaned_data["sucursal"],
                usuario=request.user,
                monto_apertura=form.cleaned_data["monto_apertura"],
            )
            messages.success(request, f"Caja #{sesion.pk} abierta con ₡{sesion.monto_apertura}.")
            return redirect("ventas:pos")
        except ValidationError as e:
            form.add_error(None, e)
    # Cómo se cerró la caja anterior (17/10/2026): para abrir sabiendo con
    # qué se quedó la gaveta y si el cierre cuadró.
    anterior = services.ultimo_cierre(empresa_actual(request))
    return render(request, "caja/abrir.html", {
        "form": form, "anterior": anterior,
        "anterior_ventas": services.resumen_ventas(anterior) if anterior else None,
    })


@rol_requerido(CAJERO, GERENTE)
def cerrar(request):
    """Cierre en dos pasos (02/11/2026, pedido de Oscar).

    1. Se cuenta a ciegas: efectivo por billete y moneda, total del datáfono
       y SINPE recibido. Si todo calza, la caja se cierra en ese momento.
    2. Si algo no calza, se muestra qué medio, de cuánto, y se pide la
       explicación ("iba a pagar con tarjeta y al final hizo un SINPE"). Se
       puede volver a contar, pero el primer conteo queda guardado: recontar
       es legítimo, acomodar el conteo al esperado sin rastro no.

    Entre un paso y otro el conteo viaja firmado (no se puede tocar desde el
    navegador) y no se guarda nada: la caja sigue abierta hasta confirmar."""
    sesion = services.sesion_abierta_de(request.user)
    if not sesion:
        messages.info(request, "No tiene una caja abierta.")
        return redirect("caja:abrir")
    paso = request.POST.get("paso", "contar") if request.method == "POST" else "contar"
    if paso == "justificar":
        return _justificar(request, sesion)
    if paso in ("corregir", "retiro"):
        return _ajustar(request, sesion, paso)
    if paso == "recontar":
        datos = _leer(request.POST.get("firma"), sesion)
        if datos is None:
            messages.info(request, "Pasó mucho tiempo: volvé a contar.")
            return redirect("caja:cerrar")
        previos = datos["previos"] + [_resumen_conteo(datos)]
        inicial = {f"den_{v}": n for v, n in datos["conteo"].items() if n}
        inicial.update(tarjeta_contado=datos["tarjeta"], sinpe_contado=datos["sinpe"])
        return _pantalla_conteo(request, sesion, CerrarCajaForm(initial=inicial), previos)

    previos = (_leer(request.POST.get("previos"), sesion, lista=True) or []) if request.method == "POST" else []
    # Con todo vacío (no había efectivo) el POST llega sin datos: igual es un cierre.
    form = CerrarCajaForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        datos = {"sesion": sesion.pk, "conteo": d["conteo"], "efectivo": str(d["monto_contado"]),
                 "tarjeta": str(d["tarjeta_contado"]), "sinpe": str(d["sinpe_contado"]), "previos": previos}
        arqueo = services.calcular_arqueo(sesion, efectivo=d["monto_contado"], tarjeta=d["tarjeta_contado"],
                                          sinpe=d["sinpe_contado"])
        if all(f["calza"] for f in arqueo):
            return _cerrar_y_avisar(request, sesion, datos, {})
        return _pantalla_diferencias(request, sesion, datos, arqueo)
    return _pantalla_conteo(request, sesion, form, previos)


def _pantalla_conteo(request, sesion, form, previos):
    movimientos = sesion.movimientos.all()[:50]
    # Cómo se abrió esta caja (17/10/2026) y qué contó el cierre anterior:
    # si la apertura no calza con lo que quedó la noche antes, se ve aquí.
    # No muestra lo esperado de ESTA caja: el conteo sigue siendo ciego.
    anterior = services.ultimo_cierre(empresa_actual(request), antes_de=sesion.abierta_en)
    return render(request, "caja/cerrar.html", {
        "form": form, "sesion": sesion, "movimientos": movimientos, "anterior": anterior,
        "grupos": [("Billetes", form.billetes()), ("Monedas", form.monedas())],
        "previos": previos, "previos_firmado": signing.dumps(previos, salt=_SAL) if previos else "",
    })


def _pantalla_diferencias(request, sesion, datos, arqueo, form=None, aviso=""):
    from ventas.medio_pago import candidatas_cruce

    malas = [f for f in arqueo if not f["calza"]]
    sugerencias = services.sugerir_cruce(arqueo)
    datos = dict(datos, difs={f["medio"]: str(f["diferencia"]) for f in malas})
    form = form or JustificarForm(medios=[f["medio"] for f in malas], sugerencias=sugerencias)
    campos = dict((m, (motivo, explicacion)) for m, motivo, explicacion in form.pares())
    # Si parece una venta cobrada por otro medio, se ofrecen las ventas que
    # calzan con el monto para corregirlas con un clic (02/11/2026): mejor
    # que explicarlo, porque deja bien también el reporte por medio.
    cruce = None
    if sugerencias:
        falta = next(f for f in malas if f["diferencia"] < 0)
        sobra = next(f for f in malas if f["diferencia"] > 0)
        cruce = {"falta": falta, "sobra": sobra,
                 "ventas": candidatas_cruce(sesion, falta["medio"], abs(falta["diferencia"]))}
    efectivo = next((f for f in malas if f["medio"] == "EFE" and f["diferencia"] < 0), None)
    return render(request, "caja/cerrar_diferencias.html", {
        "sesion": sesion, "arqueo": arqueo, "form": form, "firma": signing.dumps(datos, salt=_SAL),
        "filas": [dict(f, campos=campos.get(f["medio"])) for f in arqueo],
        "hay_cruce": bool(sugerencias), "cruce": cruce, "aviso": aviso, "previos": datos["previos"],
        # Registrar al cerrar un retiro que no se anotó en el momento: solo
        # gerente. Si el cajero pudiera, cualquier faltante se "explicaría"
        # como un retiro que nunca llega al banco.
        "faltante_efectivo": abs(efectivo["diferencia"]) if efectivo and es_gerente(request.user) else None,
    })


def _ajustar(request, sesion, paso):
    """Desde la pantalla de diferencias: corregir el medio de pago de una
    venta, o registrar como retiro para depositar el efectivo que se sacó y
    no se anotó. Después se recalcula: si ya calza, la caja se cierra."""
    from ventas.medio_pago import cambiar_medio_pago
    from ventas.models import FacturaVenta

    from .retiros import registrar_retiro

    datos = _leer(request.POST.get("firma"), sesion)
    if datos is None:
        messages.info(request, "Pasó mucho tiempo desde que se contó: volvé a contar.")
        return redirect("caja:cerrar")
    try:
        if paso == "corregir":
            factura = get_object_or_404(FacturaVenta, pk=request.POST.get("factura"), sesion_caja=sesion)
            cambio = cambiar_medio_pago(factura=factura, nuevo=request.POST.get("nuevo", ""), usuario=request.user,
                                        motivo=request.POST.get("motivo") or "Corregido al cerrar la caja: se "
                                        "cobró por otro medio.")
            hecho = f"La venta {factura.numero} quedó como {cambio.get_nuevo_display()}."
        else:
            if not es_gerente(request.user):
                raise ValidationError("Solo un gerente puede registrar un retiro al cerrar.")
            retiro = registrar_retiro(sesion=sesion, usuario=request.user, monto=request.POST.get("monto"),
                                      nota=request.POST.get("nota", "Registrado al cerrar la caja"))
            hecho = f"Retiro {retiro.referencia} de ₡{retiro.monto:,.0f} registrado (queda por depositar).".replace(",", ".")
            _imprimir_retiro(request, retiro)
    except ValidationError as e:
        hecho = ""
        error = " ".join(e.messages)
    else:
        error = ""
    arqueo = services.calcular_arqueo(sesion, efectivo=datos["efectivo"], tarjeta=datos["tarjeta"],
                                      sinpe=datos["sinpe"])
    if not error and all(f["calza"] for f in arqueo):
        messages.info(request, hecho)
        return _cerrar_y_avisar(request, sesion, datos, {})
    return _pantalla_diferencias(request, sesion, datos, arqueo,
                                 aviso=error or (hecho + " Todavía queda algo que no calza."))


def _justificar(request, sesion):
    datos = _leer(request.POST.get("firma"), sesion)
    if datos is None:
        messages.info(request, "Pasó mucho tiempo desde que se contó: volvé a contar.")
        return redirect("caja:cerrar")
    arqueo = services.calcular_arqueo(sesion, efectivo=datos["efectivo"], tarjeta=datos["tarjeta"],
                                      sinpe=datos["sinpe"])
    ahora = {f["medio"]: str(f["diferencia"]) for f in arqueo if not f["calza"]}
    if ahora != datos.get("difs"):
        # Entró una venta (u otro movimiento) mientras se escribía la
        # explicación: lo esperado cambió y la explicación podría no aplicar.
        if not ahora:
            return _cerrar_y_avisar(request, sesion, datos, {})
        return _pantalla_diferencias(request, sesion, datos, arqueo,
                                     aviso="Mientras cerrabas entró un movimiento y las diferencias cambiaron. "
                                           "Revisalas de nuevo.")
    form = JustificarForm(request.POST, medios=list(ahora), sugerencias=services.sugerir_cruce(arqueo))
    if not form.is_valid():
        return _pantalla_diferencias(request, sesion, datos, arqueo, form=form)
    return _cerrar_y_avisar(request, sesion, datos, form.justificaciones())


def _cerrar_y_avisar(request, sesion, datos, justificaciones):
    try:
        sesion = services.cerrar_caja(
            sesion=sesion, conteo=datos["conteo"], usuario=request.user, tarjeta_contado=datos["tarjeta"],
            sinpe_contado=datos["sinpe"], justificaciones=justificaciones, conteos_previos=datos["previos"],
        )
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("caja:cerrar")
    sesion.refresh_from_db()  # el aviso por correo anota si salió (on_commit)
    diferencias = list(sesion.diferencias.all())
    if not diferencias:
        texto = (f"Caja #{sesion.pk} cerrada: todo calzó. Efectivo ₡{sesion.monto_contado:,.0f}, "
                 f"datáfono ₡{sesion.tarjeta_contado:,.0f}, SINPE ₡{sesion.sinpe_contado:,.0f}.")
        messages.success(request, texto.replace(",", "."))
    else:
        partes = [f"{d.get_medio_display()}: {texto_diferencia(d.diferencia).lower()}" for d in diferencias]
        texto = f"Caja #{sesion.pk} cerrada con diferencias explicadas ({'; '.join(partes)})."
        messages.warning(request, texto + (f" {sesion.aviso_diferencia}." if sesion.aviso_diferencia else ""))
    if getattr(settings, "CIERRE_TIQUETE_AUTOMATICO", True):
        _imprimir(request, sesion)
    return redirect("caja:abrir")


def _imprimir(request, sesion):
    from impresion.servicio import imprimir_cierre

    try:
        imprimir_cierre(sesion)
    except Exception as e:  # noqa: BLE001 — la caja ya está cerrada; un papel que no sale no la reabre
        logger.exception("No se pudo imprimir el cierre #%s", sesion.pk)
        messages.error(request, f"La caja quedó cerrada, pero el resumen no se pudo imprimir ({e}). "
                                "Podés reimprimirlo desde Abrir caja.")
        return False
    messages.info(request, "El resumen del cierre se mandó a la impresora de tiquetes.")
    return True


@rol_requerido(GERENTE)
def retiro(request):
    """Sacar efectivo de la gaveta para depositarlo, y anotar el depósito
    (02/11/2026, pedido de Oscar: mantener la gaveta bajo ₡50-60 mil). Solo
    gerente: es plata que sale de la caja."""
    from .forms import RetiroForm
    from .retiros import por_depositar, registrar_deposito, registrar_retiro

    empresa = empresa_actual(request)
    sesion = services.sesion_abierta_de(request.user)
    accion = request.POST.get("accion") if request.method == "POST" else ""
    form = RetiroForm(request.POST if accion == "retirar" else None)
    if accion == "retirar":
        if sesion is None:
            messages.error(request, "No hay una caja abierta.")
            return redirect("caja:retiro")
        if form.is_valid():
            try:
                r = registrar_retiro(sesion=sesion, usuario=request.user, conteo=form.cleaned_data["conteo"],
                                     nota=form.cleaned_data["nota"])
            except ValidationError as e:
                form.add_error(None, e)
            else:
                messages.success(request, f"Retiro {r.referencia} de ₡{r.monto:,.0f} registrado. Queda por "
                                          "depositar; el cierre de hoy ya lo descuenta.".replace(",", "."))
                _imprimir_retiro(request, r)
                return redirect("caja:retiro")
    elif accion == "depositar":
        ids = request.POST.getlist("retiro")
        elegidos = list(por_depositar(empresa).filter(pk__in=ids))
        try:
            fecha = datetime.strptime(request.POST.get("fecha", ""), "%Y-%m-%d").date()
        except ValueError:
            fecha = timezone.localdate()
        if not elegidos:
            messages.error(request, "Marcá cuáles retiros entraron en el depósito.")
        else:
            try:
                hechos = registrar_deposito(retiros=elegidos, usuario=request.user, fecha=fecha,
                                            comprobante=request.POST.get("comprobante", ""))
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
            else:
                total = sum(r.monto for r in hechos)
                messages.success(request, f"Depósito de ₡{total:,.0f} anotado.".replace(",", "."))
        return redirect("caja:retiro")
    from .models import RetiroCaja
    return render(request, "caja/retiro.html", {
        "sesion": sesion, "form": form, "grupos": [("Billetes", form.billetes()), ("Monedas", form.monedas())],
        "pendientes": por_depositar(empresa),
        "depositados": RetiroCaja.objects.filter(sesion__sucursal__empresa=empresa,
                                                 estado=RetiroCaja.Estado.DEPOSITADO)
        .select_related("usuario", "depositado_por").order_by("-depositado_en", "-id")[:10],
        "hoy": timezone.localdate(),
    })


def _imprimir_retiro(request, retiro):
    from impresion.servicio import imprimir_retiro

    try:
        imprimir_retiro(retiro)
    except Exception as e:  # noqa: BLE001 — el retiro ya quedó registrado; el papel es aparte
        logger.exception("No se pudo imprimir el retiro %s", retiro.referencia)
        messages.error(request, f"El retiro quedó registrado, pero el comprobante no se pudo imprimir ({e}).")
        return False
    messages.info(request, "Comprobante del retiro enviado a la impresora (abre la gaveta).")
    return True


@rol_requerido(CAJERO, GERENTE)
@require_POST
def imprimir(request, sesion_id):
    """Reimprimir el resumen de un cierre (botón en "Así se cerró la caja
    anterior"). Solo cajas cerradas de la empresa."""
    sesion = get_object_or_404(SesionCaja, pk=sesion_id, estado=SesionCaja.Estado.CERRADA,
                               sucursal__empresa=empresa_actual(request))
    _imprimir(request, sesion)
    return redirect("caja:abrir")


_SAL = "caja.cierre"
# Tres horas para escribir la explicación sobra; pasado eso, se vuelve a contar.
_VIGENCIA = 3 * 60 * 60


def _leer(firmado, sesion, lista=False):
    """Lo que viajó firmado entre los pasos del cierre, o None si no vale
    (vencido, tocado o de otra caja)."""
    if not firmado:
        return None
    try:
        datos = signing.loads(firmado, salt=_SAL, max_age=_VIGENCIA)
    except signing.BadSignature:
        return None
    if lista:
        return datos if isinstance(datos, list) else None
    return datos if isinstance(datos, dict) and datos.get("sesion") == sesion.pk else None


def _resumen_conteo(datos):
    return {"efectivo": datos["efectivo"], "tarjeta": datos["tarjeta"], "sinpe": datos["sinpe"],
            "billetes": {k: v for k, v in datos["conteo"].items() if v}, "en": timezone.now().isoformat()}
