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
    # Obligatorios desde el 02/11/2026: "todo debe calzar" (Oscar). Antes se
    # podían dejar vacíos y el arqueo de tarjeta y SINPE quedaba sin hacer.
    # Si no hubo, se escribe 0: un SINPE que entró sin venta registrada
    # (la clienta pagó por SINPE algo que se cobró como tarjeta) solo se ve
    # si alguien anota lo que de verdad entró.
    tarjeta_contado = forms.DecimalField(
        label="Total del cierre del datáfono (₡)", required=True, min_value=0, max_digits=12, decimal_places=2,
        help_text="El total que imprime el datáfono al cerrar. Si no hubo pagos con tarjeta, 0.",
        error_messages={"required": "Escribí el total del datáfono (0 si no hubo)."},
    )
    sinpe_contado = forms.DecimalField(
        label="SINPE recibido según el celular o el banco (₡)", required=True, min_value=0, max_digits=12,
        decimal_places=2, help_text="Sumá los SINPE que de verdad entraron hoy. Si no hubo, 0.",
        error_messages={"required": "Escribí cuánto entró por SINPE (0 si no hubo)."},
    )


class JustificarForm(forms.Form):
    """Una explicación por cada medio que no calzó (02/11/2026). Los campos
    se llaman motivo_EFE / explicacion_EFE, etc., y solo existen para los
    medios que no calzaron."""

    def __init__(self, *args, medios=(), sugerencias=None, **kwargs):
        from .models import DiferenciaCaja

        super().__init__(*args, **kwargs)
        sugerencias = sugerencias or {}
        opciones = [("", "— elegí el motivo —")] + list(DiferenciaCaja.Motivo.choices)
        self.medios = list(medios)
        for medio in self.medios:
            self.fields[f"motivo_{medio}"] = forms.ChoiceField(
                label="Motivo", choices=opciones,
                initial=DiferenciaCaja.Motivo.CRUCE if medio in sugerencias else "",
                error_messages={"required": "Elegí el motivo."},
            )
            self.fields[f"explicacion_{medio}"] = forms.CharField(
                label="Qué pasó", max_length=300, min_length=5, initial=sugerencias.get(medio, ""),
                widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Ej.: la clienta iba a pagar con tarjeta "
                                             "y al final hizo un SINPE de ₡12.500 (factura 0001234)."}),
                error_messages={"required": "Contá qué pasó.",
                                "min_length": "Contá un poco más qué pasó."},
            )

    def justificaciones(self) -> dict:
        return {m: (self.cleaned_data[f"motivo_{m}"], self.cleaned_data[f"explicacion_{m}"]) for m in self.medios}

    def pares(self):
        return [(m, self[f"motivo_{m}"], self[f"explicacion_{m}"]) for m in self.medios]


class RetiroForm(forms.Form):
    """Sacar efectivo para depositar (02/11/2026): se cuentan los billetes que
    se sacan, igual que en el cierre, y el sistema suma."""

    nota = forms.CharField(label="Nota (opcional)", max_length=200, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "Ej.: para depositar en el BN"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for valor in TODAS:
            self.fields[f"den_{valor}"] = forms.IntegerField(
                label=f"₡{valor:,}".replace(",", "."), required=False, min_value=0, max_value=100000,
                widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "placeholder": "0",
                                                "data-valor": valor, "autocomplete": "off"}),
            )

    def clean(self):
        datos = super().clean()
        datos["conteo"] = {str(v): datos.get(f"den_{v}") or 0 for v in TODAS}
        if not total(datos["conteo"]):
            raise forms.ValidationError("Anotá cuántos billetes (o monedas) de cada uno se sacan.")
        return datos

    def billetes(self):
        return [(v, self[f"den_{v}"]) for v in BILLETES]

    def monedas(self):
        return [(v, self[f"den_{v}"]) for v in MONEDAS]
