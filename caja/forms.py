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
