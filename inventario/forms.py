from django import forms

from catalogo.models import Producto

from .models import Bodega


class AjusteInventarioForm(forms.Form):
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.filter(activo=True).order_by("nombre"),
        label="Producto",
    )
    bodega = forms.ModelChoiceField(queryset=Bodega.objects.all(), label="Bodega")
    cantidad = forms.DecimalField(
        label="Cantidad",
        help_text="Positiva entra (sobrante), negativa sale (faltante/dañado)",
        max_digits=12,
        decimal_places=2,
    )
    costo_unitario = forms.DecimalField(
        label="Costo unitario (solo entradas)",
        required=False,
        initial=0,
        min_value=0,
        max_digits=12,
        decimal_places=2,
    )
    motivo = forms.CharField(
        label="Motivo (obligatorio, queda en auditoría)",
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=200,
    )

    def clean_cantidad(self):
        cantidad = self.cleaned_data["cantidad"]
        if cantidad == 0:
            raise forms.ValidationError("La cantidad no puede ser cero.")
        return cantidad
