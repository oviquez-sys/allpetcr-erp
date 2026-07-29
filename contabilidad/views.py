from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import Empresa
from core.roles import CONTADOR, GERENTE, rol_requerido
from core.tenancy import documento_de_empresa, empresa_actual

from .models import Asiento, CierrePeriodo, CuentaContable, LineaAsiento
from .services import cerrar_periodo, fecha_bloqueo, reabrir_periodo


@rol_requerido(GERENTE, CONTADOR)
def libro_diario(request):
    empresa = empresa_actual(request)
    asientos = (
        Asiento.objects.filter(empresa=empresa)
        .prefetch_related("lineas__cuenta")
        .order_by("-id")[:100]
    )
    return render(request, "contabilidad/libro_diario.html", {"asientos": asientos})


@rol_requerido(GERENTE, CONTADOR)
def balance_comprobacion(request):
    """Suma débitos y créditos por cuenta de movimiento. Por partida doble el
    total de débitos SIEMPRE iguala el de créditos: es la prueba de que la
    contabilidad, generada sola, está cuadrada."""
    empresa = empresa_actual(request)
    filas = (
        LineaAsiento.objects.filter(asiento__empresa=empresa)
        .values("cuenta__codigo", "cuenta__nombre")
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
        .order_by("cuenta__codigo")
    )
    total_debe = sum((f["debe"] or Decimal("0") for f in filas), Decimal("0"))
    total_haber = sum((f["haber"] or Decimal("0") for f in filas), Decimal("0"))
    return render(request, "contabilidad/balance.html", {
        "filas": filas,
        "total_debe": total_debe,
        "total_haber": total_haber,
        "cuadra": total_debe == total_haber,
    })


@rol_requerido(GERENTE)
def cierres(request):
    """Cerrar un período (hasta una fecha) y reabrir cierres, solo gerente.
    Cerrar bloquea todo registro con esa fecha o anterior; reabrir queda
    auditado (quién, cuándo, por qué)."""
    empresa = empresa_actual(request)

    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "cerrar":
                fecha_txt = (request.POST.get("fecha_cierre") or "").strip()
                if not fecha_txt:
                    raise ValidationError("Indicá la fecha hasta la cual cerrar.")
                fecha = datetime.strptime(fecha_txt, "%Y-%m-%d").date()
                cerrar_periodo(
                    empresa=empresa, fecha_cierre=fecha,
                    usuario=request.user, nota=request.POST.get("nota") or "",
                )
                messages.success(request, f"Período cerrado hasta el {fecha:%d/%m/%Y}.")
            elif accion == "reabrir":
                cierre = documento_de_empresa(
                    CierrePeriodo, request, pk=request.POST.get("cierre_id")
                )
                reabrir_periodo(
                    cierre=cierre, usuario=request.user,
                    motivo=request.POST.get("motivo") or "",
                )
                messages.success(request, "Período reabierto. Quedó registrado quién y por qué.")
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
        except ValueError:
            messages.error(request, "Fecha inválida.")
        return redirect("contabilidad:cierres")

    lista = (CierrePeriodo.objects.filter(empresa=empresa)
             .select_related("cerrado_por", "reabierto_por"))
    return render(request, "contabilidad/cierres.html", {
        "cierres": lista,
        "bloqueo": fecha_bloqueo(empresa),
    })


