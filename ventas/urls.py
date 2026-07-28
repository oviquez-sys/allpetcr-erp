from django.urls import path

from . import views

app_name = "ventas"

urlpatterns = [
    path("", views.pos, name="pos"),
    path("vender/", views.vender, name="vender"),
    path("tiquete/<int:factura_id>/", views.tiquete, name="tiquete"),
    path("factura/<int:factura_id>/", views.factura, name="factura"),
    path("factura/<int:factura_id>/enviar/", views.factura_enviar, name="factura_enviar"),
    path("<int:factura_id>/anular/", views.anular, name="anular"),
    path("<int:factura_id>/devolver/", views.devolver, name="devolver"),
    path("cliente/<int:cliente_id>/estado-cuenta/", views.estado_cuenta, name="estado_cuenta"),
    path("cxc/<int:documento_id>/abonar/", views.abonar, name="abonar"),
]
