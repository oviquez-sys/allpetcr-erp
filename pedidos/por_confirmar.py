"""Pedidos web por confirmar: crear, cobrar en caja, cancelar.

Ver el docstring de `pedidos.models.PedidoPorConfirmar` para el porqué. En
corto: el sitio anota el pedido antes de mandarlo por WhatsApp y recibe un
número (WEB-12); la caja lo cobra con ese número y la venta queda marcada
como nacida en la web.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalogo.consultas import publicados_en_web

from .models import PedidoPorConfirmar

logger = logging.getLogger(__name__)

MAX_LINEAS = 60
# Un pedido que nadie cobró en este tiempo deja de salir en la lista de la
# caja (sigue en el admin). No se cancela solo: puede que el cliente vuelva.
DIAS_EN_LISTA = 15


def _nuevo_numero(empresa) -> str:
    """WEB-1, WEB-2… corto a propósito: se lee en un WhatsApp y se teclea en
    la caja. Mismo contador con bloqueo de fila que los cupones ALP-."""
    from ventas.models import Consecutivo

    with transaction.atomic():
        fila, _ = Consecutivo.objects.select_for_update().get_or_create(empresa=empresa, tipo="WEB")
        while True:
            numero = f"WEB-{fila.siguiente}"
            fila.siguiente += 1
            if not PedidoPorConfirmar.objects.filter(numero=numero).exists():
                break
        fila.save(update_fields=["siguiente"])
    return numero


def normalizar_numero(texto) -> str:
    """«web 12», «WEB12», «12» → WEB-12."""
    limpio = "".join(c for c in (texto or "").upper() if c.isalnum())
    if limpio.startswith("WEB"):
        limpio = limpio[3:]
    return f"WEB-{int(limpio)}" if limpio.isdigit() else ""


def lineas_con_precio(empresa, lineas):
    """[{sku, cantidad}] → (líneas con nombre y precio vigente, subtotal).
    El precio lo pone el ERP (con la oferta si hay): el sitio nunca manda
    precios, igual que en `crear_pedido`."""
    from catalogo.promociones import precio_vigente

    if not isinstance(lineas, list) or not lineas:
        raise ValidationError("El pedido no tiene productos.")
    if len(lineas) > MAX_LINEAS:
        raise ValidationError("El pedido tiene demasiados productos distintos.")
    salida, subtotal = [], Decimal("0")
    for linea in lineas:
        if not isinstance(linea, dict):
            raise ValidationError("Datos del pedido inválidos.")
        sku = str(linea.get("sku") or "").strip()
        try:
            cantidad = Decimal(str(linea.get("cantidad")))
        except (ArithmeticError, ValueError, TypeError):
            raise ValidationError(f"Cantidad inválida para {sku or 'un producto'}.")
        if cantidad <= 0 or cantidad != cantidad.to_integral_value() or cantidad > 999:
            raise ValidationError(f"Cantidad inválida para {sku or 'un producto'}.")
        # Solo lo publicado (18/11/2026): esto es el carrito del sitio.
        producto = publicados_en_web(empresa).filter(sku=sku).first()
        if producto is None:
            raise ValidationError(f"No existe un producto activo con el código {sku!r}.")
        precio = precio_vigente(producto)
        subtotal += (precio * cantidad).quantize(Decimal("0.01"))
        salida.append({"sku": producto.sku, "nombre": producto.nombre, "cantidad": int(cantidad),
                       "precio": str(precio), "producto_id": producto.pk})
    return salida, subtotal


@transaction.atomic
def crear(*, empresa, nombre, telefono, lineas, email="", entrega="RET", provincia="", canton="", distrito="",
          senas="", nota="", origen_visita="", clave=""):
    """Anota el pedido y devuelve (pedido, creado). Con la misma `clave`
    devuelve el que ya existía."""
    from campanas.reglas import _limpiar_origen
    from manada.identificar import identificar
    from manada.services import _limpiar_telefono

    clave = (clave or "").strip()[:64] or None
    if clave:
        ya = PedidoPorConfirmar.objects.filter(empresa=empresa, clave=clave).first()
        if ya is not None:
            return ya, False
    nombre = " ".join((nombre or "").split())[:150]
    if not nombre:
        raise ValidationError("Falta el nombre.")
    telefono = _limpiar_telefono(telefono)
    if not telefono:
        raise ValidationError("Falta el número de WhatsApp.")
    if entrega not in PedidoPorConfirmar.Entrega.values:
        raise ValidationError("La entrega tiene que ser retiro en tienda (RET) o envío (ENV).")
    if entrega == PedidoPorConfirmar.Entrega.ENVIO and not (canton or "").strip():
        raise ValidationError("Para un envío hace falta el cantón.")
    detalle, subtotal = lineas_con_precio(empresa, lineas)
    email = (email or "").strip().lower()[:254]
    # Solo se RECONOCE al cliente (no se crea ni se hace miembro): un pedido
    # que quizás nunca se pague no debe llenar la base de clientes.
    reconocido = identificar(empresa, telefono=telefono, correo=email).cliente
    try:
        with transaction.atomic():
            pedido = PedidoPorConfirmar.objects.create(
                empresa=empresa, numero=_nuevo_numero(empresa), clave=clave, cliente_nombre=nombre,
                cliente_telefono=telefono, cliente_email=email, cliente=reconocido, entrega=entrega,
                provincia=(provincia or "").strip()[:40], canton=(canton or "").strip()[:60],
                distrito=(distrito or "").strip()[:60], senas=(senas or "").strip()[:300],
                nota=(nota or "").strip()[:300], origen_visita=_limpiar_origen(origen_visita),
                lineas=detalle, subtotal_productos=subtotal,
            )
    except IntegrityError:
        return PedidoPorConfirmar.objects.get(empresa=empresa, clave=clave), False
    return pedido, True


def pendientes(empresa):
    """Los que la caja puede cobrar hoy, del más nuevo al más viejo."""
    desde = timezone.now() - timedelta(days=DIAS_EN_LISTA)
    return (PedidoPorConfirmar.objects.filter(empresa=empresa, estado=PedidoPorConfirmar.Estado.PENDIENTE,
                                              creado_en__gte=desde).select_related("cliente"))


def concretar(numero, factura, *, envio_costo=None):
    """Liga el pedido web con la venta que lo cobró. Va DENTRO de la
    transacción de la venta, pero no puede tumbarla: si el número no existe o
    ya se cobró, la venta queda igual (como venta de tienda) y se anota."""
    try:
        with transaction.atomic():
            pedido = (PedidoPorConfirmar.objects.select_for_update()
                      .filter(empresa=factura.empresa, numero=normalizar_numero(numero)).first())
            if pedido is None or pedido.estado != PedidoPorConfirmar.Estado.PENDIENTE:
                logger.warning("La venta %s decía venir del pedido web %r, que no está pendiente.",
                               factura.numero, numero)
                return None
            from campanas.reglas import beneficios, vigente

            pedido.factura = factura
            pedido.estado = PedidoPorConfirmar.Estado.CONCRETADO
            pedido.concretado_en = timezone.now()
            if pedido.cliente_id is None and factura.cliente_id:
                pedido.cliente = factura.cliente
            pedido.envio_costo = max(Decimal("0"), Decimal(str(envio_costo or 0))).quantize(Decimal("0.01"))
            campana = vigente(factura.empresa)
            if campana is not None and pedido.entrega == PedidoPorConfirmar.Entrega.ENVIO:
                pedido.envio_gratis = beneficios(
                    campana, monto=factura.total, participa=False, entrega="ENV",
                    canton=pedido.canton, distrito=pedido.distrito)["envio"]["gratis"]
            pedido.save()
            return pedido
    except Exception:  # noqa: BLE001 — la venta manda; ver docstring
        logger.exception("No se pudo ligar el pedido web %r con la venta %s", numero, factura.numero)
        return None


def reabrir_por_anulacion(factura):
    """La venta que cobró el pedido se anuló: el pedido vuelve a quedar por
    confirmar (se puede cobrar de nuevo o cancelar)."""
    PedidoPorConfirmar.objects.filter(factura=factura).update(
        factura=None, estado=PedidoPorConfirmar.Estado.PENDIENTE, concretado_en=None,
        envio_gratis=False, envio_costo=0,
    )


@transaction.atomic
def cancelar(pedido, motivo=""):
    pedido = PedidoPorConfirmar.objects.select_for_update().get(pk=pedido.pk)
    if pedido.estado == PedidoPorConfirmar.Estado.CONCRETADO:
        raise ValidationError("Ese pedido ya se cobró: para deshacerlo, anulá o devolvé la venta.")
    pedido.estado = PedidoPorConfirmar.Estado.CANCELADO
    pedido.cancelado_en = timezone.now()
    pedido.motivo_cancelacion = (motivo or "").strip()[:200]
    pedido.save(update_fields=["estado", "cancelado_en", "motivo_cancelacion"])
    return pedido
