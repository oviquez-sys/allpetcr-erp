"""Pantallas de catálogo: precios (cambiar el precio de venta y ver el
historial de precio y costo) y completar datos faltantes (mascota,
categoría, descripción — ver catalogo/completar.py). Solo gerente."""
import logging

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.roles import GERENTE, rol_requerido
from core.tenancy import documento_de_empresa, empresa_actual

from . import completar
from .consultas import pidio_agotados, productos_visibles
from .models import Categoria, Producto
from .services import cambiar_precio

logger = logging.getLogger(__name__)


@rol_requerido(GERENTE)
def precios(request):
    """Buscador de productos para revisar/ajustar precios."""
    q = (request.GET.get("q") or "").strip()
    agotados = pidio_agotados(request)
    # Filtro por empresa (auditoría 2026-07-28, ARQ-01): esta era una de las
    # tres consultas de producto que no lo aplicaban. Hoy da igual porque hay
    # una sola empresa; el día que haya dos, este listado mostraría precios
    # y costos de la otra.
    #
    # Filtro por existencias (regla del 02/08/2026, ver catalogo/consultas.py).
    # Con ?agotados=1 se ven también los que están en cero: revisar el precio
    # de algo antes de reponerlo es un caso real, y por eso acá la excepción
    # es un botón y no una prohibición.
    productos = productos_visibles(empresa_actual(request), incluir_agotados=agotados)
    if q:
        productos = productos.filter(
            Q(nombre__icontains=q) | Q(sku__icontains=q) | Q(codigo_barras__icontains=q)
        )
    productos = list(productos.order_by("nombre")[:60])
    return render(request, "catalogo/precios.html", {
        "productos": productos, "q": q, "agotados": agotados,
    })


@rol_requerido(GERENTE)
def precio_producto(request, pk):
    """Detalle de un producto: cambiar el precio (POST) y ver ambos historiales."""
    producto = documento_de_empresa(Producto, request, pk=pk)

    if request.method == "POST":
        try:
            cambiar_precio(
                producto=producto,
                nuevo_precio=request.POST.get("nuevo_precio") or "0",
                usuario=request.user,
                motivo=request.POST.get("motivo") or "",
            )
            messages.success(request, "Precio actualizado. Quedó registrado en el historial.")
            return redirect("catalogo:precio_producto", pk=producto.pk)
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
        except Exception as e:  # noqa: BLE001
            # Se sigue atrapando todo para no dejar al gerente frente a una
            # pantalla de error, pero ahora queda el rastro completo en el log
            # (auditoría 2026-07-28, BE-03). Un cambio de precio que falla sin
            # explicación es imposible de diagnosticar después.
            logger.exception("Fallo al cambiar el precio de %s", producto.sku)
            messages.error(request, f"No se pudo cambiar el precio: {e}")

    producto.refresh_from_db()
    cambios = producto.cambios_precio.select_related("usuario")[:50]
    # Histórico de costo: cada entrada del kardex guarda el costo resultante.
    movimientos_costo = (
        producto.kardex.select_related("usuario")
        .order_by("-fecha", "-id")[:50]
    )
    return render(request, "catalogo/precio_producto.html", {
        "producto": producto,
        "cambios": cambios,
        "movimientos_costo": movimientos_costo,
    })


# --------------------------------------------------------------------------
# Completar catálogo (20/09/2026) — ver catalogo/completar.py
# --------------------------------------------------------------------------

_SAL_FIRMA = "catalogo.completar"
_VIGENCIA_FIRMA = 60 * 60  # una hora para revisar la vista previa y confirmar
_POR_PAGINA = 40


def _filtros(request):
    falta = request.GET.get("falta") or ""
    return (falta if falta in completar.CAMPOS else ""), pidio_agotados(request)


