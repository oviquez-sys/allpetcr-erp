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

CAMBIOS Y MOTIVO DE UN TOQUE (24/11/2026)
-----------------------------------------
Caso real: una clienta cambió una pechera XL comprada el viernes por SINPE
por una XXL y pagó la diferencia. El sistema solo sabía «devolver la plata»
y «vender»: no había cómo registrarlo. Ahora:

- `aplicar_a_cambio`: la parte del valor devuelto que paga lo que el cliente
  se lleva (ver ventas/cambios.py). Esa parte NO sale de la caja ni del
  banco: va a la cuenta «Cambios por aplicar», que la venta nueva vacía.
  Solo lo que sobra se reembolsa por el medio original.
- `tipo_motivo`: Talla · No le gustó · Defectuoso · Otro. «Otro» pide texto.
  Defectuoso = el producto NO vuelve al inventario vendible: no entra al
  kardex y su costo se queda como costo de ventas (es la pérdida). Si el
  proveedor lo repone, entra con la compra.
- Plazo (decisión de Oscar, 24/11/2026): 15 días desde la compra
  (`PLAZO_CAMBIOS_DIAS`). Pasado el plazo solo el gerente
  (`permitir_fuera_de_plazo`). Dentro del plazo, cualquiera: ver el control
  en el cierre de caja (`caja/resumen.py`, «Devoluciones y cambios»).
- Una venta pagada con un cambio (medio CAM) que después se devuelve por
  plata: la parte CAM se reembolsa por el medio de la compra ORIGINAL
  (efectivo o fiado → efectivo; lo demás → banco).
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from caja.models import MovimientoCaja
from caja.services import registrar_movimiento_caja, sesion_abierta_de
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .models import Consecutivo, DevolucionVenta, FacturaVenta, LineaDevolucion, LineaVenta
from .services import _desglose_fiscal

PLAZO_CAMBIOS_DIAS = int(getattr(settings, "PLAZO_CAMBIOS_DIAS", 15))
CENTIMO = Decimal("0.01")


def _cantidad_ya_devuelta(linea_venta) -> Decimal:
    agg = LineaDevolucion.objects.filter(linea_venta=linea_venta).aggregate(t=Sum("cantidad"))
    return agg["t"] or Decimal("0")


def dias_desde(factura) -> int:
    return (timezone.localdate() - timezone.localtime(factura.creado_en).date()).days


def fuera_de_plazo(factura) -> bool:
    return dias_desde(factura) > PLAZO_CAMBIOS_DIAS


def precio_pagado(linea_venta) -> Decimal:
    """Lo que el cliente pagó por UNA unidad, con su descuento. Es lo que se
    le acredita al devolverla: no el precio de hoy (si subió, no gana; si
    bajó o estaba en promoción, no pierde)."""
    if linea_venta.es_regalia or not linea_venta.cantidad:
        return Decimal("0")
    return linea_venta.total / linea_venta.cantidad


def _calcular(factura, lineas):
    """[(linea_venta, cantidad, monto)] + total, sin escribir nada. Valida
    las cantidades contra lo que queda por devolver."""
    filas, neto = [], Decimal("0")
    for l in lineas:
        cantidad = Decimal(str(l["cantidad"]))
        if cantidad <= 0:
            continue  # línea sin marcar cantidad: se omite, no es un error
        linea_venta = LineaVenta.objects.select_related("producto").get(pk=l["linea_venta_id"], factura=factura)
        ya_devuelta = _cantidad_ya_devuelta(linea_venta)
        disponible = linea_venta.cantidad - ya_devuelta
        if cantidad > disponible:
            raise ValidationError(
                f"No se puede devolver {cantidad:g} de {linea_venta.producto.nombre}: "
                f"se compraron {linea_venta.cantidad:g} y ya se devolvieron {ya_devuelta:g}. "
                f"Quedan {disponible:g} disponibles para devolver."
            )
        monto = (precio_pagado(linea_venta) * cantidad).quantize(CENTIMO)
        filas.append((linea_venta, cantidad, monto))
        neto += monto
    return filas, neto


def valor_a_favor(factura, lineas) -> Decimal:
    """Cuánto de lo devuelto puede pagar un producto nuevo (cambio). En una
    venta fiada, primero baja lo que se debe: lo que no se pagó no se le
    puede acreditar a otra compra."""
    _, neto = _calcular(factura, lineas)
    if factura.medio_pago == FacturaVenta.MedioPago.CREDITO:
        from .models import DocumentoCxC
        doc = DocumentoCxC.objects.filter(factura=factura).first()
        return neto - min(neto, doc.saldo if doc else Decimal("0"))
    return neto


