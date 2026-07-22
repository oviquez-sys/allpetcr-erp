"""Servicios del catálogo.

Única puerta para cambiar el precio de venta de un producto. Regla:
cada cambio queda registrado (quién, cuándo, de cuánto a cuánto, por qué) en
CambioPrecio, en la misma transacción que actualiza el producto. Así el
historial de precios es auditable y nadie mueve precios sin dejar rastro.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CambioPrecio, Producto


@transaction.atomic
def cambiar_precio(*, producto, nuevo_precio, usuario=None, motivo="") -> Producto:
    """Cambia el precio de venta y registra el cambio. Devuelve el producto.

    Lanza ValidationError si el precio es negativo o igual al actual (no tiene
    sentido registrar un 'cambio' que no cambia nada)."""
    nuevo = Decimal(str(nuevo_precio))
    if nuevo < 0:
        raise ValidationError("El precio no puede ser negativo.")

    # Bloqueo de fila para que dos cambios simultáneos no se pisen.
    producto = Producto.objects.select_for_update().get(pk=producto.pk)
    anterior = producto.precio_venta
    if nuevo == anterior:
        raise ValidationError(f"El precio nuevo (₡{nuevo}) es igual al actual. No hay nada que cambiar.")

    CambioPrecio.objects.create(
        producto=producto,
        valor_anterior=anterior,
        valor_nuevo=nuevo,
        costo_al_momento=producto.costo_promedio,
        motivo=motivo.strip(),
        usuario=usuario,
    )
    producto.precio_venta = nuevo
    producto.save(update_fields=["precio_venta", "actualizado_en"])
    return producto