def _parse_fecha(txt, por_defecto):
    try:
        return datetime.strptime((txt or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return por_defecto


@rol_requerido(GERENTE, CONTADOR)
def estado_resultados(request):
    """Estado de resultados (pérdidas y ganancias) para un rango de fechas.

    Se arma SOLO desde los asientos ya cuadrados: ingresos (naturaleza I) menos
    costo de ventas y gastos (naturaleza G). No hay cifras digitadas a mano, así
    que siempre concuerda con el libro diario y el balance."""
    empresa = empresa_actual(request)
    hoy = timezone.localdate()
    desde = _parse_fecha(request.GET.get("desde"), hoy.replace(month=1, day=1))
    hasta = _parse_fecha(request.GET.get("hasta"), hoy)

    lineas = (
        LineaAsiento.objects
        .filter(asiento__empresa=empresa, asiento__fecha__gte=desde, asiento__fecha__lte=hasta)
        .values("cuenta__codigo", "cuenta__nombre", "cuenta__naturaleza")
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
        .order_by("cuenta__codigo")
    )

    ingresos, gastos = [], []
    costo_ventas = Decimal("0")
    total_ingresos = Decimal("0")
    total_gastos_oper = Decimal("0")
    N = CuentaContable.Naturaleza
    for f in lineas:
        debe = f["debe"] or Decimal("0")
        haber = f["haber"] or Decimal("0")
        nat = f["cuenta__naturaleza"]
        if nat == N.INGRESO:
            saldo = haber - debe  # crédito natural; descuentos (débito) restan
            ingresos.append({"codigo": f["cuenta__codigo"], "nombre": f["cuenta__nombre"], "monto": saldo})
            total_ingresos += saldo
        elif nat == N.GASTO:
            saldo = debe - haber  # débito natural
            fila = {"codigo": f["cuenta__codigo"], "nombre": f["cuenta__nombre"], "monto": saldo}
            if f["cuenta__codigo"].startswith("51"):  # 51xx = costo de ventas
                costo_ventas += saldo
                fila["es_costo"] = True
            else:
                total_gastos_oper += saldo
            gastos.append(fila)

    utilidad_bruta = total_ingresos - costo_ventas
    utilidad_neta = utilidad_bruta - total_gastos_oper
    margen_neto = (utilidad_neta / total_ingresos * 100) if total_ingresos else None

    return render(request, "contabilidad/estado_resultados.html", {
        "desde": desde, "hasta": hasta,
        "ingresos": ingresos, "gastos": gastos,
        "total_ingresos": total_ingresos,
        "costo_ventas": costo_ventas,
        "utilidad_bruta": utilidad_bruta,
        "total_gastos_oper": total_gastos_oper,
        "utilidad_neta": utilidad_neta,
        "margen_neto": margen_neto,
        "hay_gastos_oper": total_gastos_oper != 0,
    })


@rol_requerido(GERENTE, CONTADOR)
def iva_trimestral(request):
    """Resumen trimestral para el Régimen de Tributación Simplificada.

    En RTS el impuesto se estima aplicando el factor de la actividad (que fija
    Hacienda por decreto) sobre las COMPRAS del trimestre. Aquí agrupamos las
    compras recibidas por trimestre del año elegido y, si hay factor cargado,
    mostramos el impuesto estimado. Las ventas se muestran solo de referencia."""
    from compras.models import Compra
    from ventas.models import FacturaVenta

    empresa = empresa_actual(request)
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get("anio") or hoy.year)
    except (TypeError, ValueError):
        anio = hoy.year

    factor = empresa.factor_rts if empresa else Decimal("0")

    etiquetas = ["Ene–Mar", "Abr–Jun", "Jul–Set", "Oct–Dic"]
    trimestres = []
    total_compras = total_ventas = total_impuesto = Decimal("0")
    for i in range(4):
        mes_ini = i * 3 + 1
        ini = date(anio, mes_ini, 1)
        fin = date(anio + 1, 1, 1) if i == 3 else date(anio, mes_ini + 3, 1)

        compras_q = Compra.objects.filter(
            empresa=empresa, estado="REC",
            recibida_en__date__gte=ini, recibida_en__date__lt=fin,
        ).aggregate(t=Sum("total"))["t"] or Decimal("0")

        ventas_q = FacturaVenta.objects.filter(
            empresa=empresa, estado="EMI",
            creado_en__date__gte=ini, creado_en__date__lt=fin,
        ).aggregate(t=Sum("total"))["t"] or Decimal("0")

        impuesto_q = (compras_q * factor).quantize(Decimal("0.01")) if factor else Decimal("0")

        trimestres.append({
            "n": i + 1,
            "rango": etiquetas[i],
            "compras": compras_q, "ventas": ventas_q, "impuesto": impuesto_q,
        })
        total_compras += compras_q
        total_ventas += ventas_q
        total_impuesto += impuesto_q

    return render(request, "contabilidad/iva_trimestral.html", {
        "anio": anio,
        "anios": list(range(hoy.year, hoy.year - 6, -1)),
        "trimestres": trimestres,
        "factor": factor,
        "hay_factor": factor and factor > 0,
        "total_compras": total_compras,
        "total_ventas": total_ventas,
        "total_impuesto": total_impuesto,
        "es_rts": empresa.regimen == empresa.Regimen.SIMPLIFICADO if empresa else True,
    })
