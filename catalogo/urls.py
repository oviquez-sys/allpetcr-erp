from django.urls import path

from . import views, views_promociones

app_name = "catalogo"

urlpatterns = [
    path("", views.precios, name="precios"),
    path("<int:pk>/", views.precio_producto, name="precio_producto"),
    path("completar/", views.completar_catalogo, name="completar"),
    path("completar/excel/", views.completar_excel, name="completar_excel"),
    path("completar/subir/", views.completar_subir, name="completar_subir"),
    path("completar/confirmar/", views.completar_confirmar, name="completar_confirmar"),
    path("sin-ficha/", views.alimentos_sin_ficha, name="sin_ficha"),
    path("promociones/", views_promociones.lista, name="promociones"),
    path("promociones/<int:pk>/", views_promociones.detalle, name="promocion"),
    path("promociones/<int:pk>/lista/", views_promociones.lista_para_marcar, name="promocion_lista"),
]
