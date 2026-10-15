from django.urls import path

from . import views

app_name = "manada"

urlpatterns = [
    path("clientes/", views.clientes, name="clientes"),
    path("clientes/<int:cliente_id>/", views.ficha, name="ficha"),
    path("duplicados/", views.duplicados, name="duplicados"),
    path("duplicados/<int:aviso_id>/resolver/", views.resolver_duplicado, name="resolver_duplicado"),
    path("mascotas/", views.mascotas, name="mascotas"),
    path("exportar/", views.exportar, name="exportar"),
    path("recordatorios/", views.recordatorios, name="recordatorios"),
    path("promociones/", views.promociones, name="promociones"),
]
