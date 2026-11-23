"""Admin de tareas: para ajustar el plan y la rutina sin tocar código.

Lo de todos los días se marca en /tareas/; acá se corrige lo que el plan dice.
"""
from django.contrib import admin

from . import servicios
from .models import Dia, Plan, Rutina, Semana, Tarea


class SemanaEnLinea(admin.StackedInline):
    model = Semana
    extra = 0


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("nombre", "inicio", "fin", "hito", "hito_fecha", "activo")
    list_filter = ("activo",)
    inlines = [SemanaEnLinea]


@admin.register(Dia)
class DiaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "plan", "etiqueta", "historias", "tienda_cerrada")
    list_filter = ("plan", "tienda_cerrada")
    date_hierarchy = "fecha"


@admin.register(Rutina)
class RutinaAdmin(admin.ModelAdmin):
    list_display = ("titulo", "hora", "responsable", "dias", "minimo", "activa", "desde", "hasta")
    list_filter = ("activa", "responsable", "minimo")
    ordering = ("orden", "id")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Lo de hoy en adelante que nadie marcó toma el texto nuevo; lo
        # pasado queda como se pidió ese día.
        if change:
            servicios.refrescar_rutina(obj)


@admin.register(Tarea)
class TareaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "titulo", "responsable", "tipo", "estado", "marcada_por", "marcada_en")
    list_filter = ("estado", "responsable", "tipo", "a_mano")
    search_fields = ("titulo", "detalle", "nota")
    date_hierarchy = "fecha"
    raw_id_fields = ("plan", "rutina")
    readonly_fields = ("marcada_por", "marcada_en", "creada_por", "creada_en", "actualizada_en")
