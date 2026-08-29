from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("catalogo/productos/", views.CatalogoProductosView.as_view(), name="catalogo_productos"),
    path("catalogo/productos/<str:sku>/", views.ProductoDetalleView.as_view(), name="catalogo_producto_detalle"),
    path("catalogo/productos/<str:sku>/disponibilidad/", views.DisponibilidadView.as_view(), name="disponibilidad"),
    path("catalogo/avisos-disponibilidad/", views.AvisoDisponibilidadView.as_view(), name="aviso_disponibilidad"),
    path("pedidos/reservar-stock/", views.ReservarStockView.as_view(), name="reservar_stock"),
    path("pedidos/", views.PedidosView.as_view(), name="pedidos"),
    path("pedidos/<str:numero>/estado/", views.EstadoPedidoView.as_view(), name="pedido_estado"),
]
