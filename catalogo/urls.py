from django.urls import path

from . import views

app_name = "catalogo"

urlpatterns = [
    path("", views.precios, name="precios"),
    path("<int:pk>/", views.precio_producto, name="precio_producto"),
]
