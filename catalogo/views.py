"""Pantallas de precios: cambiar el precio de venta (solo gerente) y ver el
historial de cambios de precio y de costo (este último, desde el kardex)."""
import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import redirect, render

from core.roles import GERENTE, rol_requerido
from core.tenancy import documento_de_empresa, empresa_actual

from .consultas import pidio_agotados, productos_visibles
from .models import Producto
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
