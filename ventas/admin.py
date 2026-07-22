from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html

from .models import Abono, Cliente, DevolucionVenta, DocumentoCxC, FacturaVenta, LineaVenta
from .services import anular_factura


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "identificacion", "telefono", "limite_credito", "saldo", "credito_disponible", "estado_cuenta", "activo")
    search_fields = ("nombre", "identificacion", "telefono")
    readonly_fields = ("saldo",)  # el saldo lo mueven ventas y abonos, no la mano

    @admin.display(description="Estado de cuenta")
    def estado_cuenta(self, obj):
        url = reverse("ventas:estado_cuenta", args=[obj.pk])
        return format_html('<a href="{}">Ver</a>', url)


class LineaVentaInline(admin.TabularInline):
    model = LineaVenta
    extra = 0
    can_delete = False
    readonly_fields = ("producto", "cantidad", "precio_unitario", "costo_unitario", "total")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FacturaVenta)
class FacturaVentaAdmin(admin.ModelAdmin):
    list_display = ("numero", "creado_en", "estado", "medio_pago", "cliente", "total", "usuario")
    list_filter = ("estado", "medio_pago")
    search_fields = ("numero", "cliente__nombre")
    date_hierarchy = "creado_en"
    inlines = [LineaVentaInline]
    readonly_fields = [f.name for f in FacturaVenta._meta.fields]
    actions = ["accion_anular"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Anular factura seleccionada (reversa inventario, caja y CxC)")
    def accion_anular(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Seleccione exactamente una factura.", messages.ERROR)
            return
        try:
            factura = anular_factura(
                factura=queryset.first(),
                motivo=f"Anulada desde admin por {request.user.username}",
                usuario=request.user,
            )
            self.message_user(request, f"{factura.numero} anulada.", messages.SUCCESS)
        except ValidationError as e:
            self.message_user(request, " ".join(e.messages), messages.ERROR)


class LineaDevolucionInline(admin.TabularInline):
    model = DevolucionVenta.lineas.rel.related_model
    extra = 0
    can_delete = False
    readonly_fields = ("linea_venta", "cantidad", "monto")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DevolucionVenta)
class DevolucionVentaAdmin(admin.ModelAdmin):
    list_display = ("numero", "factura", "total", "usuario", "creado_en")
    search_fields = ("numero", "factura__numero")
    date_hierarchy = "creado_en"
    inlines = [LineaDevolucionInline]
    readonly_fields = [f.name for f in DevolucionVenta._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AbonoInline(admin.TabularInline):
    model = Abono
    extra = 0
    can_delete = False
    readonly_fields = ("monto", "medio", "referencia", "usuario", "fecha")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DocumentoCxC)
class DocumentoCxCAdmin(admin.ModelAdmin):
    list_display = ("factura", "cliente", "monto_original", "saldo", "estado", "creado_en")
    list_filter = ("estado",)
    search_fields = ("factura__numero", "cliente__nombre")
    readonly_fields = [f.name for f in DocumentoCxC._meta.fields]
    inlines = [AbonoInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
