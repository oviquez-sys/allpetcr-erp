from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from core.roles import CAJERO, GERENTE, rol_requerido

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
    return render(request, "caja/abrir.html", {"form": form})


@rol_requerido(CAJERO, GERENTE)
def cerrar(request):
    sesion = services.sesion_abierta_de(request.user)
    if not sesion:
        messages.info(request, "No tiene una caja abierta.")
        return redirect("caja:abrir")
    form = CerrarCajaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            sesion = services.cerrar_caja(
                sesion=sesion, monto_contado=form.cleaned_data["monto_contado"], usuario=request.user
            )
            signo = "sobrante" if sesion.diferencia > 0 else ("faltante" if sesion.diferencia < 0 else "exacto")
            messages.success(
                request,
                f"Caja #{sesion.pk} cerrada. Esperado ₡{sesion.monto_esperado} · "
                f"Contado ₡{sesion.monto_contado} · Diferencia ₡{sesion.diferencia} ({signo}).",
            )
            return redirect("caja:abrir")
        except ValidationError as e:
            form.add_error(None, e)
    movimientos = sesion.movimientos.all()[:50]
    return render(request, "caja/cerrar.html", {"form": form, "sesion": sesion, "movimientos": movimientos})
