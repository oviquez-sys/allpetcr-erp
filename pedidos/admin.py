from django.contrib import admin

from core.admin_fotos import columna_foto

from .models import AvisoDisponibilidad, CambioEstadoPedido, LineaPedido, Pedido, ReservaStock


class LineaPedidoInline(admin.TabularInline):
    model = LineaPedido
    extra = 0
    can_delete = False
    foto = columna_foto("producto", 40)
    readonly_fields = ("foto", "producto", "cantidad", "precio_unitario", "total")

    def has_add_permission(self, request, obj=None):
        return False


class CambioEstadoPedidoInline(admin.TabularInline):
    model = CambioEstadoPedido
    extra = 0
    can_delete = False
    readonly_fields = ("estado_anterior", "estado_nuevo", "nota", "usuario", "fecha")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("numero", "cliente_nombre", "estado", "total", "creado_en")
    list_filter = ("estado",)
    search_fields = ("numero", "cliente_nombre", "cliente_telefono", "cliente_email", "referencia_pago")
    readonly_fields = [f.name for f in Pedido._meta.fields]
    inlines = [LineaPedidoInline, CambioEstadoPedidoInline]

    def has_add_permission(self, request):
        # Un pedido nace del checkout del sitio (o de la API), no a mano.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AvisoDisponibilidad)
class AvisoDisponibilidadAdmin(admin.ModelAdmin):
    foto = columna_foto("producto", 32)
    list_display = ("foto", "producto", "email", "notificado", "creado_en")
    list_filter = ("notificado",)
    search_fields = ("producto__sku", "producto__nombre", "email")


@admin.register(ReservaStock)
class ReservaStockAdmin(admin.ModelAdmin):
    """Solo lectura: sirve para ver qué está reservado en un momento dado,
    no para crear ni editar reservas a mano (eso lo hace el checkout)."""

    foto = columna_foto("producto", 32)
    list_display = ("foto", "producto", "token_carrito", "cantidad", "creada_en", "expira_en")
    readonly_fields = [f.name for f in ReservaStock._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
