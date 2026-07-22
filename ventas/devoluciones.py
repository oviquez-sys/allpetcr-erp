"""Devolución PARCIAL de una venta (distinta de anular_factura).

anular_factura revierte TODO el documento y lo marca ANULADA — pensada para
corregir un error del cajero, en el momento o poco después.

registrar_devolucion es para el caso real de negocio: un cliente vuelve
días después a devolver uno o varios productos (no necesariamente todos los
que compró, ni siempre la cantidad completa de cada uno). La factura original
sigue "Emitida"; la devolución queda como un documento propio, ligado a ella,
visible en la bitácora de Actividad.

Reglas:
- Nunca se puede devolver más de lo comprado en esa línea, contando lo que
  ya se devolvió antes en devoluciones previas de la misma línea.
- El descuento de la línea original se prorratea automáticamente.
- Regalías (es_regalia): no hubo cobro, así que no hay reembolso; pero el
  producto sí vuelve al inventario y se revierte su costo de "gasto por
  regalías" (no del costo de ventas).
- Efectivo: el reembolso sale de la CAJA ABIERTA DE HOY (nunca de la sesión
  original, que puede llevar días cerrada). Exige tener caja abierta.
- Tarjeta / SINPE: no mueve caja física (ese reembolso se gestiona aparte,
  por el datáfono); solo se ajusta la contabilidad (cuenta Bancos).
- Crédito (fiado): se reduce primero el saldo pendiente de la cuenta por
  cobrar. Si el cliente ya había abonado más de lo que ahora debe, el
  excedente se reembolsa en efectivo desde la caja abierta de hoy.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from caja.models import MovimientoCaja
from caja.services import registrar_movimiento_caja, sesion_abierta_de
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .models import Consecutivo, DevolucionVenta, FacturaVenta, LineaDevolucion, LineaVenta
from .services import _desglose_fiscal


def _cantidad_ya_devuelta(linea_venta) -> Decimal:
    agg = LineaDevolucion.objects.filter(linea_venta=linea_venta).aggregate(t=Sum("cantidad"))
    return agg["t"] or Decimal("0")


@transaction.atomic
def registrar_devolucion(*, factura, lineas, motivo, usuario=None) -> DevolucionVenta:
    """lineas: iterable de dicts {"linea_venta_id": int, "cantidad": Decimal}."""
    factura = FacturaVenta.objects.select_for_update().get(pk=factura.pk)
    if factura.estado != FacturaVenta.Estado.EMITIDA:
        raise ValidationError("Esta venta ya está anulada: no se puede registrar una devolución sobre ella.")
    if not motivo or not motivo.strip():
        raise ValidationError("El motivo de la devolución es obligatorio.")
    if not lineas:
        raise ValidationError("Seleccioná al menos un producto a devolver.")

    empresa = factura.empresa
    bodega = Bodega.objects.filter(sucursal=factura.sucursal).first()
    if bodega is None:
        raise ValidationError("La sucursal no tiene bodega configurada.")

    numero = Consecutivo.tomar(empresa, "DV")
    devolucion = DevolucionVenta.objects.create(
        factura=factura, numero=numero, motivo=motivo.strip(), usuario=usuario,
    )

    bruto_total = descuento_total = impuesto_total = subtotal_total = neto_total = Decimal("0")
    costo_vendido_total = costo_regalado_total = Decimal("0")
    algo_procesado = False

    for l in lineas:
        cantidad = Decimal(str(l["cantidad"]))
        if cantidad <= 0:
            continue  # línea sin marcar cantidad: se omite, no es un error
        algo_procesado = True

        linea_venta = LineaVenta.objects.select_related("producto").get(
            pk=l["linea_venta_id"], factura=factura
        )
        ya_devuelta = _cantidad_ya_devuelta(linea_venta)
        disponible = linea_venta.cantidad - ya_devuelta
        if cantidad > disponible:
            raise ValidationError(
                f"No se puede devolver {cantidad} de {linea_venta.producto.nombre}: "
                f"se compraron {linea_venta.cantidad} y ya se devolvieron {ya_devuelta}. "
                f"Quedan {disponible} disponibles para devolver."
            )

        producto = linea_venta.producto
        costo_linea = (linea_venta.costo_unitario * cantidad).quantize(Decimal("0.01"))

        if linea_venta.es_regalia:
            monto_linea = Decimal("0")
            costo_regalado_total += costo_linea
        else:
            bruto_linea = (linea_venta.precio_unitario * cantidad).quantize(Decimal("0.01"))
            # El precio efectivo ya trae el descuento original prorrateado.
            precio_efectivo = (linea_venta.total / linea_venta.cantidad) if linea_venta.cantidad else Decimal("0")
            monto_linea = (precio_efectivo * cantidad).quantize(Decimal("0.01"))
            desc_linea = max(Decimal("0"), bruto_linea - monto_linea)
            sub_l, imp_l = _desglose_fiscal(empresa, producto, monto_linea)

            bruto_total += bruto_linea
            descuento_total += desc_linea
            subtotal_total += sub_l
            impuesto_total += imp_l
            neto_total += monto_linea
            costo_vendido_total += costo_linea

        # Reintegra al inventario: entra de vuelta al kardex.
        registrar_movimiento(
            producto=producto, bodega=bodega, tipo="DEV",
            cantidad=cantidad, costo_unitario=Decimal("0"),
            referencia=numero, motivo=f"Devolución: {motivo.strip()}", usuario=usuario,
        )
        LineaDevolucion.objects.create(
            devolucion=devolucion, linea_venta=linea_venta, cantidad=cantidad, monto=monto_linea,
        )

    if not algo_procesado:
        raise ValidationError("Seleccioná al menos una cantidad mayor que cero para devolver.")

    devolucion.total = neto_total
    devolucion.save(update_fields=["total"])

    # --- Cómo sale el dinero (o se ajusta el crédito), según el medio de pago ---
    reducir_cxc = reembolso_efectivo = reembolso_bancos = Decimal("0")
    if neto_total > 0:
        if factura.medio_pago == FacturaVenta.MedioPago.EFECTIVO:
            reembolso_efectivo = neto_total
        elif factura.medio_pago == FacturaVenta.MedioPago.CREDITO:
            from .models import Cliente, DocumentoCxC
            doc = DocumentoCxC.objects.select_for_update().filter(factura=factura).first()
            saldo_antes = doc.saldo if doc else Decimal("0")
            reducir_cxc = min(neto_total, saldo_antes)
            reembolso_efectivo = neto_total - reducir_cxc
            if doc is not None and reducir_cxc > 0:
                doc.saldo -= reducir_cxc
                if doc.saldo == 0:
                    doc.estado = DocumentoCxC.Estado.PAGADO
                doc.save(update_fields=["saldo", "estado"])
                cliente = Cliente.objects.select_for_update().get(pk=doc.cliente_id)
                cliente.saldo -= reducir_cxc
                cliente.save(update_fields=["saldo"])
        else:  # TAR, SIN, TRA: se liquidó a Bancos, no toca caja física
            reembolso_bancos = neto_total

    if reembolso_efectivo > 0:
        sesion = sesion_abierta_de(usuario) if usuario else None
        if sesion is None:
            raise ValidationError(
                "Para devolver dinero en efectivo debe tener una caja abierta. "
                "Abra la caja primero y vuelva a intentar la devolución."
            )
        registrar_movimiento_caja(
            sesion=sesion, tipo=MovimientoCaja.Tipo.ANULACION, monto=-reembolso_efectivo,
            descripcion=f"Devolución {numero} de venta {factura.numero}",
            referencia=numero, usuario=usuario,
        )

    from .contabilizar import asentar_devolucion
    asentar_devolucion(
        devolucion=devolucion, factura=factura,
        bruto=bruto_total, descuento=descuento_total, impuesto=impuesto_total,
        costo_vendido=costo_vendido_total, costo_regalado=costo_regalado_total,
        reducir_cxc=reducir_cxc, reembolso_efectivo=reembolso_efectivo, reembolso_bancos=reembolso_bancos,
        usuario=usuario,
    )
    return devolucion
