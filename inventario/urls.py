from django.urls import path

from . import views

app_name = "inventario"

urlpatterns = [
    path("ajuste/", views.ajuste_inventario, name="ajuste"),
    path("etiquetas/", views.etiquetas, name="etiquetas"),
    path("etiquetas/<int:producto_id>/marcar/", views.marcar_etiqueta, name="marcar_etiqueta"),
    path("etiquetas/marcar-lote/", views.marcar_etiquetas_lote, name="marcar_etiquetas_lote"),
    path("codigos/", views.codigos_barras, name="codigos"),
]
