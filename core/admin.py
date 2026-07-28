from django.contrib import admin

from .models import AuditLog, ChatMensaje, Empresa, Sucursal


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "identificacion", "regimen", "moneda", "factor_rts")
    fields = ("nombre", "identificacion", "regimen", "regimen_vigente_desde", "moneda", "factor_rts")


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


@admin.register(ChatMensaje)
class ChatMensajeAdmin(admin.ModelAdmin):
    """Solo lectura: sirve para ver qué preguntan los usuarios, no para editar."""

    list_display = ("creado_en", "usuario", "pregunta_corta", "tuvo_error")
    list_filter = ("usuario",)
    search_fields = ("pregunta", "respuesta", "usuario__username")
    readonly_fields = [f.name for f in ChatMensaje._meta.fields]
    date_hierarchy = "creado_en"

    def pregunta_corta(self, obj):
        return obj.pregunta[:80]
    pregunta_corta.short_description = "Pregunta"

    def tuvo_error(self, obj):
        return bool(obj.error)
    tuvo_error.short_description = "Error"
    tuvo_error.boolean = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
