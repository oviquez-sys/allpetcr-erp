from django.contrib import admin

from .models import Asiento, CierrePeriodo, CuentaContable, LineaAsiento


@admin.register(CierrePeriodo)
class CierrePeriodoAdmin(admin.ModelAdmin):
    list_display = ("fecha_cierre", "activo", "nota", "cerrado_por", "cerrado_en", "reabierto_por")
    list_filter = ("activo",)
    readonly_fields = ("cerrado_en", "reabierto_en")


@admin.register(CuentaContable)
class CuentaContableAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "naturaleza", "movimiento")
    list_filter = ("naturaleza", "movimiento")
    search_fields = ("codigo", "nombre")


class LineaAsientoInline(admin.TabularInline):
    model = LineaAsiento
    extra = 0
    can_delete = False
    readonly_fields = ("cuenta", "debe", "haber", "detalle")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Asiento)
class AsientoAdmin(admin.ModelAdmin):
    """Libro diario de solo lectura: los asientos nacen de operaciones, no
    se digitan ni se editan ni se borran."""

    list_display = ("numero", "fecha", "origen", "descripcion", "referencia", "total_debe", "total_haber", "cuadra")
    list_filter = ("origen",)
    search_fields = ("numero", "referencia", "descripcion")
    date_hierarchy = "fecha"
    inlines = [LineaAsientoInline]
    readonly_fields = [f.name for f in Asiento._meta.fields]

    @admin.display(boolean=True, description="Cuadra")
    def cuadra(self, obj):
        return obj.cuadra

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
