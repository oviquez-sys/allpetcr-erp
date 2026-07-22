from django.contrib import admin

from .models import MovimientoCaja, SesionCaja


class SoloLectura:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SesionCaja)
class SesionCajaAdmin(SoloLectura, admin.ModelAdmin):
    list_display = ("id", "sucursal", "usuario", "estado", "monto_apertura",
                    "monto_esperado", "monto_contado", "diferencia", "abierta_en", "cerrada_en")
    list_filter = ("estado", "sucursal")


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(SoloLectura, admin.ModelAdmin):
    list_display = ("fecha", "sesion", "tipo", "monto", "referencia", "descripcion", "usuario")
    list_filter = ("tipo",)
    search_fields = ("referencia", "descripcion")
