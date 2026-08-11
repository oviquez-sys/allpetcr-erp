from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Compra, LineaCompra, Proveedor
from .services import recibir_compra


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "identificacion", "telefono", "saldo", "activo")
    search_fields = ("nombre", "identificacion")
    readonly_fields = ("saldo",)


class LineaCompraInline(admin.TabularInline):
    model = LineaCompra
    extra = 1
    autocomplete_fields = ("producto",)
    can_delete = False

    def get_readonly_fields(self, request, obj=None):
        # Una compra recibida es inmutable.
        if obj and obj.estado != Compra.Estado.BORRADOR:
            return ("producto", "cantidad", "costo_unitario", "total")
        return ("total",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    """Documento de solo lectura, como sus pares (FacturaVenta, Asiento,
    MovimientoInventario...): nace de crear_compra/recibir_compra, nunca se
    digita ni se borra desde acá. Para corregir una compra recibida, usar
    anular_compra (services.py) — nunca borrarla."""

    list_display = ("numero", "proveedor", "estado", "forma_pago", "total", "creado_en", "recibida_en")
    list_filter = ("estado", "forma_pago")
    search_fields = ("numero", "factura_proveedor", "proveedor__nombre")
    inlines = [LineaCompraInline]
    actions = ["accion_recibir"]
    readonly_fields = [f.name for f in Compra._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Recibir compra (entra a inventario y contabilidad)")
    def accion_recibir(self, request, queryset):
        for compra in queryset:
            try:
                recibir_compra(compra=compra, usuario=request.user)
                self.message_user(request, f"{compra.numero} recibida: inventario y asiento generados.", messages.SUCCESS)
            except ValidationError as e:
                self.message_user(request, f"{compra.numero}: {' '.join(e.messages)}", messages.ERROR)
