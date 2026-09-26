"""Servicios de compras.

recibir_compra es la contraparte de la venta: entra mercadería al inventario
(recalcula el costo promedio vía el servicio de inventario) y genera su
asiento en la misma transacción:

    Debe  Inventario de mercadería   total (sin IVA)
    Debe  IVA acreditable            iva   (solo régimen tradicional, con factura)
        Haber  Bancos (contado) o CxP proveedor (crédito)   total + iva

Todo o nada: si algo falla, no queda ni stock ni asiento a medias.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from contabilidad.services import cuenta, registrar_asiento
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from core.models import Empresa
from ventas.models import Consecutivo

from .models import Compra, LineaCompra, Proveedor


@transaction.atomic
def crear_compra(*, proveedor, sucursal, lineas, forma_pago="CON", factura_proveedor="", usuario=None,
                 iva=0) -> Compra:
    """Crea la compra en borrador.

    lineas: dicts {producto, cantidad, costo_unitario, cantidad_bonificada?}.

    `cantidad` y `costo_unitario` son los de la FACTURA del proveedor, y de
    ellos sale el total: así el asiento contable y la deuda con el proveedor
    cuadran contra el papel que él va a cobrar. Las unidades bonificadas
    (los "12+1") entran a bodega pero no suman al total, porque nadie las
    cobra.
    """
    if not lineas:
        raise ValidationError("La compra no tiene líneas.")
    empresa = sucursal.empresa
    iva = Decimal(str(iva or 0)).quantize(Decimal("0.01"))
    if iva < 0:
        raise ValidationError("El IVA de la factura no puede ser negativo.")
    if iva > 0 and empresa.regimen != Empresa.Regimen.TRADICIONAL:
        # En el simplificado el IVA de las compras no se acredita: es costo.
        raise ValidationError("En régimen simplificado el IVA de la compra no se separa: "
                              "anotá el costo con todo incluido y dejá el IVA en 0.")
    # La misma factura del proveedor no entra dos veces (auditoría 26/09/2026,
    # INV-04). Con dos personas ingresando mercadería desde lugares distintos
    # —Francisco desde el celular, Oscar desde la computadora— la misma factura
    # podía cargarse dos veces: el doble de stock y el doble de deuda.
    factura_proveedor = (factura_proveedor or "").strip()
    if factura_proveedor:
        repetida = (
            Compra.objects.filter(proveedor=proveedor, factura_proveedor__iexact=factura_proveedor)
            .exclude(estado=Compra.Estado.ANULADA).first()
        )
        if repetida is not None:
            raise ValidationError(
                f"La factura {factura_proveedor} de {proveedor.nombre} ya se ingresó "
                f"({repetida.numero}, {repetida.creado_en:%d/%m/%Y}). Si de verdad es otra, "
                "revise el número; si fue un error, anule la anterior primero."
            )
    numero = Consecutivo.tomar(empresa, "OC")
    compra = Compra.objects.create(
        empresa=empresa, sucursal=sucursal, proveedor=proveedor, numero=numero,
        forma_pago=forma_pago, factura_proveedor=factura_proveedor, usuario=usuario, iva=iva,
    )
    total = Decimal("0")
    for l in lineas:
        cantidad = Decimal(str(l["cantidad"]))
        costo = Decimal(str(l["costo_unitario"]))
        bonificada = Decimal(str(l.get("cantidad_bonificada") or 0))
        if cantidad < 0 or costo < 0:
            raise ValidationError("Cantidad o costo inválidos en una línea.")
        if bonificada < 0:
            raise ValidationError("La bonificación no puede ser negativa.")
        # Cantidad facturada 0 vale solo si vienen bonificadas: es mercadería
        # de regalo del proveedor, que entra a bodega a costo cero.
        if cantidad + bonificada <= 0:
            raise ValidationError("Una línea tiene que traer unidades facturadas o bonificadas.")
        # El total sale SOLO de lo facturado. Las bonificadas entran a bodega
        # más abajo (recibir_compra), no acá.
        total_l = (cantidad * costo).quantize(Decimal("0.01"))
        LineaCompra.objects.create(
            compra=compra, producto=l["producto"], cantidad=cantidad,
            cantidad_bonificada=bonificada, costo_unitario=costo, total=total_l,
        )
        total += total_l
    compra.total = total
    compra.save(update_fields=["total"])
    return compra


@transaction.atomic
def crear_y_recibir_compra(*, usuario=None, **datos) -> Compra:
    """Crea la compra y la recibe en una sola transacción: o entra todo al
    inventario y a la contabilidad, o no queda nada (INV-03)."""
    compra = crear_compra(usuario=usuario, **datos)
    return recibir_compra(compra=compra, usuario=usuario)


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
        # Entra a bodega TODO lo que llegó (facturado + bonificado), valorado
        # al costo real por unidad. Con una bonificación, ese costo es menor
        # que el facturado: es el descuento repartido entre todas las
        # unidades. Si en vez de esto entraran las facturadas a su costo y las
        # bonificadas a cero, el costo promedio del producto quedaría inflado
        # —y como el precio de venta se calcula sobre el costo, el descuento
        # que consiguió el vendedor nunca llegaría al precio—.
        registrar_movimiento(
            producto=linea.producto, bodega=bodega, tipo="COM",
            cantidad=linea.cantidad_recibida, costo_unitario=linea.costo_real_unitario,
            referencia=compra.numero,
            motivo=(f"Incluye {linea.cantidad_bonificada:g} bonificada(s) del proveedor"
                    if linea.cantidad_bonificada else ""),
            usuario=usuario,
        )

    empresa = compra.empresa
    contra = cuenta(empresa, "bancos") if compra.forma_pago == Compra.Pago.CONTADO else _cuenta_cxp(empresa)
    # Una compra que es TODA regalo del proveedor (solo bonificadas) no mueve
    # plata: la mercadería entra a bodega a costo cero y no hay asiento que
    # hacer. Un asiento en cero no dice nada y el motor contable lo rechaza.
    if compra.total_factura:
        registrar_asiento(
            empresa=empresa, fecha=timezone.now().date(),
            descripcion=f"Compra {compra.numero} — {compra.proveedor.nombre}",
            origen="MAN", referencia=compra.numero, usuario=usuario,
            lineas=_lineas_asiento(compra, contra),
        )

    if compra.forma_pago == Compra.Pago.CREDITO:
        proveedor = Proveedor.objects.select_for_update().get(pk=compra.proveedor_id)
        proveedor.saldo += compra.total_factura
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
        # Sale lo mismo que entró: facturado + bonificado. Sacar solo lo
        # facturado dejaría las unidades regaladas en bodega sin compra que
        # las respalde.
        registrar_movimiento(
            producto=linea.producto, bodega=bodega, tipo="DEV",
            cantidad=-linea.cantidad_recibida, referencia=f"ANU-{compra.numero}",
            motivo=f"Anulación de compra: {motivo.strip()}", usuario=usuario,
        )

    # Asiento inverso del de recepción.
    empresa = compra.empresa
    contra = cuenta(empresa, "bancos") if compra.forma_pago == Compra.Pago.CONTADO else _cuenta_cxp(empresa)
    if compra.total_factura:   # una compra toda de regalo no tuvo asiento
        registrar_asiento(
            empresa=empresa, fecha=timezone.now().date(),
            descripcion=f"Anulación compra {compra.numero} — {compra.proveedor.nombre}",
            origen="ANU", referencia=compra.numero, usuario=usuario,
            # El inverso exacto del de recepción: lo que era debe pasa a haber.
            lineas=[
                {"cuenta": l["cuenta"], "haber": l["debe"]} if "debe" in l
                else {"cuenta": l["cuenta"], "debe": l["haber"]}
                for l in _lineas_asiento(compra, contra)
            ],
        )

    if compra.forma_pago == Compra.Pago.CREDITO:
        proveedor = Proveedor.objects.select_for_update().get(pk=compra.proveedor_id)
        proveedor.saldo -= compra.total_factura
        proveedor.save(update_fields=["saldo"])

    compra.estado = Compra.Estado.ANULADA
    compra.motivo_anulacion = motivo.strip()
    compra.anulada_en = timezone.now()
    compra.anulada_por = usuario
    compra.save(update_fields=["estado", "motivo_anulacion", "anulada_en", "anulada_por"])
    return compra


def _lineas_asiento(compra, contra):
    """Líneas del asiento de recepción. El IVA acreditable va aparte del
    inventario: si entrara al costo, el costo promedio quedaría inflado 13 %
    y el negocio pagaría dos veces el mismo IVA (en la compra y en la venta)."""
    empresa = compra.empresa
    lineas = [{"cuenta": cuenta(empresa, "inventario"), "debe": compra.total}]
    if compra.iva:
        lineas.append({"cuenta": cuenta(empresa, "iva_acreditable"), "debe": compra.iva})
    lineas.append({"cuenta": contra, "haber": compra.total_factura})
    return lineas


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
