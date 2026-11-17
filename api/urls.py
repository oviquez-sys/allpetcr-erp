from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("catalogo/productos/", views.CatalogoProductosView.as_view(), name="catalogo_productos"),
    path("catalogo/categorias/", views.CategoriasView.as_view(), name="catalogo_categorias"),
    path("catalogo/productos/<str:sku>/", views.ProductoDetalleView.as_view(), name="catalogo_producto_detalle"),
    path("catalogo/productos/<str:sku>/disponibilidad/", views.DisponibilidadView.as_view(), name="disponibilidad"),
    path("catalogo/avisos-disponibilidad/", views.AvisoDisponibilidadView.as_view(), name="aviso_disponibilidad"),
    path("pedidos/reservar-stock/", views.ReservarStockView.as_view(), name="reservar_stock"),
    path("pedidos/", views.PedidosView.as_view(), name="pedidos"),
    path("pedidos/<str:numero>/estado/", views.EstadoPedidoView.as_view(), name="pedido_estado"),
    path("manada/registro/", views.ManadaRegistroView.as_view(), name="manada_registro"),
    path("manada/mascotas/", views.ManadaMascotasView.as_view(), name="manada_mascotas"),
    path("manada/regalia/", views.ManadaRegaliaView.as_view(), name="manada_regalia"),
    # Campañas con sorteo (16/11/2026)
    path("campana/", views.CampanaView.as_view(), name="campana"),
    path("campana/inscripcion/", views.CampanaInscripcionView.as_view(), name="campana_inscripcion"),
    path("campana/participante/", views.CampanaParticipanteView.as_view(), name="campana_participante"),
    path("campana/beneficios/", views.CampanaBeneficiosView.as_view(), name="campana_beneficios"),
    path("pedidos/por-confirmar/", views.PedidoPorConfirmarView.as_view(), name="pedido_por_confirmar"),
    path("pedidos/por-confirmar/<str:numero>/", views.PedidoPorConfirmarEstadoView.as_view(),
         name="pedido_por_confirmar_estado"),
]
