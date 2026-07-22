from django.contrib import admin

from .models import AuditLog, Empresa, Sucursal


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "regimen", "moneda", "factor_rts")
    fields = ("nombre", "regimen", "regimen_vigente_desde", "moneda", "factor_rts")


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "activa")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Solo lectura: la bitácora no se edita ni se borra desde ninguna pantalla."""

    list_display = ("fecha", "accion", "tabla", "objeto_id", "usuario")
    list_filter = ("accion", "tabla")
    search_fields = ("objeto_id",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
