from django.contrib import admin

from core.admin_fotos import columna_foto

from .models import Bodega, MovimientoInventario


@admin.register(Bodega)
class BodegaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "sucursal")


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    """Kardex de solo lectura: los movimientos se crean por operaciones
    (ventas, compras, ajustes vía servicio), nunca digitados aquí."""

    foto = columna_foto("producto", 32)
    list_display = ("fecha", "tipo", "foto", "producto", "cantidad", "costo_unitario", "stock_resultante", "referencia")
    list_filter = ("tipo", "bodega")
    list_select_related = ("producto",)
    search_fields = ("producto__sku", "producto__nombre", "referencia")
    date_hierarchy = "fecha"
    list_per_page = 50
    readonly_fields = [f.name for f in MovimientoInventario._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