def _credito_era_efectivo(factura) -> bool:
    """La parte CAM de una venta: ¿de qué medio vino ese valor?"""
    origen = factura.devoluciones_aplicadas.select_related("factura").first()
    return origen is not None and origen.factura.medio_pago in (
        FacturaVenta.MedioPago.EFECTIVO, FacturaVenta.MedioPago.CREDITO)


def _repartir_reembolso(factura, monto):
    """(efectivo, bancos) de un reembolso, según cómo se pagó la venta.

    Pago mixto (VEN-04): en la misma proporción en que se cobró. Simple y
    siempre igual: si pagó la mitad en efectivo, la mitad de lo devuelto sale
    del cajón y la otra mitad se gestiona por el datáfono o por SINPE."""
    if monto <= 0:
        return Decimal("0"), Decimal("0")
    medio = factura.medio_pago
    if medio in (FacturaVenta.MedioPago.EFECTIVO, FacturaVenta.MedioPago.CREDITO):
        return monto, Decimal("0")
    if medio in (FacturaVenta.MedioPago.MIXTO, FacturaVenta.MedioPago.CAMBIO):
        cam_es_efectivo = _credito_era_efectivo(factura)
        en_efectivo = sum((m for med, m in factura.desglose_pagos()
                           if med == "EFE" or (med == "CAM" and cam_es_efectivo)), Decimal("0"))
        efectivo = (monto * en_efectivo / factura.total).quantize(CENTIMO) if factura.total > 0 else Decimal("0")
        return efectivo, monto - efectivo
    return Decimal("0"), monto  # TAR, SIN, TRA: se liquidó a Bancos, no toca caja física


