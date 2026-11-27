"""Envío que el cliente paga junto con la compra (26/11/2026).

POR QUÉ EXISTE
--------------
Oscar: «un cliente compra algo y nos paga el producto + el Uber en el mismo
SINPE; todos los días tenemos diferencias al cierre por ese motivo». El SINPE
traía ₡2.500 más de lo vendido y el cierre lo marcaba como sobrante.

LA REGLA (decisiones de Oscar, 26/11/2026)
------------------------------------------
- Se cobra lo mismo que cobra el Uber: la tienda solo pasa la plata al
  mensajero. Por eso **no es venta**: no entra a `FacturaVenta.total`, no
  lleva IVA, no cuenta para el sorteo, ni para la ganancia, ni para los
  reportes de ventas. Queda aparte en `FacturaVenta.envio`. (Confirmar con
  el contador; si un día se cobra una tarifa propia, eso sí sería ingreso.)
- Se anota con el mismo medio con que se pagó la compra. En un pago mixto, el
  envío sale del SINPE, si no de la tarjeta, si no del efectivo: el primero
  que alcance (`repartir_mixto`).
- Cómo se le paga al mensajero varía (Oscar): con la tarjeta o la app de la
  tienda, con efectivo de la gaveta o con la tarjeta personal de un socio. Si
  el cliente le paga directo al mensajero, no pasa por la tienda y no se anota.
- No se fía: el mensajero cobra ese día.

EN EL CIERRE
------------
- SINPE y tarjeta: lo esperado suma los envíos cobrados por ese medio
  (`caja.services.esperado_por_medio`).
- Efectivo: el envío cobrado en efectivo entra a la gaveta (+) y el pagado al
  mensajero con efectivo de la gaveta sale (−); los dos como movimientos ENV.

CONTABILIDAD
------------
    Debe  Caja o Bancos (cómo pagó el cliente)       envío
        Haber  Envíos por pagar al mensajero (2403)  envío
    Debe  Envíos por pagar al mensajero (2403)       envío
        Haber  Caja / Bancos / Por reembolsar a socios (2404)
La 2403 siempre queda en cero. La 2404 es lo que la tienda le debe a un socio
que pagó el Uber con su tarjeta.

Anular la venta deshace todo (lo cobrado y lo pagado). Si en la realidad el
mensajero ya cobró, la diferencia se explica en el cierre. Una devolución no
toca el envío: el servicio ya se hizo.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError

CENTIMO = Decimal("0.01")
PREFERENCIA_MIXTO = ("SIN", "TAR", "EFE")
_CUENTA_PAGO = {"TIE": "bancos", "CAJ": "caja", "SOC": "socios"}
_CUENTA_COBRO = {"EFE": "caja", "TAR": "bancos", "SIN": "bancos"}


def leer(envio):
    """{"monto", "pago"} del POS → (monto, pago) o (0, "") si no hay envío."""
    from .models import FacturaVenta

    if not envio:
        return Decimal("0"), ""
    try:
        monto = Decimal(str(envio.get("monto") or 0)).quantize(CENTIMO)
    except Exception:
        raise ValidationError("El monto del envío no es válido.")
    if monto <= 0:
        return Decimal("0"), ""
    if monto > Decimal("100000"):
        raise ValidationError("El envío no puede pasar de ₡100.000. Revisá el monto.")
    pago = str(envio.get("pago") or "")
    if pago not in FacturaVenta.PagoEnvio.values:
        raise ValidationError("Elegí cómo se le pagó al mensajero.")
    return monto, pago


def repartir_mixto(pagos, envio):
    """Saca el envío de los pagos de un cobro mixto. Devuelve (medio del
    envío, pagos que quedan para la venta)."""
    pagos = [dict(p) for p in pagos]
    for medio in PREFERENCIA_MIXTO:
        p = next((x for x in pagos if x["medio"] == medio and x["monto"] >= envio), None)
        if p is not None:
            p["monto"] -= envio
            return medio, [x for x in pagos if x["monto"] > 0]
    raise ValidationError("El envío tiene que quedar completo en un solo medio de pago.")


def registrar(factura, sesion_caja, usuario):
    """Caja y contabilidad del envío de una venta ya guardada."""
    from caja.models import MovimientoCaja
    from caja.services import registrar_movimiento_caja
    from contabilidad.services import cuenta, registrar_asiento
    from django.utils import timezone

    monto = factura.envio
    if monto <= 0:
        return
    if factura.envio_medio == "EFE":
        registrar_movimiento_caja(sesion=sesion_caja, tipo=MovimientoCaja.Tipo.ENVIO, monto=monto,
                                  descripcion=f"Envío cobrado {factura.numero}", referencia=factura.numero,
                                  usuario=usuario)
    if factura.envio_pago == "CAJ":
        registrar_movimiento_caja(sesion=sesion_caja, tipo=MovimientoCaja.Tipo.ENVIO, monto=-monto,
                                  descripcion=f"Pago al mensajero {factura.numero}", referencia=factura.numero,
                                  usuario=usuario)
    e = factura.empresa
    registrar_asiento(
        empresa=e, fecha=timezone.localdate(factura.creado_en), descripcion=f"Envío {factura.numero}",
        origen="VEN", referencia=factura.numero, usuario=usuario,
        lineas=[
            {"cuenta": cuenta(e, _CUENTA_COBRO[factura.envio_medio]), "debe": monto, "detalle": factura.numero},
            {"cuenta": cuenta(e, "envios"), "haber": monto},
            {"cuenta": cuenta(e, "envios"), "debe": monto},
            {"cuenta": cuenta(e, _CUENTA_PAGO[factura.envio_pago]), "haber": monto, "detalle": "Mensajero"},
        ],
    )


def anular(factura, sesion_caja, usuario):
    """Deshace caja y asiento del envío de una venta que se anula."""
    from caja.models import MovimientoCaja
    from caja.services import registrar_movimiento_caja
    from contabilidad.services import cuenta, registrar_asiento
    from django.utils import timezone

    monto = factura.envio
    if monto <= 0:
        return
    mueve_caja = factura.envio_medio == "EFE" or factura.envio_pago == "CAJ"
    if mueve_caja and sesion_caja is None:
        raise ValidationError("Para anular una venta con envío en efectivo debe tener una caja abierta.")
    if factura.envio_medio == "EFE":
        registrar_movimiento_caja(sesion=sesion_caja, tipo=MovimientoCaja.Tipo.ENVIO, monto=-monto,
                                  descripcion=f"Anulación envío {factura.numero}", referencia=factura.numero,
                                  usuario=usuario)
    if factura.envio_pago == "CAJ":
        registrar_movimiento_caja(sesion=sesion_caja, tipo=MovimientoCaja.Tipo.ENVIO, monto=monto,
                                  descripcion=f"Anulación pago al mensajero {factura.numero}",
                                  referencia=factura.numero, usuario=usuario)
    e = factura.empresa
    registrar_asiento(
        empresa=e, fecha=timezone.localdate(), descripcion=f"Anulación envío {factura.numero}",
        origen="ANU", referencia=factura.numero, usuario=usuario,
        lineas=[
            {"cuenta": cuenta(e, _CUENTA_PAGO[factura.envio_pago]), "debe": monto},
            {"cuenta": cuenta(e, "envios"), "haber": monto},
            {"cuenta": cuenta(e, "envios"), "debe": monto},
            {"cuenta": cuenta(e, _CUENTA_COBRO[factura.envio_medio]), "haber": monto},
        ],
    )
