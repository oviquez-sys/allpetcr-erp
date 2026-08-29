"""Servicios de dominio de pedidos (Bloque 2, 2026-08-28).

Dos transacciones separadas a propósito:

- `reservar_stock`: durante el checkout, ANTES de pagar. Bloquea unidades
  por un rato (ver `ReservaStock.PLAZO_MINUTOS`) para que dos compradores no
  se disputen la última unidad mientras uno de los dos está tipeando el
  número de tarjeta.
- `crear_pedido`: cuando la pasarela YA confirmó el pago. Descuenta el
  kardex de verdad y libera la reserva. Idempotente por `referencia_pago`
  (ver docstring de la función) porque las pasarelas reenvían el mismo aviso
  de pago más de una vez.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from catalogo.models import Producto
from inventario.models import Bodega
from inventario.services import registrar_movimiento
# Se reutiliza el motor fiscal de ventas (única función que decide el
# desglose de impuesto, según la regla del proyecto) en vez de duplicarlo:
# un pedido en línea es, fiscalmente, una venta más.
from ventas.models import Consecutivo
from ventas.services import _desglose_fiscal

from .models import CambioEstadoPedido, LineaPedido, Pedido, ReservaStock


@transaction.atomic
def reservar_stock(*, producto: Producto, cantidad, token_carrito: str) -> ReservaStock:
    cantidad = Decimal(str(cantidad))
    if cantidad <= 0:
        raise ValidationError("La cantidad a reservar debe ser mayor que cero.")
    if not token_carrito:
        raise ValidationError("Falta el identificador del carrito.")

    # Bloqueo de fila: dos checkouts del mismo producto no se calculan
    # "disponible" a la vez con el mismo número viejo (la misma protección
    # que ya usa inventario.services.registrar_movimiento).
    producto = Producto.objects.select_for_update().get(pk=producto.pk)
    ahora = timezone.now()

    # Una reserva vencida no debe seguir restando disponibilidad a nadie.
    ReservaStock.objects.filter(producto=producto, expira_en__lte=ahora).delete()

    reservado_por_otros = (
        ReservaStock.objects.filter(producto=producto)
        .exclude(token_carrito=token_carrito)
        .aggregate(total=Sum("cantidad"))["total"]
        or Decimal("0")
    )
    disponible = producto.stock_actual - reservado_por_otros
    if cantidad > disponible:
        raise ValidationError(
            f"Sin stock suficiente de {producto.sku} — {producto.nombre}: "
            f"disponible {disponible}, se pidió {cantidad}."
        )

    reserva, _ = ReservaStock.objects.update_or_create(
        producto=producto, token_carrito=token_carrito,
        defaults={"cantidad": cantidad, "expira_en": ahora + timedelta(minutes=ReservaStock.PLAZO_MINUTOS)},
    )
    return reserva


@transaction.atomic
def crear_pedido(
    *, empresa, sucursal, cliente_nombre, cliente_telefono, lineas,
    token_carrito="", cliente_identificacion="", cliente_email="",
    direccion_texto="", direccion_lat=None, direccion_lng=None,
    referencia_pago="", usuario=None,
) -> Pedido:
    """Crea el pedido YA PAGADO: descuenta el kardex de una vez (tipo VEN,
    igual que una venta de mostrador) y libera la reserva del carrito.

    Idempotencia: si `referencia_pago` ya está asociada a un pedido de esta
    empresa, se devuelve ESE pedido sin tocar inventario de nuevo. Es lo que
    exige un webhook de pasarela de pago, que puede reenviar el mismo aviso
    más de una vez (ver Bloque 3).
    """
    if referencia_pago:
        # Atajo rápido para el caso común (no hay condición de carrera que
        # importe acá: si dos hilos pasan este filtro a la vez, el
        # IntegrityError de abajo resuelve cuál gana de verdad).
        existente = Pedido.objects.filter(empresa=empresa, referencia_pago=referencia_pago).first()
        if existente is not None:
            return existente

    if not lineas:
        raise ValidationError("El pedido no tiene productos.")

    bodega = Bodega.principal_de(sucursal)
    if bodega is None:
        raise ValidationError("La sucursal no tiene una bodega configurada.")

    numero = Consecutivo.tomar(empresa, "PED")
    try:
        # Saveproint propio: si el INSERT choca con la restricción única de
        # (empresa, referencia_pago) porque otro hilo llegó primero con el
        # MISMO webhook, se revierte solo este intento —no todo lo demás
        # que ya haya pasado en la transacción— y se devuelve el pedido que
        # ya existe, sin descontar el inventario una segunda vez.
        with transaction.atomic():
            pedido = Pedido.objects.create(
                empresa=empresa, sucursal=sucursal, numero=numero,
                cliente_nombre=cliente_nombre, cliente_identificacion=cliente_identificacion,
                cliente_telefono=cliente_telefono, cliente_email=cliente_email,
                direccion_texto=direccion_texto, direccion_lat=direccion_lat, direccion_lng=direccion_lng,
                referencia_pago=referencia_pago,
            )
    except IntegrityError:
        return Pedido.objects.get(empresa=empresa, referencia_pago=referencia_pago)

    subtotal = impuesto = Decimal("0")
    for linea in lineas:
        producto = Producto.objects.select_for_update().get(pk=linea["producto_id"], empresa=empresa)
        cantidad = Decimal(str(linea["cantidad"]))
        if cantidad <= 0:
            raise ValidationError("La cantidad de cada línea debe ser mayor que cero.")
        precio_unitario = producto.precio_venta
        total_linea = (cantidad * precio_unitario).quantize(Decimal("0.01"))
        sub_l, imp_l = _desglose_fiscal(empresa, producto, total_linea)
        LineaPedido.objects.create(
            pedido=pedido, producto=producto, cantidad=cantidad,
            precio_unitario=precio_unitario, total=total_linea,
        )
        registrar_movimiento(
            producto=producto, bodega=bodega, tipo="VEN", cantidad=-cantidad,
            referencia=numero, usuario=usuario,
        )
        subtotal += sub_l
        impuesto += imp_l

    pedido.subtotal = subtotal
    pedido.impuesto = impuesto
    pedido.total = subtotal + impuesto
    pedido.save(update_fields=["subtotal", "impuesto", "total"])

    if token_carrito:
        ReservaStock.objects.filter(token_carrito=token_carrito).delete()

    CambioEstadoPedido.objects.create(
        pedido=pedido, estado_anterior=Pedido.Estado.PAGO_CONFIRMADO,
        estado_nuevo=Pedido.Estado.PAGO_CONFIRMADO,
        nota="Pedido creado (pago confirmado por la pasarela)", usuario=usuario,
    )
    return pedido


@transaction.atomic
def cambiar_estado(*, pedido: Pedido, nuevo_estado: str, usuario=None, nota: str = "") -> Pedido:
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    permitidos = Pedido.TRANSICIONES.get(pedido.estado, set())
    if nuevo_estado not in permitidos:
        raise ValidationError(
            f"No se puede pasar el pedido {pedido.numero} de "
            f"'{pedido.get_estado_display()}' a '{Pedido.Estado(nuevo_estado).label}'."
        )
    anterior = pedido.estado
    pedido.estado = nuevo_estado
    pedido.save(update_fields=["estado"])
    CambioEstadoPedido.objects.create(
        pedido=pedido, estado_anterior=anterior, estado_nuevo=nuevo_estado,
        nota=nota, usuario=usuario,
    )
    return pedido
