"""Servicio de dominio del inventario.

Única puerta de entrada para mover stock. Reglas implementadas aquí
(y en ningún otro lugar):

1. Transaccional: el movimiento, el stock y el costo se confirman juntos
   o no se confirma nada.
2. No se permite stock negativo (ValidationError); el override auditado
   llegará con el POS (S3) como permiso explícito.
3. Costo promedio ponderado: se recalcula solo en entradas con costo.
4. El kardex guarda stock y costo resultantes: historial auditable.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from catalogo.models import Producto

from .models import Bodega, MovimientoInventario


@transaction.atomic
def registrar_movimiento(
    *,
    producto: Producto,
    bodega: Bodega,
    tipo: str,
    cantidad: Decimal,
    costo_unitario: Decimal = Decimal("0"),
    referencia: str = "",
    motivo: str = "",
    usuario=None,
) -> MovimientoInventario:
    cantidad = Decimal(cantidad)
    costo_unitario = Decimal(costo_unitario)
    if cantidad == 0:
        raise ValidationError("La cantidad no puede ser cero.")

    # Bloqueo de fila: dos cajas no pueden mover el mismo producto a la vez.
    producto = Producto.objects.select_for_update().get(pk=producto.pk)

    nuevo_stock = producto.stock_actual + cantidad
    if nuevo_stock < 0:
        raise ValidationError(
            f"Stock insuficiente de {producto.sku} — {producto.nombre}: "
            f"hay {producto.stock_actual}, se pidió sacar {abs(cantidad)}. "
            "No se permite inventario negativo."
        )

    # Costo promedio ponderado: solo cambia con entradas que traen costo.
    if cantidad > 0 and costo_unitario > 0:
        valor_actual = producto.stock_actual * producto.costo_promedio
        valor_entrada = cantidad * costo_unitario
        nuevo_costo = ((valor_actual + valor_entrada) / nuevo_stock).quantize(Decimal("0.01"))
    else:
        nuevo_costo = producto.costo_promedio

    movimiento = MovimientoInventario.objects.create(
        producto=producto,
        bodega=bodega,
        tipo=tipo,
        cantidad=cantidad,
        costo_unitario=costo_unitario,
        costo_promedio_resultante=nuevo_costo,
        stock_resultante=nuevo_stock,
        referencia=referencia,
        motivo=motivo,
        usuario=usuario,
    )
    producto.stock_actual = nuevo_stock
    producto.costo_promedio = nuevo_costo
    producto.save(update_fields=["stock_actual", "costo_promedio", "actualizado_en"])
    return movimiento
