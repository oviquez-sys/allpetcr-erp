from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from core.roles import CAJERO, GERENTE, rol_requerido
from core.tenancy import empresa_actual

from . import services
from .forms import AbrirCajaForm, CerrarCajaForm


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
    sesion = services.sesion_abierta_de(request.user)
    if not sesion:
        messages.info(request, "No tiene una caja abierta.")
        return redirect("caja:abrir")
    # Con todo vacío (no había efectivo) el POST llega sin datos: igual es un cierre.
    form = CerrarCajaForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            sesion = services.cerrar_caja(
                sesion=sesion, conteo=form.cleaned_data["conteo"], usuario=request.user,
                tarjeta_contado=form.cleaned_data.get("tarjeta_contado"),
                sinpe_contado=form.cleaned_data.get("sinpe_contado"),
            )
            signo = "sobrante" if sesion.diferencia > 0 else ("faltante" if sesion.diferencia < 0 else "exacto")
            texto = (f"Caja #{sesion.pk} cerrada. Efectivo: esperado ₡{sesion.monto_esperado:,.0f} · "
                     f"contado ₡{sesion.monto_contado:,.0f} · diferencia ₡{sesion.diferencia:,.0f} ({signo}).")
            for nombre, esperado, contado in (("Tarjeta", sesion.tarjeta_esperado, sesion.tarjeta_contado),
                                              ("SINPE", sesion.sinpe_esperado, sesion.sinpe_contado)):
                if contado is not None:
                    texto += f" {nombre}: vendido ₡{esperado:,.0f}, según comprobante ₡{contado:,.0f}"
                    texto += " (cuadra)." if contado == esperado else f" (diferencia ₡{contado - esperado:,.0f})."
            messages.success(request, texto.replace(",", "."))
            return redirect("caja:abrir")
        except ValidationError as e:
            form.add_error(None, e)
    movimientos = sesion.movimientos.all()[:50]
    # Cómo se abrió esta caja (17/10/2026) y qué contó el cierre anterior:
    # si la apertura no calza con lo que quedó la noche antes, se ve aquí.
    # No muestra lo esperado de ESTA caja: el conteo sigue siendo ciego.
    anterior = services.ultimo_cierre(empresa_actual(request), antes_de=sesion.abierta_en)
    return render(request, "caja/cerrar.html", {
        "form": form, "sesion": sesion, "movimientos": movimientos, "anterior": anterior,
        "grupos": [("Billetes", form.billetes()), ("Monedas", form.monedas())],
    })
