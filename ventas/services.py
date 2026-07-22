"""Servicios de dominio de ventas.

registrar_venta es LA transacción central del sistema: factura + kardex +
caja se confirman juntos o no se confirma nada. El motor fiscal (Fase 2 §6)
decide el desglose de impuestos según el régimen de la empresa:

- RTS (hoy): el precio es el total; no se desglosa IVA en la venta.
- Tradicional (futuro): el precio incluye IVA según la tarifa del producto;
  se desglosa subtotal e impuesto, y aquí se activará el adaptador de
  facturación electrónica v4.4.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from caja.models import MovimientoCaja, SesionCaja
from caja.services import registrar_movimiento_caja
from catalogo.models import Producto
from core.models import Empresa
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .models import Consecutivo, FacturaVenta, LineaVenta


def _desglose_fiscal(empresa, producto, total_linea):
    """Devuelve (subtotal, impuesto) de una línea según el régimen."""
    if empresa.regimen == Empresa.Regimen.SIMPLIFICADO:
        return total_linea, Decimal("0")
    tarifa = producto.impuesto.tarifa if producto.impuesto else Decimal("0")
    subtotal = (total_linea / (1 + tarifa / 100)).quantize(Decimal("0.01"))
    return subtotal, total_linea - subtotal


@transaction.atomic
def registrar_venta(*, sesion_caja, lineas, medio_pago, usuario, cliente=None,
                    permitir_bajo_costo=False) -> FacturaVenta:
    """lineas: iterable de dicts {"producto_id": int, "cantidad": Decimal}.

    permitir_bajo_costo: por defecto NO se puede vender un producto por debajo
    de su costo promedio (protege el margen y cierra un hueco de fraude: un
    cajero descontando de más). El gerente sí puede autorizarlo (la vista lo
    pasa en True cuando quien vende es gerente)."""
    # Releer la sesión desde la BD con bloqueo: el objeto en memoria puede
    # estar desactualizado (p. ej., la caja se cerró desde otra pantalla).
    sesion_caja = SesionCaja.objects.select_for_update().get(pk=sesion_caja.pk)
    if sesion_caja.estado != SesionCaja.Estado.ABIERTA:
        raise ValidationError("No hay una sesión de caja abierta.")
    if not lineas:
        raise ValidationError("La venta no tiene líneas.")
    if medio_pago not in FacturaVenta.MedioPago.values:
        raise ValidationError("Medio de pago inválido.")
    if medio_pago == FacturaVenta.MedioPago.CREDITO and cliente is None:
        raise ValidationError("Una venta a crédito requiere seleccionar un cliente.")

    sucursal = sesion_caja.sucursal
    empresa = sucursal.empresa
    bodega = Bodega.objects.filter(sucursal=sucursal).first()
    if bodega is None:
        raise ValidationError("La sucursal no tiene bodega configurada.")

    numero = Consecutivo.tomar(empresa, "FV")
    factura = FacturaVenta.objects.create(
        empresa=empresa, sucursal=sucursal, sesion_caja=sesion_caja,
        numero=numero, cliente=cliente, medio_pago=medio_pago, usuario=usuario,
    )

    subtotal = impuesto = total = descuento_total = Decimal("0")
    for linea in lineas:
        producto = Producto.objects.get(pk=linea["producto_id"], activo=True)
        cantidad = Decimal(str(linea["cantidad"]))
        if cantidad <= 0:
            raise ValidationError(f"Cantidad inválida para {producto.nombre}.")
        es_regalia = bool(linea.get("es_regalia", False))

        if es_regalia:
            # Regalía: se entrega gratis. No genera ingreso ni descuento; el
            # stock sale y su costo se registra como gasto de promoción.
            precio = Decimal("0")
            desc_l = Decimal("0")
            total_linea = Decimal("0")
            sub_l = imp_l = Decimal("0")
            tipo_kardex = "REG"
        else:
            precio = producto.precio_venta
            bruto_linea = (precio * cantidad).quantize(Decimal("0.01"))
            desc_pct = Decimal(str(linea.get("descuento_pct", 0) or 0))
            if desc_pct < 0 or desc_pct > 100:
                raise ValidationError(f"Porcentaje de descuento inválido para {producto.nombre} (0-100).")
            # Calcular automáticamente el monto del descuento
            desc_l = (bruto_linea * desc_pct / 100).quantize(Decimal("0.01"))
            total_linea = bruto_linea - desc_l
            # Bloqueo de venta bajo costo: el precio efectivo por unidad (ya con
            # el descuento) no puede quedar por debajo del costo promedio.
            if not permitir_bajo_costo and producto.costo_promedio > 0:
                precio_efectivo = total_linea / cantidad
                if precio_efectivo < producto.costo_promedio:
                    raise ValidationError(
                        f"{producto.nombre}: el precio con descuento (₡{precio_efectivo:.2f}) "
                        f"queda por debajo del costo (₡{producto.costo_promedio}). "
                        "Un gerente debe autorizar la venta bajo costo."
                    )
            sub_l, imp_l = _desglose_fiscal(empresa, producto, total_linea)
            tipo_kardex = "VEN"

        # Kardex primero: si no hay stock, ValidationError revienta TODA la venta.
        registrar_movimiento(
            producto=producto, bodega=bodega, tipo=tipo_kardex,
            cantidad=-cantidad, referencia=numero, usuario=usuario,
            motivo="Regalía / promoción" if es_regalia else "",
        )
        LineaVenta.objects.create(
            factura=factura, producto=producto, cantidad=cantidad,
            precio_unitario=precio, descuento_pct=desc_pct if not es_regalia else 0,
            descuento_monto=desc_l if not es_regalia else 0, es_regalia=es_regalia,
            costo_unitario=producto.costo_promedio, total=total_linea,
        )
        subtotal += sub_l; impuesto += imp_l; total += total_linea; descuento_total += desc_l

    factura.subtotal, factura.impuesto, factura.total = subtotal, impuesto, total
    factura.descuento = descuento_total
    factura.save(update_fields=["subtotal", "descuento", "impuesto", "total"])

    if medio_pago == FacturaVenta.MedioPago.EFECTIVO:
        # Una venta 100% regalía tiene total 0: no mueve caja (evita el
        # movimiento de monto cero, que además es inválido).
        if total > 0:
            registrar_movimiento_caja(
                sesion=sesion_caja, tipo=MovimientoCaja.Tipo.VENTA, monto=total,
                descripcion=f"Venta {numero}", referencia=numero, usuario=usuario,
            )
    elif medio_pago == FacturaVenta.MedioPago.CREDITO:
        # Genera la cuenta por cobrar y valida el límite (revienta la venta
        # completa si el crédito no alcanza). No mueve caja: no hay efectivo.
        if total > 0:
            from .cxc import crear_cxc
            crear_cxc(factura=factura)

    # Asiento automático (venta + costo), en la misma transacción: si el
    # asiento no cuadra, la venta entera se revierte. Nadie digita contabilidad.
    from .contabilizar import asentar_venta
    asentar_venta(factura, usuario=usuario)
    return factura


@transaction.atomic
def anular_factura(*, factura, motivo, usuario) -> FacturaVenta:
    """Anulación por movimientos inversos: el inventario regresa, el efectivo
    sale de caja. La factura original nunca se borra ni se edita."""
    factura = FacturaVenta.objects.select_for_update().get(pk=factura.pk)
    if factura.estado == FacturaVenta.Estado.ANULADA:
        raise ValidationError("La factura ya está anulada.")
    if not motivo or not motivo.strip():
        raise ValidationError("El motivo de anulación es obligatorio.")

    bodega = Bodega.objects.filter(sucursal=factura.sucursal).first()
    for linea in factura.lineas.all():
        registrar_movimiento(
            producto=linea.producto, bodega=bodega, tipo="DEV",
            cantidad=linea.cantidad, costo_unitario=Decimal("0"),
            referencia=f"ANU-{factura.numero}", motivo=motivo, usuario=usuario,
        )
    if factura.medio_pago == FacturaVenta.MedioPago.EFECTIVO:
        from caja.services import sesion_abierta_de
        sesion = sesion_abierta_de(usuario)
        if sesion is None:
            raise ValidationError(
                "Para anular una venta en efectivo debe tener una caja abierta "
                "(el dinero devuelto sale de esa caja)."
            )
        registrar_movimiento_caja(
            sesion=sesion, tipo=MovimientoCaja.Tipo.ANULACION, monto=-factura.total,
            descripcion=f"Anulación {factura.numero}: {motivo}", referencia=factura.numero, usuario=usuario,
        )
    elif factura.medio_pago == FacturaVenta.MedioPago.CREDITO:
        # Cancela la CxC y libera el crédito (bloquea si ya tiene abonos).
        from .cxc import cancelar_cxc_por_anulacion
        cancelar_cxc_por_anulacion(factura=factura, usuario=usuario)
    factura.estado = FacturaVenta.Estado.ANULADA
    factura.motivo_anulacion = motivo.strip()
    factura.anulada_en = timezone.now()
    factura.anulada_por = usuario
    factura.save(update_fields=["estado", "motivo_anulacion", "anulada_en", "anulada_por"])

    # Asiento inverso de la venta y del costo.
    from .contabilizar import asentar_anulacion
    asentar_anulacion(factura, usuario=usuario)
    return factura
