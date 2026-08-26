from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("actividad/", views.actividad, name="actividad"),
    path("reportes/", views.reportes, name="reportes"),
    path("reportes/mas-vendidos/", views.reporte_mas_vendidos, name="reporte_mas_vendidos"),
    path("reportes/stock/", views.reporte_stock, name="reporte_stock"),
    path("reportes/inventario/", views.reporte_inventario, name="reporte_inventario"),
    path("reportes/reposicion/", views.reporte_reposicion, name="reporte_reposicion"),
    path("reportes/arqueo/", views.reporte_arqueo, name="reporte_arqueo"),
    # Evidencia de los indicadores del Inicio: cada KPI se puede abrir para
    # ver de dónde sale el número y qué registros lo componen.
    path("evidencia/caja/", views.evidencia_caja, name="evidencia_caja"),
    path("evidencia/medios-de-pago/", views.evidencia_medios, name="evidencia_medios"),
    path("evidencia/por-cobrar/", views.evidencia_cxc, name="evidencia_cxc"),
    path("api/chat/", views.chat_claude, name="chat_claude"),
]
