from django.urls import path

from . import views

app_name = "inventario"

urlpatterns = [
    path("ajuste/", views.ajuste_inventario, name="ajuste"),
    path("ajustes/", views.ajustes, name="ajustes"),
    path("ajustes/<int:producto_id>/", views.ajuste_producto, name="ajuste_producto"),
    path("etiquetas/", views.etiquetas, name="etiquetas"),
    path("etiquetas/<int:producto_id>/marcar/", views.marcar_etiqueta, name="marcar_etiqueta"),
    path("etiquetas/marcar-lote/", views.marcar_etiquetas_lote, name="marcar_etiquetas_lote"),
    path("agotados/", views.agotados, name="agotados"),
    path("agotados/excel/", views.agotados_excel, name="agotados_excel"),
    path("vendido/", views.vendido, name="vendido"),
    path("vendido/excel/", views.vendido_excel, name="vendido_excel"),
    path("vencimientos/", views.vencimientos, name="vencimientos"),
    path("codigos/", views.codigos_barras, name="codigos"),
]
