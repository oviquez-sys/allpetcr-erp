from django.urls import path

from . import views

app_name = "campanas"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.editar, name="nueva"),
    path("demostracion/", views.demostracion, name="demostracion"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/accion/", views.accion, name="accion"),
    path("<int:pk>/acta/", views.acta, name="acta"),
    path("<int:pk>/lista.csv", views.lista_csv, name="lista_csv"),
    path("<int:pk>/participantes.csv", views.participantes_csv, name="participantes_csv"),
]
