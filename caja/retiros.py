"""Sacar efectivo de la gaveta para depositarlo, y marcarlo depositado
(02/11/2026, pedido de Oscar).

La gaveta se mantiene bajo unos ₡50-60 mil: lo que pasa de ahí se saca en un
sobre y se deposita en el Banco Nacional otro día. Dos momentos:

1. Retiro: sale de la gaveta. Movimiento de caja negativo (tipo RET), así
   lo esperado del cierre ya lo descuenta. Sin asiento contable: la plata
   sigue en "Caja general" (la gaveta y el sobre son la misma cuenta).
2. Depósito: llega al banco. Asiento Bancos (debe) contra Caja general
   (haber), con el número de comprobante.

Así un retiro que nunca llegó al banco no se pierde de vista: queda en la
lista "por depositar" hasta que alguien anota el comprobante.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import MovimientoCaja, RetiroCaja, SesionCaja
from .services import monto_esperado, registrar_movimiento_caja


@transaction.atomic
def registrar_retiro(*, sesion, usuario, conteo=None, monto=None, nota="") -> RetiroCaja:
    """conteo {"20000": 2, "10000": 1} o, si no se contó por billete (se
    registra al cerrar lo que ya se había sacado), un monto suelto."""
    from .denominaciones import TODAS, total

    sesion = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
    if sesion.estado != SesionCaja.Estado.ABIERTA:
        raise ValidationError("La caja está cerrada: no se le puede sacar efectivo.")
    limpio = None
    if conteo:
        limpio = {}
        for valor, cantidad in conteo.items():
            cantidad = int(cantidad or 0)
            if int(valor) not in TODAS:
                raise ValidationError(f"₡{valor} no es un billete ni una moneda vigente.")
            if cantidad < 0:
                raise ValidationError("La cantidad no puede ser negativa.")
            if cantidad:
                limpio[str(int(valor))] = cantidad
        monto = Decimal(total(limpio))
    monto = Decimal(monto or 0)
    if monto <= 0:
        raise ValidationError("Anotá cuánto se saca.")
    # No se puede sacar más de lo que debería haber: sería tapar un faltante
    # con un "retiro" que nunca llegó al banco.
    hay = monto_esperado(sesion)
    if monto > hay:
        raise ValidationError(f"En la gaveta debería haber ₡{hay:,.0f}; no se pueden sacar ₡{monto:,.0f}."
                              .replace(",", "."))
    retiro = RetiroCaja.objects.create(sesion=sesion, monto=monto, conteo=limpio, nota=(nota or "")[:200],
                                       usuario=usuario if getattr(usuario, "pk", None) else None)
    registrar_movimiento_caja(sesion=sesion, tipo=MovimientoCaja.Tipo.RETIRO, monto=-monto,
                              descripcion=f"Retiro para depositar{': ' + nota if nota else ''}"[:200],
                              referencia=retiro.referencia, usuario=retiro.usuario)
    return retiro


@transaction.atomic
def registrar_deposito(*, retiros, usuario, fecha=None, comprobante="") -> list:
    """Marca como depositados uno o varios retiros (un mismo depósito puede
    juntar varios sobres) y hace UN asiento Bancos contra Caja."""
    from contabilidad.services import cuenta, registrar_asiento

    comprobante = (comprobante or "").strip()
    if not comprobante:
        raise ValidationError("Anotá el número del comprobante del depósito.")
    fecha = fecha or timezone.localdate()
    ids = [r.pk for r in retiros]
    pendientes = list(RetiroCaja.objects.select_for_update().select_related("sesion__sucursal__empresa")
                      .filter(pk__in=ids, estado=RetiroCaja.Estado.POR_DEPOSITAR))
    if not pendientes or len(pendientes) != len(ids):
        raise ValidationError("Algún retiro ya estaba depositado o no existe.")
    empresa = pendientes[0].sesion.sucursal.empresa
    if any(r.sesion.sucursal.empresa_id != empresa.pk for r in pendientes):
        raise ValidationError("Los retiros son de empresas distintas.")
    total = sum((r.monto for r in pendientes), Decimal("0"))
    referencias = ", ".join(r.referencia for r in pendientes)
    registrar_asiento(
        empresa=empresa, fecha=fecha, origen="DEP", referencia=comprobante[:40],
        descripcion=f"Depósito de efectivo ({referencias})"[:200], usuario=usuario,
        lineas=[{"cuenta": cuenta(empresa, "bancos"), "debe": total, "detalle": comprobante},
                {"cuenta": cuenta(empresa, "caja"), "haber": total, "detalle": referencias}],
    )
    for r in pendientes:
        r.estado, r.depositado_en, r.comprobante = RetiroCaja.Estado.DEPOSITADO, fecha, comprobante[:60]
        r.depositado_por = usuario if getattr(usuario, "pk", None) else None
        r.save(update_fields=["estado", "depositado_en", "comprobante", "depositado_por"])
    return pendientes


def por_depositar(empresa):
    return (RetiroCaja.objects.filter(sesion__sucursal__empresa=empresa, estado=RetiroCaja.Estado.POR_DEPOSITAR)
            .select_related("usuario", "sesion").order_by("creado_en"))
