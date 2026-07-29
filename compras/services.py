"""Servicios de compras.

recibir_compra es la contraparte de la venta: entra mercadería al inventario
(recalcula el costo promedio vía el servicio de inventario) y genera su
asiento en la misma transacción:

    Debe  Inventario de mercadería   total
        Haber  Bancos (contado) o CxP proveedor (crédito)   total

Todo o nada: si algo falla, no queda ni stock ni asiento a medias.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from contabilidad.services import cuenta, registrar_asiento
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import Consecutivo

from .models import Compra, LineaCompra, Proveedor


@transaction.atomic
def crear_compra(*, proveedor, sucursal, lineas, forma_pago="CON", factura_proveedor="", usuario=None) -> Compra:
    """Crea la compra en borrador. lineas: dicts {producto, cantidad, costo_unitario}."""
    if not lineas:
        raise ValidationError("La compra no tiene líneas.")
    empresa = sucursal.empresa
    numero = Consecutivo.tomar(empresa, "OC")
    compra = Compra.objects.create(
        empresa=empresa, sucursal=sucursal, proveedor=proveedor, numero=numero,
        forma_pago=forma_pago, factura_proveedor=factura_proveedor, usuario=usuario,
    )
    total = Decimal("0")
    for l in lineas:
        cantidad = Decimal(str(l["cantidad"]))
        costo = Decimal(str(l["costo_unitario"]))
        if cantidad <= 0 or costo < 0:
            raise ValidationError("Cantidad o costo inválidos en una línea.")
        total_l = (cantidad * costo).quantize(Decimal("0.01"))
        LineaCompra.objects.create(
            compra=compra, producto=l["producto"], cantidad=cantidad,
            costo_unitario=costo, total=total_l,
        )
        total += total_l
    compra.total = total
    compra.save(update_fields=["total"])
    return compra


@transaction.atomic
def recibir_compra(*, compra, usuario=None) -> Compra:
    """Recibe la mercadería: entra al kardex (recalcula costo promedio),
    genera el asiento y, si es a crédito, sube el saldo del proveedor."""
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.estado != Compra.Estado.BORRADOR:
        raise ValidationError("Solo se puede recibir una compra en borrador.")
    # Bodega principal explícita (auditoría 2026-07-28, BE-09).
    bodega = Bodega.principal_de(compra.sucursal)
    if bodega is None:
        raise ValidationError("La sucursal no tiene bodega configurada.")

    for linea in compra.lineas.select_related("producto"):
        registrar_movimiento(
            producto=linea.producto, bodega=bodega, tipo="COM",
            cantidad=linea.cantidad, costo_unitario=linea.costo_unitario,
            referencia=compra.numero, usuario=usuario,
        )

    empresa = compra.empresa
    contra = cuenta(empresa, "bancos") if compra.forma_pago == Compra.Pago.CONTADO else _cuenta_cxp(empresa)
    registrar_asiento(
        empresa=empresa, fecha=timezone.now().date(),
        descripcion=f"Compra {compra.numero} — {compra.proveedor.nombre}",
        origen="MAN", referencia=compra.numero, usuario=usuario,
        lineas=[
            {"cuenta": cuenta(empresa, "inventario"), "debe": compra.total},
            {"cuenta": contra, "haber": compra.total},
        ],
    )

    if compra.forma_pago == Compra.Pago.CREDITO:
        proveedor = Proveedor.objects.select_for_update().get(pk=compra.proveedor_id)
        proveedor.saldo += compra.total
        proveedor.save(update_fields=["saldo"])

    compra.estado = Compra.Estado.RECIBIDA
    compra.recibida_en = timezone.now()
    compra.save(update_fields=["estado", "recibida_en"])
    return compra


@transaction.atomic
def anular_compra(*, compra, motivo, usuario=None) -> Compra:
    """Reversa una compra recibida por error: saca del inventario lo que había
    entrado, registra el asiento inverso y, si fue a crédito, baja el saldo del
    proveedor. Nunca borra la compra: queda como ANULADA con quién/cuándo/por qué.

    Guard importante: si la mercadería ya se vendió (el stock no alcanza para
    devolver), la reversa se rechaza limpio; no deja inventario negativo."""
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.estado != Compra.Estado.RECIBIDA:
        raise ValidationError("Solo se puede anular una compra que está recibida.")
    if not motivo or not motivo.strip():
        raise ValidationError("El motivo de la anulación es obligatorio.")

    # Bodega principal explícita (auditoría 2026-07-28, BE-09).
    bodega = Bodega.principal_de(compra.sucursal)
    if bodega is None:
        raise ValidationError("La sucursal no tiene bodega configurada.")

    # Saca del kardex lo que había entrado (revienta si ya no hay stock).
    for linea in compra.lineas.select_related("producto"):
        registrar_movimiento(
            producto=linea.producto, bodega=bodega, tipo="DEV",
            cantidad=-linea.cantidad, referencia=f"ANU-{compra.numero}",
            motivo=f"Anulación de compra: {motivo.strip()}", usuario=usuario,
        )

    # Asiento inverso del de recepción.
    empresa = compra.empresa
    contra = cuenta(empresa, "bancos") if compra.forma_pago == Compra.Pago.CONTADO else _cuenta_cxp(empresa)
    registrar_asiento(
        empresa=empresa, fecha=timezone.now().date(),
        descripcion=f"Anulación compra {compra.numero} — {compra.proveedor.nombre}",
        origen="ANU", referencia=compra.numero, usuario=usuario,
        lineas=[
            {"cuenta": contra, "debe": compra.total},
            {"cuenta": cuenta(empresa, "inventario"), "haber": compra.total},
        ],
    )

    if compra.forma_pago == Compra.Pago.CREDITO:
        proveedor = Proveedor.objects.select_for_update().get(pk=compra.proveedor_id)
        proveedor.saldo -= compra.total
        proveedor.save(update_fields=["saldo"])

    compra.estado = Compra.Estado.ANULADA
    compra.motivo_anulacion = motivo.strip()
    compra.anulada_en = timezone.now()
    compra.anulada_por = usuario
    compra.save(update_fields=["estado", "motivo_anulacion", "anulada_en", "anulada_por"])
    return compra


def _cuenta_cxp(empresa):
    """Cuenta de cuentas por pagar a proveedores. Se crea si no existe en el
    plan (el plan base no la trae para no ensuciar cuando solo se compra de
    contado)."""
    from contabilidad.models import CuentaContable
    from contabilidad.services import asegurar_plan
    asegurar_plan(empresa)
    obj, _ = CuentaContable.objects.get_or_create(
        empresa=empresa, codigo="2101",
        defaults={"nombre": "Cuentas por pagar proveedores", "naturaleza": "P", "movimiento": True},
    )
    return obj
