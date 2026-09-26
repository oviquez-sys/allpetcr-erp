from django.urls import path

from . import agente, views

app_name = "impresion"

urlpatterns = [
    path("tiquete/<int:factura_id>/", views.tiquete, name="tiquete"),
    path("etiquetas/", views.etiquetas, name="etiquetas"),
    path("etiquetas/compra/<int:compra_id>/", views.etiquetas_compra, name="etiquetas_compra"),
    path("etiqueta/<int:producto_id>/", views.etiqueta_producto, name="etiqueta_producto"),
    path("codigo/<int:producto_id>.png", views.codigo_png, name="codigo_png"),
    path("estado/", views.estado, name="estado"),
    path("trabajo/<int:trabajo_id>/", views.estado_trabajo, name="estado_trabajo"),
    # Puertas del agente de la tienda. No las abre una persona: ver agente.py.
    path("agente/pendientes/", agente.pendientes, name="agente_pendientes"),
    path("agente/resultado/", agente.resultado, name="agente_resultado"),
]
