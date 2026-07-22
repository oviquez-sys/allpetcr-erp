from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "ALLPETCR ERP"
admin.site.site_title = "ALLPETCR ERP"
admin.site.index_title = "Administración — núcleo v1"

urlpatterns = [
    path("", include("core.urls")),
    path("pos/", include("ventas.urls")),
    path("caja/", include("caja.urls")),
    path("compras/", include("compras.urls")),
    path("inventario/", include("inventario.urls")),
    path("precios/", include("catalogo.urls")),
    path("contabilidad/", include("contabilidad.urls")),
    path("admin/", admin.site.urls),
]

# Servir las fotos de productos en desarrollo (runserver).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
