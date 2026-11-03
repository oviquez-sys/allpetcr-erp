from django.contrib import admin

from .models import DiferenciaCaja, MovimientoCaja, RetiroCaja, SesionCaja


class SoloLectura:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DiferenciaInline(SoloLectura, admin.TabularInline):
    """Lo que no calzó en el cierre y su explicación (02/11/2026)."""
    model = DiferenciaCaja
    extra = 0
    fields = ("medio", "esperado", "contado", "diferencia", "motivo", "explicacion")
    readonly_fields = fields


@admin.register(SesionCaja)
class SesionCajaAdmin(SoloLectura, admin.ModelAdmin):
    inlines = [DiferenciaInline]
    list_display = ("id", "sucursal", "usuario", "estado", "monto_apertura",
                    "monto_esperado", "monto_contado", "diferencia", "abierta_en", "cerrada_en")
    list_filter = ("estado", "sucursal")
    readonly_fields = ("billetes_y_monedas", "conteos_previos", "aviso_diferencia")

    @admin.display(description="Billetes y monedas contados")
    def billetes_y_monedas(self, obj):
        filas = obj.desglose()
        if not filas:
            return "—"
        f = lambda n: f"{n:,}".replace(",", ".")
        return "; ".join(f"{n} × ₡{f(v)} = ₡{f(st)}" for v, n, st in filas)


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(SoloLectura, admin.ModelAdmin):
    list_display = ("fecha", "sesion", "tipo", "monto", "referencia", "descripcion", "usuario")
    list_filter = ("tipo",)
    search_fields = ("referencia", "descripcion")


@admin.register(DiferenciaCaja)
class DiferenciaCajaAdmin(SoloLectura, admin.ModelAdmin):
    list_display = ("sesion", "medio", "esperado", "contado", "diferencia", "motivo", "explicacion")
    list_filter = ("medio", "motivo")
    search_fields = ("explicacion",)


@admin.register(RetiroCaja)
class RetiroCajaAdmin(SoloLectura, admin.ModelAdmin):
    """Efectivo sacado para depositar (02/11/2026). Se registra y se marca
    depositado desde Caja → Sacar efectivo, no desde aquí."""
    list_display = ("id", "sesion", "monto", "usuario", "creado_en", "estado", "depositado_en", "comprobante")
    list_filter = ("estado",)
    search_fields = ("comprobante", "nota")
