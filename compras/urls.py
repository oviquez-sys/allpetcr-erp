from django.urls import path

from . import views

app_name = "compras"

urlpatterns = [
    path("", views.nueva, name="nueva"),
    path("registrar/", views.registrar, name="registrar"),
    path("producto-nuevo/", views.producto_nuevo, name="producto_nuevo"),
    path("<int:compra_id>/anular/", views.anular, name="anular"),
]
