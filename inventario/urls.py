from django.urls import path

from . import views

app_name = "inventario"

urlpatterns = [
    path("ajuste/", views.ajuste_inventario, name="ajuste"),
    path("etiquetas/", views.etiquetas, name="etiquetas"),
]
