from django.urls import path

from . import views

app_name = "caja"

urlpatterns = [
    path("abrir/", views.abrir, name="abrir"),
    path("cerrar/", views.cerrar, name="cerrar"),
    path("cierre/<int:sesion_id>/imprimir/", views.imprimir, name="imprimir_cierre"),
    path("retiro/", views.retiro, name="retiro"),
]
