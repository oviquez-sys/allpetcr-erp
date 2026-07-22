from django.urls import path

from . import views

app_name = "contabilidad"

urlpatterns = [
    path("libro-diario/", views.libro_diario, name="libro_diario"),
    path("balance/", views.balance_comprobacion, name="balance"),
    path("cierres/", views.cierres, name="cierres"),
    path("estado-resultados/", views.estado_resultados, name="estado_resultados"),
    path("iva-trimestral/", views.iva_trimestral, name="iva_trimestral"),
]
