from django import forms

from core.models import Sucursal

from .denominaciones import BILLETES, MONEDAS, TODAS, total


class AbrirCajaForm(forms.Form):
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.filter(activa=True), label="Sucursal")
    monto_apertura = forms.DecimalField(
        label="Monto de apertura (₡)", min_value=0, max_digits=12, decimal_places=2,
        help_text="Efectivo contado físicamente al iniciar el turno",
    )


class CerrarCajaForm(forms.Form):
    """El efectivo se cuenta por billete y moneda (pedido de Oscar,
    14/10/2026): se anota cuántos hay de cada uno y el sistema suma. Un campo
    vacío es cero. Los campos se llaman den_20000, den_500, etc."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for valor in TODAS:
            self.fields[f"den_{valor}"] = forms.IntegerField(
                label=f"₡{valor:,}".replace(",", "."), required=False, min_value=0, max_value=100000,
                widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "placeholder": "0",
                                                "data-valor": valor, "autocomplete": "off"}),
            )
        # Primero los billetes y monedas, después datáfono y SINPE.
        orden = [f"den_{v}" for v in TODAS] + ["tarjeta_contado", "sinpe_contado"]
        self.order_fields(orden)

    def clean(self):
        datos = super().clean()
        datos["conteo"] = {str(v): datos.get(f"den_{v}") or 0 for v in TODAS}
        datos["monto_contado"] = total(datos["conteo"])
        return datos

    def campos_de(self, valores):
        return [(v, self[f"den_{v}"]) for v in valores]

    def billetes(self):
        return self.campos_de(BILLETES)

    def monedas(self):
        return self.campos_de(MONEDAS)

    # Arqueo de lo que no es efectivo (auditoría 26/09/2026, CAJ-02).
    tarjeta_contado = forms.DecimalField(
        label="Total del cierre del datáfono (₡)", required=False, min_value=0, max_digits=12, decimal_places=2,
        help_text="El total que imprime el datáfono al cerrar. Déjelo vacío si no lo revisó.",
    )
    sinpe_contado = forms.DecimalField(
        label="SINPE recibido según el celular o el banco (₡)", required=False, min_value=0, max_digits=12,
        decimal_places=2, help_text="Sume los SINPE que de verdad entraron hoy. Vacío si no lo revisó.",
    )
