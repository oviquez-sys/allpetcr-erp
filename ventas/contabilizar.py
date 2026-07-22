"""Traducción de operaciones de venta a asientos contables.

Vive en `ventas` (conoce facturas y abonos) y usa el libro genérico de
`contabilidad`. Reglas de asiento (motor fiscal por régimen, Fase 2 §6):

Venta (efectivo/tarjeta/SINPE):
    Debe  Caja o Bancos            total
        Haber  Ventas               subtotal
        Haber  IVA por pagar        impuesto   (solo régimen tradicional)

Venta a crédito:
    Debe  Cuentas por cobrar       total
        Haber  Ventas               subtotal
        Haber  IVA por pagar        impuesto

Costo de la venta (siempre, a costo promedio):
    Debe  Costo de ventas          costo
        Haber  Inventario           costo

Abono a CxC:
    Debe  Caja o Bancos            monto
        Haber  Cuentas por cobrar   monto

Anulación: se registra el asiento inverso de la venta y del costo.
"""
from decimal import Decimal

from django.utils import timezone

from contabilidad.services import cuenta, registrar_asiento

# Efectivo entra a Caja; tarjeta y SINPE se liquidan en Bancos.
_CUENTA_PAGO = {"EFE": "caja", "TAR": "bancos", "SIN": "bancos", "CRE": "cxc", "TRA": "bancos"}


def _costos_por_tipo(factura):
    """Separa el costo (a costo promedio) de lo vendido vs. lo regalado.
    Lo vendido va a Costo de ventas; lo regalado a Gasto por regalías."""
    vendido = sum((l.costo_unitario * l.cantidad for l in factura.lineas.all() if not l.es_regalia), Decimal("0"))
    regalado = sum((l.costo_unitario * l.cantidad for l in factura.lineas.all() if l.es_regalia), Decimal("0"))
    return vendido, regalado


def asentar_venta(factura, usuario=None):
    empresa = factura.empresa
    # Fecha del DÍA LOCAL (Costa Rica), no la fecha UTC: una venta a las 7pm
    # debe quedar en su día, no correrse al siguiente por el desfase horario.
    fecha = timezone.localdate(factura.creado_en)
    cuenta_cargo = cuenta(empresa, _CUENTA_PAGO[factura.medio_pago])

    # Ventas brutas = lo que paga el cliente + el descuento concedido. El
    # descuento se debita a su propia cuenta (contra-ingreso) para que quede
    # a la vista cuánto se rebajó, en vez de esconderlo en un ingreso menor.
    bruto = factura.subtotal + factura.descuento
    lineas = []
    if factura.total > 0:
        lineas.append({"cuenta": cuenta_cargo, "debe": factura.total, "detalle": factura.numero})
    if factura.descuento > 0:
        lineas.append({"cuenta": cuenta(empresa, "descuentos"), "debe": factura.descuento})
    if bruto > 0:
        lineas.append({"cuenta": cuenta(empresa, "ventas"), "haber": bruto})
    if factura.impuesto > 0:
        lineas.append({"cuenta": cuenta(empresa, "iva_por_pagar"), "haber": factura.impuesto})
    if lineas:  # una venta 100% regalía no tiene asiento de ingreso
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Venta {factura.numero}",
            origen="VEN", referencia=factura.numero, lineas=lineas, usuario=usuario,
        )

    # Costo: lo vendido a Costo de ventas; lo regalado a Gasto por regalías.
    vendido, regalado = _costos_por_tipo(factura)
    if vendido > 0:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Costo de venta {factura.numero}",
            origen="COS", referencia=factura.numero, usuario=usuario,
            lineas=[
                {"cuenta": cuenta(empresa, "costo_ventas"), "debe": vendido},
                {"cuenta": cuenta(empresa, "inventario"), "haber": vendido},
            ],
        )
    if regalado > 0:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Regalía {factura.numero}",
            origen="COS", referencia=factura.numero, usuario=usuario,
            lineas=[
                {"cuenta": cuenta(empresa, "gasto_regalias"), "debe": regalado},
                {"cuenta": cuenta(empresa, "inventario"), "haber": regalado},
            ],
        )


