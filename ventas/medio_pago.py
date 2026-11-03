"""Corregir el medio de pago de una venta (02/11/2026, pedido de Oscar).

Caso real: "la cliente iba a pagar con tarjeta y al final hizo un SINPE".
Si la venta queda como tarjeta, el reporte por medio miente y el cierre no
calza (falta en tarjeta, sobra en SINPE). Corregirla en el momento deja todo
bien sin tener que explicarlo al cerrar.

Reglas, y por qué:
- Solo efectivo, tarjeta y SINPE, entre ellos. El fiado tiene su cuenta por
  cobrar y el pago mixto su reparto: cambiarlos es anular y volver a vender.
- Solo mientras la caja de esa venta sigue abierta. Un cierre ya hecho no se
  reabre por la puerta de atrás: lo que no calzó ahí, se explicó ahí.
- No si la venta tiene devoluciones (el reembolso se calculó con el medio
  viejo) ni si ya tiene comprobante electrónico de Hacienda (ese documento
  dice el medio y no se edita).
- Efectivo de por medio: un movimiento de caja (tipo COR) entra o saca la
  plata de lo esperado de la gaveta, y un asiento pasa el monto de Caja a
  Bancos o al revés. Entre tarjeta y SINPE no hay asiento: los dos van a
  Bancos.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CambioMedioPago, FacturaVenta

CAMBIABLES = ("EFE", "TAR", "SIN")


def se_puede_cambiar(factura) -> str:
    """'' si se puede; si no, el porqué en palabras de la tienda."""
    from caja.models import SesionCaja

    if factura.estado != FacturaVenta.Estado.EMITIDA:
        return "La venta está anulada."
    if factura.medio_pago not in CAMBIABLES:
        return "Solo se corrigen ventas en efectivo, tarjeta o SINPE (no fiado ni pago mixto)."
    if factura.sesion_caja.estado != SesionCaja.Estado.ABIERTA:
        return "La caja de esa venta ya se cerró: la diferencia se explicó en el cierre."
    if factura.total <= 0:
        return "La venta no cobró nada."
    if factura.devoluciones.exists():
        return "La venta tiene devoluciones."
    if hasattr(factura, "factura_electronica") or hasattr(factura, "tiquete_electronico"):
        return "La venta ya tiene comprobante electrónico de Hacienda."
    return ""


@transaction.atomic
def cambiar_medio_pago(*, factura, nuevo, usuario, motivo) -> CambioMedioPago:
    from caja.models import MovimientoCaja
    from caja.services import registrar_movimiento_caja
    from contabilidad.services import cuenta, registrar_asiento

    factura = FacturaVenta.objects.select_for_update().select_related("sesion_caja", "empresa").get(pk=factura.pk)
    if nuevo not in CAMBIABLES:
        raise ValidationError("Ese medio de pago no se puede elegir aquí.")
    if nuevo == factura.medio_pago:
        raise ValidationError("La venta ya está con ese medio de pago.")
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ValidationError("Contá por qué cambió el medio de pago.")
    porque_no = se_puede_cambiar(factura)
    if porque_no:
        raise ValidationError(porque_no)

    anterior, monto = factura.medio_pago, factura.total
    nombres = dict(FacturaVenta.MedioPago.choices)
    texto = f"{factura.numero}: {nombres[anterior]} → {nombres[nuevo]}"
    if "EFE" in (anterior, nuevo):
        # La gaveta: si era efectivo, esa plata nunca entró; si pasa a
        # efectivo, sí entró. El movimiento original de la venta no se toca
        # (la tabla es de solo agregar): se compensa con otro.
        registrar_movimiento_caja(
            sesion=factura.sesion_caja, tipo=MovimientoCaja.Tipo.CORRECCION,
            monto=monto if nuevo == "EFE" else -monto, descripcion=f"Cambio de medio {texto}"[:200],
            referencia=factura.numero, usuario=usuario,
        )
        de, a = ("caja", "bancos") if anterior == "EFE" else ("bancos", "caja")
        registrar_asiento(
            empresa=factura.empresa, fecha=timezone.localdate(), origen="COR", referencia=factura.numero,
            descripcion=f"Corrección de medio de pago {texto}"[:200], usuario=usuario,
            lineas=[{"cuenta": cuenta(factura.empresa, a), "debe": monto},
                    {"cuenta": cuenta(factura.empresa, de), "haber": monto}],
        )
    campos = ["medio_pago"]
    factura.medio_pago = nuevo
    if anterior == "EFE":
        # Lo recibido y el vuelto eran del pago en efectivo: ya no aplican.
        factura.monto_recibido = factura.vuelto = None
        campos += ["monto_recibido", "vuelto"]
    factura.save(update_fields=campos)
    return CambioMedioPago.objects.create(factura=factura, anterior=anterior, nuevo=nuevo, monto=monto,
                                          motivo=motivo[:200], usuario=usuario if getattr(usuario, "pk", None) else None)


def candidatas_cruce(sesion, medio_registrado, monto):
    """Ventas de la caja que pueden ser "la que se cobró por otro medio":
    registradas con `medio_registrado` y por exactamente `monto`. Las usa la
    pantalla de cierre para ofrecer corregirlas con un clic."""
    return list(sesion.ventas.filter(estado=FacturaVenta.Estado.EMITIDA, medio_pago=medio_registrado,
                                     total=monto).select_related("cliente").order_by("-creado_en")[:5])
