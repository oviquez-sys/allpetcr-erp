"""Admin de campañas: para consultar y para el caso raro de corregir un dato.
El trabajo de todos los días se hace en las pantallas de /campanas/."""
from django.contrib import admin

from .models import (Adjudicacion, Campana, CanastaProducto, EntregaPremio, MovimientoNumeros, NumerosVenta,
                     Participante, Sorteo)


class SoloLectura(admin.ModelAdmin):
    """Lo que respalda un sorteo no se edita ni se borra desde el admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Campana)
class CampanaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "estado", "inicio", "cierre", "sorteo_en", "es_demo")
    list_filter = ("estado", "es_demo")
    readonly_fields = ("estado", "es_demo", "activada_en", "activada_por", "finalizada_en")
    prepopulated_fields = {"slug": ("nombre",)}

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Participante)
class ParticipanteAdmin(SoloLectura):
    list_display = ("cliente", "campana", "canal", "origen_visita", "creado_en")
    list_filter = ("campana", "canal")
    search_fields = ("cliente__nombre", "cliente__telefono", "cliente__email")


@admin.register(NumerosVenta)
class NumerosVentaAdmin(SoloLectura):
    list_display = ("documento", "participante", "canal", "monto_evaluado", "monto_vigente", "habituales", "bono",
                    "revertidos", "fecha")
    list_filter = ("campana", "canal")
    search_fields = ("documento", "participante__cliente__nombre")


@admin.register(MovimientoNumeros)
class MovimientoNumerosAdmin(SoloLectura):
    list_display = ("creado_en", "participante", "tipo", "cantidad", "motivo", "usuario")
    list_filter = ("campana", "tipo")
    search_fields = ("participante__cliente__nombre", "motivo")


@admin.register(Sorteo)
class SorteoAdmin(SoloLectura):
    list_display = ("campana", "congelada_en", "total_participantes", "total_numeros", "realizado_en",
                    "numero_ganador")


@admin.register(Adjudicacion)
class AdjudicacionAdmin(SoloLectura):
    list_display = ("sorteo", "orden", "participante", "numero", "estado", "vence_en")


@admin.register(EntregaPremio)
class EntregaPremioAdmin(SoloLectura):
    list_display = ("sorteo", "recibe_nombre", "version", "costo", "entregado_en", "entregado_por")


admin.site.register(CanastaProducto)
