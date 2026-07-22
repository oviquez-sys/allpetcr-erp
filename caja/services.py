"""Servicios de dominio de caja: apertura, movimientos y cierre con arqueo."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import MovimientoCaja, SesionCaja


def sesion_abierta_de(usuario):
    return SesionCaja.objects.filter(usuario=usuario, estado=SesionCaja.Estado.ABIERTA).first()


@transaction.atomic
def abrir_caja(*, sucursal, usuario, monto_apertura) -> SesionCaja:
    monto_apertura = Decimal(monto_apertura)
    if monto_apertura < 0:
        raise ValidationError("El monto de apertura no puede ser negativo.")
    if sesion_abierta_de(usuario):
        raise ValidationError("Ya tiene una sesión de caja abierta. Ciérrela antes de abrir otra.")
    sesion = SesionCaja.objects.create(
        sucursal=sucursal, usuario=usuario, monto_apertura=monto_apertura
    )
    # Abrir con ₡0 es válido; en ese caso no se crea un movimiento nulo
    # (viola el CHECK de monto distinto de cero y no aporta al esperado).
    if monto_apertura > 0:
        MovimientoCaja.objects.create(
            sesion=sesion, tipo=MovimientoCaja.Tipo.APERTURA, monto=monto_apertura,
            descripcion="Apertura de caja", usuario=usuario,
        )
    return sesion


@transaction.atomic
def registrar_movimiento_caja(*, sesion, tipo, monto, descripcion="", referencia="", usuario=None) -> MovimientoCaja:
    monto = Decimal(monto)
    if sesion.estado != SesionCaja.Estado.ABIERTA:
        raise ValidationError("La sesión de caja está cerrada: no admite movimientos.")
    if monto == 0:
        raise ValidationError("El monto no puede ser cero.")
    return MovimientoCaja.objects.create(
        sesion=sesion, tipo=tipo, monto=monto,
        descripcion=descripcion, referencia=referencia, usuario=usuario,
    )


def monto_esperado(sesion) -> Decimal:
    total = sesion.movimientos.aggregate(t=Sum("monto"))["t"]
    return total if total is not None else Decimal("0")


@transaction.atomic
def cerrar_caja(*, sesion, monto_contado, usuario=None) -> SesionCaja:
    """Arqueo: se registra lo contado físicamente y se calcula la diferencia
    contra lo esperado. La sesión queda inmutable."""
    sesion = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
    if sesion.estado != SesionCaja.Estado.ABIERTA:
        raise ValidationError("La sesión ya está cerrada.")
    monto_contado = Decimal(monto_contado)
    if monto_contado < 0:
        raise ValidationError("El monto contado no puede ser negativo.")
    sesion.monto_esperado = monto_esperado(sesion)
    sesion.monto_contado = monto_contado
    sesion.diferencia = monto_contado - sesion.monto_esperado
    sesion.estado = SesionCaja.Estado.CERRADA
    sesion.cerrada_en = timezone.now()
    sesion.save()
    return sesion