@transaction.atomic
def registrar_devolucion(*, factura, lineas, motivo="", usuario=None, tipo_motivo=DevolucionVenta.TipoMotivo.OTRO,
                         aplicar_a_cambio=Decimal("0"), venta_cambio=None, permitir_fuera_de_plazo=True,
                         sesion_caja=None) -> DevolucionVenta:
    """lineas: iterable de dicts {"linea_venta_id": int, "cantidad": Decimal}."""
    factura = FacturaVenta.objects.select_for_update().get(pk=factura.pk)
    if factura.estado != FacturaVenta.Estado.EMITIDA:
        raise ValidationError("Esta venta ya está anulada: no se puede registrar una devolución sobre ella.")
    if tipo_motivo not in DevolucionVenta.TipoMotivo.values:
        raise ValidationError("Ese motivo no existe.")
    motivo = (motivo or "").strip()
    if not motivo and tipo_motivo != DevolucionVenta.TipoMotivo.OTRO:
        motivo = DevolucionVenta.TipoMotivo(tipo_motivo).label
    if not motivo:
        raise ValidationError("El motivo de la devolución es obligatorio.")
    if not lineas:
        raise ValidationError("Seleccioná al menos un producto a devolver.")
    if not permitir_fuera_de_plazo and fuera_de_plazo(factura):
        raise ValidationError(
            f"Esa compra es de hace {dias_desde(factura)} días y el plazo para cambios y devoluciones es de "
            f"{PLAZO_CAMBIOS_DIAS}. Solo el gerente puede hacerla.")
    defectuoso = tipo_motivo == DevolucionVenta.TipoMotivo.DEFECTUOSO

    empresa = factura.empresa
    # La devolución entra a la misma bodega de la que salió (BE-09).
    bodega = Bodega.principal_de(factura.sucursal)
    if bodega is None:
        raise ValidationError("La sucursal no tiene bodega configurada.")

    filas, _ = _calcular(factura, lineas)
    if not filas:
        raise ValidationError("Seleccioná al menos una cantidad mayor que cero para devolver.")

    numero = Consecutivo.tomar(empresa, "DV")
    devolucion = DevolucionVenta.objects.create(
        factura=factura, numero=numero, motivo=motivo[:200], tipo_motivo=tipo_motivo, usuario=usuario,
        venta_cambio=venta_cambio,
    )

    bruto_total = descuento_total = impuesto_total = subtotal_total = neto_total = Decimal("0")
    costo_vendido_total = costo_regalado_total = Decimal("0")

    for linea_venta, cantidad, monto_linea in filas:
        producto = linea_venta.producto
        costo_linea = (linea_venta.costo_unitario * cantidad).quantize(CENTIMO)

        if linea_venta.es_regalia:
            if not defectuoso:
                costo_regalado_total += costo_linea
        else:
            bruto_linea = (linea_venta.precio_unitario * cantidad).quantize(CENTIMO)
            # El precio efectivo ya trae el descuento original prorrateado.
            desc_linea = max(Decimal("0"), bruto_linea - monto_linea)
            sub_l, imp_l = _desglose_fiscal(empresa, producto, monto_linea)

            bruto_total += bruto_linea
            descuento_total += desc_linea
            subtotal_total += sub_l
            impuesto_total += imp_l
            neto_total += monto_linea
            if not defectuoso:
                costo_vendido_total += costo_linea

        # Reintegra al inventario: entra de vuelta al kardex. Lo defectuoso
        # no: venderlo otra vez sería venderle un producto dañado a otro.
        if not defectuoso:
            registrar_movimiento(
                producto=producto, bodega=bodega, tipo="DEV",
                cantidad=cantidad, costo_unitario=Decimal("0"),
                referencia=numero, motivo=f"Devolución: {motivo}", usuario=usuario,
            )
        LineaDevolucion.objects.create(
            devolucion=devolucion, linea_venta=linea_venta, cantidad=cantidad, monto=monto_linea,
            a_inventario=not defectuoso,
        )

    # --- Cómo sale el dinero (o se ajusta el crédito), según el medio de pago ---
    reducir_cxc = Decimal("0")
    if neto_total > 0 and factura.medio_pago == FacturaVenta.MedioPago.CREDITO:
        from .models import Cliente, DocumentoCxC
        doc = DocumentoCxC.objects.select_for_update().filter(factura=factura).first()
        saldo_antes = doc.saldo if doc else Decimal("0")
        reducir_cxc = min(neto_total, saldo_antes)
        if doc is not None and reducir_cxc > 0:
            doc.saldo -= reducir_cxc
            if doc.saldo == 0:
                doc.estado = DocumentoCxC.Estado.PAGADO
            doc.save(update_fields=["saldo", "estado"])
            cliente = Cliente.objects.select_for_update().get(pk=doc.cliente_id)
            cliente.saldo -= reducir_cxc
            cliente.save(update_fields=["saldo"])
    aplicar_a_cambio = Decimal(str(aplicar_a_cambio or 0)).quantize(CENTIMO)
    if aplicar_a_cambio < 0 or aplicar_a_cambio > neto_total - reducir_cxc:
        raise ValidationError("Lo que se aplica al cambio no puede pasar del valor devuelto.")
    reembolso_efectivo, reembolso_bancos = _repartir_reembolso(factura, neto_total - reducir_cxc - aplicar_a_cambio)

    sesion = sesion_caja or (sesion_abierta_de(usuario) if usuario else None)
    if reembolso_efectivo > 0:
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

    devolucion.total = neto_total
    devolucion.reembolso_efectivo, devolucion.reembolso_bancos = reembolso_efectivo, reembolso_bancos
    devolucion.rebajado_cxc, devolucion.aplicado_cambio = reducir_cxc, aplicar_a_cambio
    devolucion.sesion_caja = sesion
    devolucion.save(update_fields=["total", "reembolso_efectivo", "reembolso_bancos", "rebajado_cxc",
                                   "aplicado_cambio", "sesion_caja"])

    from .contabilizar import asentar_devolucion
    asentar_devolucion(
        devolucion=devolucion, factura=factura,
        bruto=bruto_total, descuento=descuento_total, impuesto=impuesto_total,
        costo_vendido=costo_vendido_total, costo_regalado=costo_regalado_total,
        reducir_cxc=reducir_cxc, reembolso_efectivo=reembolso_efectivo, reembolso_bancos=reembolso_bancos,
        reembolso_cambio=aplicar_a_cambio, usuario=usuario,
    )
    # Campaña con sorteo (16/11/2026): con lo devuelto, la venta puede dejar
    # de superar el umbral o quedar en cero; se le quitan esos números.
    from campanas.reglas import recalcular_venta
    recalcular_venta(factura, motivo=f"Devolución {numero}", usuario=usuario)
    return devolucion