@rol_requerido(GERENTE)
def completar_catalogo(request):
    """Lista de productos con datos incompletos, editable en la misma tabla."""
    empresa = empresa_actual(request)
    falta, agotados = _filtros(request)

    if request.method == "POST":
        categorias = {c.pk: c for c in Categoria.objects.select_related("padre")}
        ids = [int(x) for x in request.POST.getlist("producto") if x.isdigit()]
        cambios = []
        for p in Producto.objects.filter(empresa=empresa, pk__in=ids).select_related("categoria", "categoria__padre"):
            cat_id = request.POST.get(f"c_{p.pk}") or ""
            cambios += completar.proponer(
                p,
                mascota=completar.normalizar_mascota(request.POST.get(f"m_{p.pk}")) or "",
                categoria=categorias.get(int(cat_id)) if cat_id.isdigit() else None,
                descripcion=request.POST.get(f"d_{p.pk}") or "",
            )
        tocados = completar.aplicar(empresa, [c.a_dict() for c in cambios])
        if tocados:
            messages.success(request, f"Listo: se actualizaron {tocados} producto(s). Los que quedaron completos ya no aparecen en la lista.")
        else:
            messages.info(request, "No había cambios que guardar.")
        return redirect(request.get_full_path())

    pagina = Paginator(completar.pendientes(empresa, falta=falta, incluir_agotados=agotados), _POR_PAGINA).get_page(request.GET.get("pagina"))
    filas = []
    for p in pagina:
        f = completar.faltantes(p)
        filas.append({"p": p, "falta": f, "etiquetas": [completar.ETIQUETA_CAMPO[x].lower() for x in f]})
    return render(request, "catalogo/completar.html", {
        "pagina": pagina,
        "filas": filas,
        "falta": falta,
        "agotados": agotados,
        "conteos": completar.conteos(empresa, incluir_agotados=agotados),
        "mascotas": completar.MASCOTAS,
        "categorias": completar.opciones_categoria(),
        "etiqueta_campo": completar.ETIQUETA_CAMPO,
    })


@rol_requerido(GERENTE)
def completar_excel(request):
    """Descarga los pendientes (con el mismo filtro de la pantalla)."""
    empresa = empresa_actual(request)
    falta, agotados = _filtros(request)
    contenido = completar.exportar_excel(completar.pendientes(empresa, falta=falta, incluir_agotados=agotados))
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = 'attachment; filename="catalogo_por_completar.xlsx"'
    return respuesta


@rol_requerido(GERENTE)
@require_POST
def completar_subir(request):
    """Paso 1 de 2: lee el Excel y muestra qué cambiaría. No guarda nada."""
    archivo = request.FILES.get("archivo")
    if archivo is None:
        messages.error(request, "Elegí el archivo de Excel antes de subirlo.")
        return redirect("catalogo:completar")
    revision = completar.revisar_excel(empresa_actual(request), archivo)
    firma = signing.dumps([c.a_dict() for c in revision.cambios], salt=_SAL_FIRMA, compress=True)
    return render(request, "catalogo/completar_revision.html", {
        "revision": revision,
        "firma": firma,
        "productos_afectados": len({c.sku for c in revision.cambios}),
        "etiqueta_campo": completar.ETIQUETA_CAMPO,
    })


@rol_requerido(GERENTE)
@require_POST
def completar_confirmar(request):
    """Paso 2 de 2: aplica exactamente lo que se mostró en la vista previa."""
    try:
        cambios = signing.loads(request.POST.get("firma") or "", salt=_SAL_FIRMA, max_age=_VIGENCIA_FIRMA)
    except signing.SignatureExpired:
        messages.error(request, "La vista previa venció (más de una hora). Subí el Excel de nuevo.")
        return redirect("catalogo:completar")
    except signing.BadSignature:
        messages.error(request, "No se pudo leer la vista previa. Subí el Excel de nuevo.")
        return redirect("catalogo:completar")
    tocados = completar.aplicar(empresa_actual(request), cambios)
    messages.success(request, f"Listo: se actualizaron {tocados} producto(s) desde el Excel.")
    return redirect("catalogo:completar")