def asentar_devolucion(
    *, devolucion, factura, bruto, descuento, impuesto,
    costo_vendido, costo_regalado, reducir_cxc, reembolso_efectivo, reembolso_bancos, usuario=None,
):
    """Reversa contable de una devolución PARCIAL. Espeja asentar_venta pero
    solo por los montos devueltos, y el 'reembolso' puede repartirse entre
    caja / bancos / CxC según cómo se pagó y cuánto ya se había abonado
    (ver ventas.devoluciones.registrar_devolucion, que calcula ese reparto)."""
    empresa = factura.empresa
    fecha = timezone.localdate()

    # 'ventas_ledger' replica la convención de asentar_venta: la cuenta Ventas
    # se debita (reversa) por subtotal + descuento. Como bruto = subtotal +
    # descuento + impuesto, subtotal + descuento = bruto - impuesto.
    ventas_ledger = bruto - impuesto

    lineas = []
    if reducir_cxc > 0:
        lineas.append({"cuenta": cuenta(empresa, "cxc"), "haber": reducir_cxc, "detalle": devolucion.numero})
    if reembolso_efectivo > 0:
        lineas.append({"cuenta": cuenta(empresa, "caja"), "haber": reembolso_efectivo, "detalle": devolucion.numero})
    if reembolso_bancos > 0:
        lineas.append({"cuenta": cuenta(empresa, "bancos"), "haber": reembolso_bancos, "detalle": devolucion.numero})
    if descuento > 0:
        lineas.append({"cuenta": cuenta(empresa, "descuentos"), "haber": descuento})
    if ventas_ledger > 0:
        lineas.append({"cuenta": cuenta(empresa, "ventas"), "debe": ventas_ledger})
    if impuesto > 0:
        lineas.append({"cuenta": cuenta(empresa, "iva_por_pagar"), "debe": impuesto})
    if lineas:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Devolución {devolucion.numero} — venta {factura.numero}",
            origen="ANU", referencia=devolucion.numero, lineas=lineas, usuario=usuario,
        )

    if costo_vendido > 0:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Reversa costo devolución {devolucion.numero}",
            origen="ANU", referencia=devolucion.numero, usuario=usuario,
            lineas=[
                {"cuenta": cuenta(empresa, "inventario"), "debe": costo_vendido},
                {"cuenta": cuenta(empresa, "costo_ventas"), "haber": costo_vendido},
            ],
        )
    if costo_regalado > 0:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Reversa regalía devolución {devolucion.numero}",
            origen="ANU", referencia=devolucion.numero, usuario=usuario,
            lineas=[
                {"cuenta": cuenta(empresa, "inventario"), "debe": costo_regalado},
                {"cuenta": cuenta(empresa, "gasto_regalias"), "haber": costo_regalado},
            ],
        )


def asentar_abono(abono, usuario=None):
    factura = abono.documento.factura
    empresa = factura.empresa
    cuenta_cargo = cuenta(empresa, _CUENTA_PAGO.get(abono.medio, "bancos"))
    registrar_asiento(
        empresa=empresa, fecha=timezone.localdate(abono.fecha),
        descripcion=f"Cobro CxC {factura.numero}", origen="COB",
        referencia=factura.numero, usuario=usuario,
        lineas=[
            {"cuenta": cuenta_cargo, "debe": abono.monto},
            {"cuenta": cuenta(empresa, "cxc"), "haber": abono.monto},
        ],
    )


def asentar_anulacion(factura, usuario=None):
    """Reversa de la venta y del costo (débitos y créditos intercambiados)."""
    empresa = factura.empresa
    fecha = timezone.localdate(factura.anulada_en) if factura.anulada_en else timezone.localdate(factura.creado_en)
    cuenta_cargo = cuenta(empresa, _CUENTA_PAGO[factura.medio_pago])

    bruto = factura.subtotal + factura.descuento
    lineas = []
    if factura.total > 0:
        lineas.append({"cuenta": cuenta_cargo, "haber": factura.total, "detalle": f"Anulación {factura.numero}"})
    if factura.descuento > 0:
        lineas.append({"cuenta": cuenta(empresa, "descuentos"), "haber": factura.descuento})
    if bruto > 0:
        lineas.append({"cuenta": cuenta(empresa, "ventas"), "debe": bruto})
    if factura.impuesto > 0:
        lineas.append({"cuenta": cuenta(empresa, "iva_por_pagar"), "debe": factura.impuesto})
    if lineas:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Anulación venta {factura.numero}",
            origen="ANU", referencia=factura.numero, lineas=lineas, usuario=usuario,
        )

    vendido, regalado = _costos_por_tipo(factura)
    if vendido > 0:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Reversa costo {factura.numero}",
            origen="ANU", referencia=factura.numero, usuario=usuario,
            lineas=[
                {"cuenta": cuenta(empresa, "inventario"), "debe": vendido},
                {"cuenta": cuenta(empresa, "costo_ventas"), "haber": vendido},
            ],
        )
    if regalado > 0:
        registrar_asiento(
            empresa=empresa, fecha=fecha, descripcion=f"Reversa regalía {factura.numero}",
            origen="ANU", referencia=factura.numero, usuario=usuario,
            lineas=[
                {"cuenta": cuenta(empresa, "inventario"), "debe": regalado},
                {"cuenta": cuenta(empresa, "gasto_regalias"), "haber": regalado},
            ],
        )
