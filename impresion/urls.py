from django.urls import path

from . import views

app_name = "impresion"

urlpatterns = [
    path("tiquete/<int:factura_id>/", views.tiquete, name="tiquete"),
    path("etiquetas/", views.etiquetas, name="etiquetas"),
    path("etiqueta/<int:producto_id>/", views.etiqueta_producto, name="etiqueta_producto"),
    path("codigo/<int:producto_id>.png", views.codigo_png, name="codigo_png"),
    path("estado/", views.estado, name="estado"),
]
