from django.urls import path

from . import views

app_name = "tareas"

urlpatterns = [
    path("", views.dia, name="dia"),
    path("agregar/", views.agregar, name="agregar"),
    path("<int:pk>/marcar/", views.marcar, name="marcar"),
    path("<int:pk>/guardar/", views.guardar, name="guardar"),
    path("<int:pk>/borrar/", views.borrar, name="borrar"),
]
