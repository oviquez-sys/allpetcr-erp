"""Pantallas de precios: cambiar el precio de venta (solo gerente) y ver el
historial de cambios de precio y de costo (este último, desde el kardex)."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from core.roles import GERENTE, rol_requerido

from .models import Producto
from .services import cambiar_precio


@rol_requerido(GERENTE)
def precios(request):
    """Buscador de productos para revisar/ajustar precios."""
    q = (request.GET.get("q") or "").strip()
    productos = Producto.objects.filter(activo=True)
    if q:
        productos = productos.filter(
            Q(nombre__icontains=q) | Q(sku__icontains=q) | Q(codigo_barras__icontains=q)
        )
    productos = productos.order_by("nombre")[:60]
    return render(request, "catalogo/precios.html", {"productos": productos, "q": q})


@rol_requerido(GERENTE)
def precio_producto(request, pk):
    """Detalle de un producto: cambiar el precio (POST) y ver ambos historiales."""
    producto = get_object_or_404(Producto, pk=pk)

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
            messages.error(request, f"No se pudo cambiar el precio: {e}")

    producto.refresh_from_db()
    cambios = producto.cambios_precio.select_related("usuario")[:50]
    # Histórico de costo: cada entrada del kardex guarda el costo resultante.
    movimientos_costo = (
        producto.kardex.select_related("usuario")
        .order_by("-fecha", "-id")[:50]
    )
    margen = None
    if producto.precio_venta:
        margen = (producto.precio_venta - producto.costo_promedio) / producto.precio_venta * 100
    return render(request, "catalogo/precio_producto.html", {
        "producto": producto,
        "cambios": cambios,
        "movimientos_costo": movimientos_costo,
        "margen": margen,
    })
