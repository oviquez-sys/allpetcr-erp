from django import forms

from core.models import Sucursal


class AbrirCajaForm(forms.Form):
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.filter(activa=True), label="Sucursal")
    monto_apertura = forms.DecimalField(
        label="Monto de apertura (₡)", min_value=0, max_digits=12, decimal_places=2,
        help_text="Efectivo contado físicamente al iniciar el turno",
    )


class CerrarCajaForm(forms.Form):
    monto_contado = forms.DecimalField(
        label="Efectivo contado al cierre (₡)", min_value=0, max_digits=12, decimal_places=2,
        help_text="Cuente el efectivo ANTES de ver el monto esperado (arqueo ciego)",
    )
    # Arqueo de lo que no es efectivo (auditoría 26/09/2026, CAJ-02).
    tarjeta_contado = forms.DecimalField(
        label="Total del cierre del datáfono (₡)", required=False, min_value=0, max_digits=12, decimal_places=2,
        help_text="El total que imprime el datáfono al cerrar. Déjelo vacío si no lo revisó.",
    )
    sinpe_contado = forms.DecimalField(
        label="SINPE recibido según el celular o el banco (₡)", required=False, min_value=0, max_digits=12,
        decimal_places=2, help_text="Sume los SINPE que de verdad entraron hoy. Vacío si no lo revisó.",
    )
