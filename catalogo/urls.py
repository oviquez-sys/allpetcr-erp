from django.urls import path

from . import views

app_name = "catalogo"

urlpatterns = [
    path("", views.precios, name="precios"),
    path("<int:pk>/", views.precio_producto, name="precio_producto"),
    path("completar/", views.completar_catalogo, name="completar"),
    path("completar/excel/", views.completar_excel, name="completar_excel"),
    path("completar/subir/", views.completar_subir, name="completar_subir"),
    path("completar/confirmar/", views.completar_confirmar, name="completar_confirmar"),
]
