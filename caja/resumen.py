"""Resumen de un cierre de caja: lo que imprime el tiquete y lo que lleva el
aviso por correo (02/11/2026, pedido de Oscar).

Un solo lugar arma los números para que el papel, el correo y la pantalla no
puedan contar distinto. Todo sale de la sesión YA CERRADA: lo esperado y lo
contado que guardó `cerrar_caja`, no un cálculo nuevo que podría dar otra
cosa si después se anula una venta.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum

from .models import MovimientoCaja, SesionCaja

CERO = Decimal("0")

# Orden y nombres con que se muestran los medios. "Crédito" es fiado: no
# entra plata ese día, pero es venta y tiene que verse.
MEDIOS = [("EFE", "Efectivo"), ("TAR", "Tarjeta"), ("SIN", "SINPE Móvil"),
          ("TRA", "Transferencia"), ("CRE", "Crédito (fiado)")]


def resumen_cierre(sesion: SesionCaja) -> dict:
    from ventas.models import CambioMedioPago, FacturaVenta, LineaVenta
    from ventas.pagos import por_medio

    from .services import ultimo_cierre

    emitidas = sesion.ventas.filter(estado=FacturaVenta.Estado.EMITIDA)
    tot = emitidas.aggregate(n=Count("id"), total=Sum("total"), descuento=Sum("descuento"),
                             redondeo=Sum("redondeo"), impuesto=Sum("impuesto"))
    anuladas = sesion.ventas.filter(estado=FacturaVenta.Estado.ANULADA).aggregate(n=Count("id"), total=Sum("total"))
    regalias = LineaVenta.objects.filter(factura__in=emitidas, es_regalia=True).aggregate(n=Sum("cantidad"))

    medios = por_medio(emitidas)
    ventas_por_medio = [(nombre, medios[c]["n"], medios[c]["t"]) for c, nombre in MEDIOS if c in medios]

    movs = sesion.movimientos.aggregate(
        apertura=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.APERTURA)),
        ventas=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.VENTA)),
        ingresos=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.INGRESO)),
        egresos=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.EGRESO)),
        devoluciones=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.ANULACION)),
        retiros=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.RETIRO)),
        correcciones=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.CORRECCION)),
    )
    movs = {k: v or CERO for k, v in movs.items()}

    redondeo = tot["redondeo"] or CERO
    arqueo = [
        ("Efectivo", sesion.monto_esperado, sesion.monto_contado),
        ("Tarjeta", sesion.tarjeta_esperado, sesion.tarjeta_contado),
        ("SINPE Móvil", sesion.sinpe_esperado, sesion.sinpe_contado),
    ]
    arqueo = [{"nombre": n, "esperado": e or CERO, "contado": c, "diferencia": (c - (e or CERO)) if c is not None else None}
              for n, e, c in arqueo]
    orden = {"EFE": 0, "TAR": 1, "SIN": 2}
    diferencias = sorted(sesion.diferencias.all(), key=lambda d: orden.get(d.medio, 9))
    anterior = ultimo_cierre(sesion.sucursal.empresa, antes_de=sesion.abierta_en)
    return {
        "sesion": sesion,
        "ventas_n": tot["n"] or 0,
        "ventas_total": tot["total"] or CERO,
        "impuesto": tot["impuesto"] or CERO,
        "descuentos": (tot["descuento"] or CERO) - redondeo,
        "redondeo": redondeo,
        "regalias": regalias["n"] or CERO,
        "anuladas_n": anuladas["n"] or 0,
        "anuladas_total": anuladas["total"] or CERO,
        "ventas_por_medio": ventas_por_medio,
        # La cuenta del efectivo, renglón por renglón: así se ve de dónde
        # sale lo esperado (los egresos y devoluciones vienen en negativo).
        "efectivo": [
            ("Apertura", movs["apertura"]),
            ("Ventas en efectivo", movs["ventas"]),
            ("Ingresos (abonos, otros)", movs["ingresos"]),
            ("Egresos", movs["egresos"]),
            ("Devoluciones en efectivo", movs["devoluciones"]),
            ("Cambios de medio de pago", movs["correcciones"]),
            ("Retiros para depositar", movs["retiros"]),
        ],
        # 02/11/2026: lo que se sacó para depositar y las ventas que se
        # cobraron con otro medio, con nombre y apellido en el papel.
        "retiros": list(sesion.retiros.select_related("usuario").order_by("creado_en")),
        "cambios_medio": list(CambioMedioPago.objects.filter(factura__sesion_caja=sesion)
                              .select_related("factura", "usuario").order_by("fecha")),
        "arqueo": arqueo,
        "diferencias": diferencias,
        "cuadra": not diferencias,
        "neto": sum((d.diferencia for d in diferencias), CERO),
        "anterior": anterior,
        # La apertura contra lo que contó el cierre anterior. No es una
        # diferencia de ESTA caja: entre un cierre y la apertura siguiente se
        # puede sacar plata (depósito) a propósito. Se informa, no se acusa.
        "apertura_vs_anterior": (sesion.monto_apertura - anterior.monto_contado)
        if anterior and anterior.monto_contado is not None else None,
        "desglose": sesion.desglose(),
    }


def texto_diferencia(d) -> str:
    """'Faltan ₡2.000' / 'Sobran ₡500' (sin signo raro para quien lee)."""
    monto = f"₡{abs(d):,.0f}".replace(",", ".")
    return f"Faltan {monto}" if d < 0 else f"Sobran {monto}"
