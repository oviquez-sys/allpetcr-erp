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
    path("api/chat/", views.chat_claude, name="chat_claude"),
]
