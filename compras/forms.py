from django import forms

from .entregas import DIAS_CORTOS
from .models import Proveedor

_DIAS = [(str(i), d) for i, d in enumerate(DIAS_CORTOS)]


class DiasField(forms.MultipleChoiceField):
    """Casillas Lun…Dom que se guardan como "04" (lunes y viernes)."""

    def __init__(self, **kw):
        super().__init__(choices=_DIAS, required=False, widget=forms.CheckboxSelectMultiple, **kw)

    def prepare_value(self, value):
        return list(value) if isinstance(value, str) else value

    def clean(self, value):
        return "".join(sorted(set(super().clean(value))))


class ProveedorForm(forms.ModelForm):
    dias_pedido = DiasField(label="Se le pide", help_text="Ninguno marcado = cualquier día")
    dias_entrega = DiasField(label="Entrega", help_text="Ninguno marcado = cualquier día")

    class Meta:
        model = Proveedor
        fields = [
            "nombre", "contacto", "telefono", "email", "razon_social", "identificacion",
            "cuenta_bancaria", "direccion_bodega", "catalogo", "pedidos_en_linea",
            "horario_entrega", "dias_pedido", "hora_limite", "dias_entrega", "dias_minimos",
            "notas", "activo",
        ]
        labels = {
            "telefono": "Celular", "email": "Correo", "razon_social": "Razón social",
            "identificacion": "Cédula", "cuenta_bancaria": "Cuenta para pagarle",
            "direccion_bodega": "Dirección de bodega", "catalogo": "Catálogo",
            "pedidos_en_linea": "Pedidos en línea", "horario_entrega": "Horario (como lo dice el proveedor)",
            "hora_limite": "Pedir antes de las", "dias_minimos": "Tarda al menos (días)",
            "activo": "Activo",
        }
        widgets = {
            "hora_limite": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "notas": forms.Textarea(attrs={"rows": 2}),
            "dias_minimos": forms.NumberInput(attrs={"min": 0, "max": 30}),
        }
