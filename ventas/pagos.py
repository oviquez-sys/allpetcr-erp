"""Totales de ventas por medio de pago, contando bien los pagos mixtos.

Hasta el 26/09/2026 cada venta tenía UN medio y los reportes agrupaban por
`FacturaVenta.medio_pago`. Con el pago mixto (auditoría, VEN-04) una venta
puede traer efectivo y SINPE a la vez: agrupar por `medio_pago` la mandaría
entera a una fila "Pago mixto" que no le dice nada al arqueo. Este es el
único lugar que sabe repartirla; los reportes lo llaman en vez de agrupar
por su cuenta, para que el Inicio, la evidencia de caja y el resumen diario
no puedan contar distinto.
"""
from decimal import Decimal

from django.db.models import Count, Sum

from .models import FacturaVenta, PagoVenta

# Los medios que de verdad mueven plata. "Pago mixto" no es un medio: es una
# venta repartida entre estos.
MEDIOS_REALES = [(c, e) for c, e in FacturaVenta.MedioPago.choices if c != FacturaVenta.MedioPago.MIXTO]


def por_medio(facturas) -> dict:
    """{medio: {"t": total, "n": ventas}} de un queryset de facturas.

    Una venta mixta suma su parte a cada medio y cuenta como una venta en
    cada uno: así la suma de los totales sigue siendo la venta, pero la suma
    de las `n` puede pasar del número de tiquetes."""
    resultado = {}
    simples = (
        facturas.exclude(medio_pago=FacturaVenta.MedioPago.MIXTO)
        .order_by().values("medio_pago").annotate(t=Sum("total"), n=Count("id"))
    )
    for fila in simples:
        resultado[fila["medio_pago"]] = {"t": fila["t"] or Decimal("0"), "n": fila["n"]}
    mixtos = (
        PagoVenta.objects.filter(factura__in=facturas.filter(medio_pago=FacturaVenta.MedioPago.MIXTO))
        .order_by().values("medio").annotate(t=Sum("monto"), n=Count("factura", distinct=True))
    )
    for fila in mixtos:
        actual = resultado.setdefault(fila["medio"], {"t": Decimal("0"), "n": 0})
        actual["t"] += fila["t"] or Decimal("0")
        actual["n"] += fila["n"]
    return resultado
