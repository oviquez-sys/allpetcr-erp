"""Indicadores del mes en el índice del panel de administración.

Qué problema resuelve
---------------------
El Inicio se abre decenas de veces por día desde el mostrador; el resumen del
mes (ganancia, ventas, margen, monitor del régimen simplificado) se mira una
vez al día o menos. Tenerlos juntos hacía que ninguno se leyera: el operativo
quedaba sepultado bajo el gerencial, y el gerencial se volvía paisaje.

Así que el resumen del mes se movió acá, a `/admin/`, que ya era el lugar
donde se entra a hacer trabajo administrativo, y que ya tenía su botón en el
acceso rápido del Inicio.

Por qué se envuelve la vista en vez de subclasear AdminSite
-----------------------------------------------------------
La alternativa ortodoxa —crear `class ERPAdminSite(admin.AdminSite)` y
reemplazar `admin.site`— obliga a re-registrar los ~15 modelos que hoy se
registran con `@admin.register` en cada app. Es más código, y sobre todo es
código que falla en silencio: si mañana alguien agrega un modelo con el
decorador de siempre, no aparece y nadie sabe por qué.

Acá se envuelve `admin.site.index`, que es la única vista que cambia.
`AdminSite.get_urls()` resuelve `self.index` cuando arma las rutas, y la
búsqueda de atributo encuentra primero el que se asigna a la instancia. Las
registraciones no se tocan, y un modelo nuevo sigue apareciendo solo.

El contexto se calcula SOLO en el índice, nunca en `each_context`: eso último
corre en cada pantalla del admin, y no tiene sentido pagar ocho agregados por
abrir el formulario de un producto.
"""
from django.contrib import admin

# Guarda de idempotencia: `ready()` puede ejecutarse más de una vez (el
# autoreload del servidor de desarrollo es el caso típico). Sin esto, cada
# pasada envolvería la vista ya envuelta y se apilarían capas.
_YA_INSTALADO = False


def _contexto_administrativo(request):
    """Indicadores del mes para el índice, o vacío si no corresponde.

    Devuelve un diccionario vacío —y la plantilla no dibuja nada— en tres
    casos: usuario sin rol de gerente, sin empresa configurada, o cualquier
    error de cálculo. El panel de administración tiene que abrir siempre:
    dejarlo caído por un indicador sería cambiar una comodidad por una avería.
    """
    from core.dashboard import indicadores
    from core.roles import es_gerente
    from core.tenancy import empresa_actual

    if not es_gerente(request.user):
        # El admin exige `is_staff`, que NO es lo mismo que ser gerente: un
        # cajero con permiso sobre una tabla entra igual. Sin este chequeo,
        # mover el resumen del mes acá lo habría expuesto a quien no lo veía
        # en el Inicio — un retroceso de permisos disfrazado de rediseño.
        return {}

    empresa = empresa_actual(request)
    if empresa is None:
        return {}

    try:
        datos = indicadores(empresa)
    except Exception:  # noqa: BLE001 — un indicador roto no tumba el admin
        return {}

    return {
        "ax_indicadores": True,
        "ax_empresa": empresa,
        **{k: datos[k] for k in (
            "utilidad_mes", "margen", "ventas_mes", "variacion_mes",
            "cxc_total", "compras_anio", "limite_rts", "pct_rts",
            "alerta_rts", "es_rts",
        ) if k in datos},
    }


def instalar():
    """Envuelve el índice del admin para que muestre el resumen del mes."""
    global _YA_INSTALADO
    if _YA_INSTALADO:
        return
    _YA_INSTALADO = True

    index_original = admin.site.index

    def index_con_indicadores(request, extra_context=None):
        contexto = dict(extra_context or {})
        contexto.update(_contexto_administrativo(request))
        return index_original(request, extra_context=contexto)

    admin.site.index = index_con_indicadores
