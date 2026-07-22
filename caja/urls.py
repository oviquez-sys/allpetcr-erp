from django.urls import path

from . import views

app_name = "caja"

urlpatterns = [
    path("abrir/", views.abrir, name="abrir"),
    path("cerrar/", views.cerrar, name="cerrar"),
]
