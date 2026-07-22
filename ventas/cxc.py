"""Servicios de cuentas por cobrar (CxC).

Reglas:
- Vender a crédito exige cliente con límite y crédito disponible suficiente.
- El saldo del cliente y el del documento se mantienen consistentes en la
  misma transacción del abono.
- Un abono en efectivo entra a la caja abierta (el dinero es real).
- Anular una factura a crédito cancela su CxC y libera el crédito del cliente,
  siempre que no tenga abonos (si ya pagó parte, se bloquea: primero se
  reversa el abono, criterio de S5 con el motor contable).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Abono, Cliente, DocumentoCxC, FacturaVenta


def validar_credito(cliente, monto):
    if cliente is None:
        raise ValidationError("Una venta a crédito requiere seleccionar un cliente.")
    if cliente.limite_credito <= 0:
        raise ValidationError(f"{cliente.nombre} no tiene crédito habilitado.")
    if monto > cliente.credito_disponible:
        raise ValidationError(
            f"Crédito insuficiente para {cliente.nombre}: disponible "
            f"₡{cliente.credito_disponible}, venta ₡{monto}."
        )


@transaction.atomic
def crear_cxc(*, factura: FacturaVenta) -> DocumentoCxC:
    """Genera la CxC de una venta a crédito y sube el saldo del cliente."""
    cliente = Cliente.objects.select_for_update().get(pk=factura.cliente_id)
    validar_credito(cliente, factura.total)
    doc = DocumentoCxC.objects.create(
        cliente=cliente, factura=factura,
        monto_original=factura.total, saldo=factura.total,
    )
    cliente.saldo += factura.total
    cliente.save(update_fields=["saldo"])
    return doc


@transaction.atomic
def registrar_abono(*, documento, monto, medio="EFE", referencia="", usuario=None) -> Abono:
    monto = Decimal(str(monto))
    documento = DocumentoCxC.objects.select_for_update().get(pk=documento.pk)
    if documento.estado != DocumentoCxC.Estado.PENDIENTE:
        raise ValidationError("El documento no está pendiente de cobro.")
    if monto <= 0:
        raise ValidationError("El abono debe ser mayor que cero.")
    if monto > documento.saldo:
        raise ValidationError(
            f"El abono (₡{monto}) excede el saldo pendiente (₡{documento.saldo})."
        )

    abono = Abono.objects.create(
        documento=documento, monto=monto, medio=medio, referencia=referencia, usuario=usuario
    )
    documento.saldo -= monto
    if documento.saldo == 0:
        documento.estado = DocumentoCxC.Estado.PAGADO
    documento.save(update_fields=["saldo", "estado"])

    cliente = Cliente.objects.select_for_update().get(pk=documento.cliente_id)
    cliente.saldo -= monto
    cliente.save(update_fields=["saldo"])

    # El efectivo cobrado entra a la caja abierta del usuario, si la hay.
    if medio == Abono.Medio.EFECTIVO and usuario is not None:
        from caja.models import MovimientoCaja
        from caja.services import registrar_movimiento_caja, sesion_abierta_de
        sesion = sesion_abierta_de(usuario)
        if sesion is not None:
            registrar_movimiento_caja(
                sesion=sesion, tipo=MovimientoCaja.Tipo.INGRESO, monto=monto,
                descripcion=f"Abono CxC {documento.factura.numero}",
                referencia=documento.factura.numero, usuario=usuario,
            )

    # Asiento automático del cobro (Debe Caja/Bancos, Haber CxC).
    from .contabilizar import asentar_abono
    asentar_abono(abono, usuario=usuario)
    return abono


@transaction.atomic
def cancelar_cxc_por_anulacion(*, factura, usuario=None):
    """Al anular una factura a crédito: si su CxC no tiene abonos, se cancela
    y se libera el crédito del cliente. Si ya tiene abonos, se bloquea la
    anulación (el dinero cobrado debe tratarse aparte)."""
    doc = DocumentoCxC.objects.select_for_update().filter(factura=factura).first()
    if doc is None:
        return
    if doc.abonos.exists():
        raise ValidationError(
            "No se puede anular: la venta a crédito ya tiene abonos. "
            "Gestione primero la devolución del dinero cobrado."
        )
    cliente = Cliente.objects.select_for_update().get(pk=doc.cliente_id)
    cliente.saldo -= doc.saldo
    cliente.save(update_fields=["saldo"])
    doc.saldo = Decimal("0")
    doc.estado = DocumentoCxC.Estado.ANULADO
    doc.save(update_fields=["saldo", "estado"])
