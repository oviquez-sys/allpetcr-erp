from django import forms

from catalogo.models import Producto

from .models import Bodega


class AjusteInventarioForm(forms.Form):
    """Ajuste manual de inventario.

    El selector se acota a la empresa del usuario (auditoría 2026-07-28,
    ARQ-01). Antes ofrecía TODOS los productos activos del sistema, así que el
    día que haya una segunda empresa se podría ajustar el stock de la otra
    desde este formulario. Los queryset se definen vacíos a nivel de clase y
    se llenan en __init__ con la empresa recibida: si alguien instancia el
    formulario sin pasarla, no ve nada — que es el valor seguro.
    """

    producto = forms.ModelChoiceField(queryset=Producto.objects.none(), label="Producto")
    bodega = forms.ModelChoiceField(queryset=Bodega.objects.none(), label="Bodega")
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

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa is not None:
            self.fields["producto"].queryset = (
                Producto.objects.filter(activo=True, empresa=empresa).order_by("nombre")
            )
            self.fields["bodega"].queryset = (
                Bodega.objects.filter(sucursal__empresa=empresa).order_by("nombre")
            )

    def clean_cantidad(self):
        cantidad = self.cleaned_data["cantidad"]
        if cantidad == 0:
            raise forms.ValidationError("La cantidad no puede ser cero.")
        return cantidad
