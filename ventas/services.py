"""Servicios de dominio de ventas.

registrar_venta es LA transacción central del sistema: factura + kardex +
caja se confirman juntos o no se confirma nada. El motor fiscal (Fase 2 §6)
decide el desglose de impuestos según el régimen de la empresa:

- RTS (hoy): el precio es el total; no se desglosa IVA en la venta.
- Tradicional (futuro): el precio incluye IVA según la tarifa del producto;
  se desglosa subtotal e impuesto, y aquí se activará el adaptador de
  facturación electrónica v4.4.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from caja.models import MovimientoCaja, SesionCaja
from caja.services import registrar_movimiento_caja
from catalogo.models import Producto
from core.models import Empresa
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .models import Consecutivo, FacturaVenta, LineaVenta, PagoVenta

# Descuento máximo que un cajero puede aplicar por línea sin que un gerente
# autorice la venta (SEC-001, auditoría 2026-08-10). Antes no había ningún
# techo propio: el único freno era no vender bajo costo, que no protege el
# margen de productos con margen amplio (un cajero podía regalar la mitad
# del margen a un cómplice sin que nada lo bloqueara ni lo distinguiera de
# un descuento legítimo). Valor de negocio, no técnico — decidir con el
# dueño antes de cambiarlo.
DESCUENTO_MAXIMO_SIN_AUTORIZACION = Decimal("15")

# Valor máximo (precio de lista × cantidad) que un cajero puede regalar por
# línea sin que un gerente autorice la venta (SEC-006, auditoría 2026-08-10).
# Antes una regalía no tenía techo ni control de rol: cualquier cajero podía
# marcar es_regalia y sacar mercadería de cualquier valor sin cobrar nada, sin
# el piso de costo que sí protege a los descuentos (SEC-001). Valor de
# negocio, no técnico — decidir con el dueño antes de cambiarlo.
REGALIA_MAXIMA_SIN_AUTORIZACION = Decimal("5000")


def _desglose_fiscal(empresa, producto, total_linea):
    """Devuelve (subtotal, impuesto) de una línea según el régimen."""
    if empresa.regimen == Empresa.Regimen.SIMPLIFICADO:
        return total_linea, Decimal("0")
    # Sin tarifa asignada se usa la general (13 %), no 0: ver
    # catalogo.models.TARIFA_GENERAL_IVA. Antes un producto sin impuesto se
    # vendía en régimen tradicional sin IVA, sin avisar a nadie.
    tarifa = producto.tarifa_iva
    subtotal = (total_linea / (1 + tarifa / 100)).quantize(Decimal("0.01"))
    return subtotal, total_linea - subtotal


# Medios que pueden combinarse en un pago mixto (VEN-04). El crédito queda
# afuera a propósito: una venta a medias fiada necesitaría una CxC parcial,
# abonos contra una parte, y un reembolso que no sabe de qué parte salió. Si
# el cliente fía una parte, se hace como dos ventas.
MEDIOS_MIXTOS = ("EFE", "TAR", "SIN")


def _validar_pagos(pagos, total):
    """Normaliza la lista de pagos mixtos y exige que sume el total exacto."""
    limpios = []
    for p in pagos:
        medio = p.get("medio")
        monto = Decimal(str(p.get("monto") or 0)).quantize(Decimal("0.01"))
        if medio not in MEDIOS_MIXTOS:
            raise ValidationError("En un pago mixto solo se combinan efectivo, tarjeta y SINPE.")
        if monto < 0:
            raise ValidationError("Un monto del pago mixto no puede ser negativo.")
        if monto > 0:
            limpios.append({"medio": medio, "monto": monto})
    suma = sum((p["monto"] for p in limpios), Decimal("0"))
    if suma != total:
        raise ValidationError(
            f"Los pagos suman ₡{suma:,.2f} y la venta es de ₡{total:,.2f}: tienen que coincidir."
        )
    return limpios


@transaction.atomic
def registrar_venta(*, sesion_caja, lineas, medio_pago, usuario, cliente=None,
                    permitir_bajo_costo=False, permitir_descuento_alto=False,
                    permitir_regalia_alta=False, pagos=None, clave_pos=None,
                    monto_recibido=None, cupon=None) -> FacturaVenta:
    """lineas: iterable de dicts {"producto_id": int, "cantidad": Decimal}.

    permitir_bajo_costo: por defecto NO se puede vender un producto por debajo
    de su costo promedio (protege el margen y cierra un hueco de fraude: un
    cajero descontando de más). El gerente sí puede autorizarlo (la vista lo
    pasa en True cuando quien vende es gerente).

    permitir_descuento_alto: por defecto un cajero no puede aplicar más de
    DESCUENTO_MAXIMO_SIN_AUTORIZACION por línea (SEC-001) — protege el margen
    en productos donde ese descuento no llega a bajar del costo, que es lo
    único que el freno anterior cubría. El gerente sí puede autorizarlo.

    permitir_regalia_alta: por defecto un cajero no puede marcar es_regalia
    en una línea cuyo valor de lista supere REGALIA_MAXIMA_SIN_AUTORIZACION
    (SEC-006). Toda regalía exige además un motivo (línea["motivo"]).

    pagos: solo con medio_pago="MIX", lista de {"medio", "monto"} que debe
    sumar el total (VEN-04).

    clave_pos: identificador único que el POS le pone a CADA venta. Si llega
    una que ya existe, se devuelve esa y no se crea otra (VEN-02: doble F1,
    reintento de la red).

    monto_recibido: efectivo que entregó el cliente; si viene, se guarda el
    vuelto (VEN-03).

    cupon: código de la manada (manada.Cupon), de un solo uso. Su porcentaje
    se aplica a cada línea que no sea regalía (si la línea ya traía un
    descuento mayor, queda el mayor: no se suman). El cupón se marca usado en
    ESTA transacción: si la venta falla, el cupón sigue disponible. El tope
    de descuento del cajero (SEC-001) no frena el porcentaje del cupón, que
    ya lo autorizó el negocio al definir la regalía; el piso de costo sí
    sigue mandando."""
    if clave_pos:
        ya_hecha = FacturaVenta.objects.filter(clave_pos=clave_pos).first()
        if ya_hecha is not None:
            ya_hecha.repetida = True  # la vista no vuelve a imprimir
            return ya_hecha
    # Releer la sesión desde la BD con bloqueo: el objeto en memoria puede
    # estar desactualizado (p. ej., la caja se cerró desde otra pantalla).
    sesion_caja = SesionCaja.objects.select_for_update().get(pk=sesion_caja.pk)
    if sesion_caja.estado != SesionCaja.Estado.ABIERTA:
        raise ValidationError("No hay una sesión de caja abierta.")
    if not lineas:
        raise ValidationError("La venta no tiene líneas.")
    if medio_pago not in FacturaVenta.MedioPago.values:
        raise ValidationError("Medio de pago inválido.")
    if medio_pago == FacturaVenta.MedioPago.CREDITO and cliente is None:
        raise ValidationError("Una venta a crédito requiere seleccionar un cliente.")

    sucursal = sesion_caja.sucursal
    empresa = sucursal.empresa
    # Bodega principal explícita (auditoría 2026-07-28, BE-09) en vez de "la
    # primera que aparezca". Ver inventario.models.Bodega.principal_de.
    bodega = Bodega.principal_de(sucursal)
    if bodega is None:
        raise ValidationError("La sucursal no tiene bodega configurada.")

    cupon_obj = None
    pct_cupon = Decimal("0")
    if cupon:
        from manada.services import cupon_para_venta
        # Con bloqueo de fila: dos cajas cobrando con el mismo cupón a la vez
        # → la segunda espera, lo encuentra usado y su venta no se registra.
        cupon_obj = cupon_para_venta(empresa, cupon, bloquear=True)
        pct_cupon = cupon_obj.porcentaje
        if cliente is None:
            # La compra queda a nombre de quien trae el cupón: así la base de
            # la manada sabe qué compró cada uno.
            cliente = cupon_obj.cliente

    numero = Consecutivo.tomar(empresa, "FV")
    # Segunda mirada, ya con el consecutivo bloqueado: si dos envíos del mismo
    # cobro llegaron a la vez, el primero ya confirmó y este lo encuentra. Se
    # deshace lo de esta transacción, así el número tomado vuelve a quedar libre.
    if clave_pos:
        ya_hecha = FacturaVenta.objects.filter(clave_pos=clave_pos).first()
        if ya_hecha is not None:
            transaction.set_rollback(True)
            ya_hecha.repetida = True
            return ya_hecha
    factura = FacturaVenta.objects.create(
        empresa=empresa, sucursal=sucursal, sesion_caja=sesion_caja,
        numero=numero, cliente=cliente, medio_pago=medio_pago, usuario=usuario,
        clave_pos=clave_pos or None,
    )

    # Orden estable de bloqueo: al recorrer las líneas se toma un lock de fila
    # sobre cada producto (en registrar_movimiento). Si dos cajas venden los
    # mismos productos en distinto orden, adquirir los locks siempre en el
    # mismo orden (por id de producto) evita interbloqueos (deadlock) en
    # PostgreSQL. El orden no afecta los totales (la suma es conmutativa).
    lineas = sorted(lineas, key=lambda l: l["producto_id"])

    subtotal = impuesto = total = descuento_total = Decimal("0")
    for linea in lineas:
        producto = Producto.objects.get(pk=linea["producto_id"], activo=True)
        cantidad = Decimal(str(linea["cantidad"]))
        if cantidad <= 0:
            raise ValidationError(f"Cantidad inválida para {producto.nombre}.")
        es_regalia = bool(linea.get("es_regalia", False))

        if es_regalia:
            # Regalía: se entrega gratis. No genera ingreso ni descuento; el
            # stock sale y su costo se registra como gasto de promoción.
            precio = Decimal("0")
            desc_l = Decimal("0")
            desc_pct = Decimal("0")
            total_linea = Decimal("0")
            sub_l = imp_l = Decimal("0")
            tipo_kardex = "REG"
            # Motivo obligatorio (SEC-006): sin esto, una regalía no deja
            # ningún rastro de por qué se entregó gratis (LineaVenta no está
            # auditada; el motivo es lo único que queda en el kardex).
            motivo_regalia = (linea.get("motivo") or "").strip()
            if not motivo_regalia:
                raise ValidationError(f"{producto.nombre}: toda regalía requiere un motivo.")
            # Techo de valor regalado sin autorización (SEC-006): a diferencia
            # del descuento, una regalía no tiene piso de costo propio — sin
            # este freno un cajero podía sacar mercadería de cualquier valor
            # sin cobrar nada y sin que nadie más lo autorizara.
            valor_regalado = (producto.precio_venta * cantidad).quantize(Decimal("0.01"))
            if not permitir_regalia_alta and valor_regalado > REGALIA_MAXIMA_SIN_AUTORIZACION:
                raise ValidationError(
                    f"{producto.nombre}: una regalía de ₡{valor_regalado:.2f} supera el tope de "
                    f"₡{REGALIA_MAXIMA_SIN_AUTORIZACION} que un cajero puede dar sin autorización. "
                    "Pedile a un gerente que registre la venta."
                )
        else:
            precio = producto.precio_venta
            bruto_linea = (precio * cantidad).quantize(Decimal("0.01"))
            desc_pct = Decimal(str(linea.get("descuento_pct", 0) or 0))
            if desc_pct < 0 or desc_pct > 100:
                raise ValidationError(f"Porcentaje de descuento inválido para {producto.nombre} (0-100).")
            # Precio final por unidad (13/10/2026, pedido de Oscar): "lo vendo
            # en ₡2.000" en vez de adivinar qué % da ₡2.000. El porcentaje sale
            # de ahí con decimales (14,89 %) para que el total cierre EXACTO en
            # lo que se le dijo al cliente; el cajero nunca lo teclea. Pasa por
            # las mismas reglas de abajo: tope del cajero y piso de costo.
            precio_final = linea.get("precio_final")
            desc_l = None
            if precio_final not in (None, ""):
                precio_final = Decimal(str(precio_final)).quantize(Decimal("0.01"))
                if precio_final < 0 or precio_final > precio:
                    raise ValidationError(
                        f"{producto.nombre}: el precio final debe estar entre ₡0 y su precio de ₡{precio:,.0f}."
                    )
                desc_l = bruto_linea - (precio_final * cantidad).quantize(Decimal("0.01"))
                desc_pct = (desc_l * 100 / bruto_linea).quantize(Decimal("0.01")) if bruto_linea else Decimal("0")
            if pct_cupon > desc_pct:
                # El cupón da más que lo negociado: gana el cupón (no se suman).
                desc_pct, desc_l = pct_cupon, None
            if desc_l is None:
                # A colón entero (13/10/2026): 13 % de ₡2.350 son ₡305,50 y el
                # total quedaba en ₡2.044,50 — nadie cobra ni da vuelto en
                # céntimos. Se redondea el descuento, no el precio.
                desc_l = (bruto_linea * desc_pct / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            total_linea = bruto_linea - desc_l
            sub_l, imp_l = _desglose_fiscal(empresa, producto, total_linea)
            # Bloqueo de venta bajo costo: lo que le queda al negocio por
            # unidad (ya con el descuento y SIN el IVA, que es de Hacienda)
            # no puede quedar por debajo del costo promedio. Antes se
            # comparaba el precio con IVA: en régimen tradicional dejaba pasar
            # ventas que perdían plata (20/09/2026).
            if not permitir_bajo_costo and producto.costo_promedio > 0:
                precio_efectivo = sub_l / cantidad
                if precio_efectivo < producto.costo_promedio:
                    por_cupon = " (por el cupón)" if pct_cupon and desc_pct == pct_cupon else ""
                    raise ValidationError(
                        f"{producto.nombre}: el precio con descuento{por_cupon}, sin IVA (₡{precio_efectivo:.2f}), "
                        f"queda por debajo del costo (₡{producto.costo_promedio}). "
                        "Un gerente debe autorizar la venta bajo costo."
                    )
            # Techo de descuento sin autorización (SEC-001): independiente del
            # piso de costo — un producto con margen amplio puede aceptar un
            # descuento grande sin bajar del costo, y aun así representar una
            # fuga de margen que un cajero no debería poder decidir solo.
            if (not permitir_descuento_alto and desc_pct > DESCUENTO_MAXIMO_SIN_AUTORIZACION
                    and desc_pct > pct_cupon):
                raise ValidationError(
                    f"{producto.nombre}: un descuento de {desc_pct}% supera el "
                    f"{DESCUENTO_MAXIMO_SIN_AUTORIZACION}% que un cajero puede aplicar sin "
                    "autorización. Pedile a un gerente que registre la venta."
                )
            tipo_kardex = "VEN"

        # Kardex primero: si no hay stock, ValidationError revienta TODA la venta.
        registrar_movimiento(
            producto=producto, bodega=bodega, tipo=tipo_kardex,
            cantidad=-cantidad, referencia=numero, usuario=usuario,
            motivo=f"Regalía: {motivo_regalia}" if es_regalia else "",
        )
        LineaVenta.objects.create(
            factura=factura, producto=producto, cantidad=cantidad,
            precio_unitario=precio, descuento_pct=desc_pct if not es_regalia else 0,
            descuento_monto=desc_l if not es_regalia else 0, es_regalia=es_regalia,
            costo_unitario=producto.costo_promedio, total=total_linea,
            # Foto fiscal de la línea (VEN-08). En simplificado no hay tarifa
            # que declarar: se deja vacía en vez de inventar un 0 %.
            tarifa_iva=(producto.tarifa_iva if empresa.regimen == Empresa.Regimen.TRADICIONAL else None),
            subtotal=sub_l, impuesto=imp_l, cabys=producto.cabys or "",
        )
        subtotal += sub_l; impuesto += imp_l; total += total_linea; descuento_total += desc_l

    factura.subtotal, factura.impuesto, factura.total = subtotal, impuesto, total
    factura.descuento = descuento_total

    # Cuánto de este cobro es efectivo que entra al cajón.
    if medio_pago == FacturaVenta.MedioPago.MIXTO:
        pagos = _validar_pagos(pagos or [], total)
        if len(pagos) < 2:
            raise ValidationError("Un pago mixto necesita al menos dos medios con monto.")
        for p in pagos:
            PagoVenta.objects.create(factura=factura, medio=p["medio"], monto=p["monto"])
        efectivo = sum((p["monto"] for p in pagos if p["medio"] == "EFE"), Decimal("0"))
    elif medio_pago == FacturaVenta.MedioPago.EFECTIVO:
        efectivo = total
    else:
        efectivo = Decimal("0")

    campos = ["subtotal", "descuento", "impuesto", "total"]
    if monto_recibido not in (None, "") and efectivo > 0:
        recibido = Decimal(str(monto_recibido)).quantize(Decimal("0.01"))
        if recibido < efectivo:
            raise ValidationError(
                f"El cliente entregó ₡{recibido:,.0f} y en efectivo son ₡{efectivo:,.0f}: falta plata."
            )
        factura.monto_recibido, factura.vuelto = recibido, recibido - efectivo
        campos += ["monto_recibido", "vuelto"]
    factura.save(update_fields=campos)

    if cupon_obj is not None:
        if descuento_total <= 0:
            # Todo regalía: el cupón no rebajó nada. Se rechaza en vez de
            # quemarlo en una venta donde el cliente no recibió el beneficio.
            raise ValidationError("El cupón no se puede usar en una venta sin productos cobrados.")
        from manada.services import marcar_usado
        marcar_usado(cupon_obj, factura)

    # Una venta 100% regalía tiene total 0: no mueve caja (evita el
    # movimiento de monto cero, que además es inválido).
    if efectivo > 0:
        registrar_movimiento_caja(
            sesion=sesion_caja, tipo=MovimientoCaja.Tipo.VENTA, monto=efectivo,
            descripcion=f"Venta {numero}", referencia=numero, usuario=usuario,
        )
    if medio_pago == FacturaVenta.MedioPago.CREDITO:
        # Genera la cuenta por cobrar y valida el límite (revienta la venta
        # completa si el crédito no alcanza). No mueve caja: no hay efectivo.
        if total > 0:
            from .cxc import crear_cxc
            crear_cxc(factura=factura)

    # Asiento automático (venta + costo), en la misma transacción: si el
    # asiento no cuadra, la venta entera se revierte. Nadie digita contabilidad.
    from .contabilizar import asentar_venta
    asentar_venta(factura, usuario=usuario)
    return factura


@transaction.atomic
def anular_factura(*, factura, motivo, usuario) -> FacturaVenta:
    """Anulación por movimientos inversos: el inventario regresa, el efectivo
    sale de caja. La factura original nunca se borra ni se edita."""
    factura = FacturaVenta.objects.select_for_update().get(pk=factura.pk)
    if factura.estado == FacturaVenta.Estado.ANULADA:
        raise ValidationError("La factura ya está anulada.")
    if not motivo or not motivo.strip():
        raise ValidationError("El motivo de anulación es obligatorio.")
    # Una venta con devoluciones ya NO se anula (auditoría 26/09/2026, VEN-01).
    # La anulación reversa las cantidades y el total ORIGINALES: sobre una
    # venta con una devolución parcial volvía a meter al inventario lo ya
    # devuelto y a sacar de caja otra vez lo ya reembolsado. Medido: venta de
    # ₡10.600, devolución de ₡5.300 y anulación = ₡15.900 fuera de caja y una
    # unidad fantasma. Lo que queda por devolver se devuelve con "Devolver".
    if factura.devoluciones.exists():
        raise ValidationError(
            "Esta venta ya tiene devoluciones, así que no se puede anular completa. "
            "Use «Devolver» para lo que falta devolver."
        )

    # Se reversa contra la MISMA bodega de la que salió (BE-09).
    bodega = Bodega.principal_de(factura.sucursal)
    for linea in factura.lineas.all():
        registrar_movimiento(
            producto=linea.producto, bodega=bodega, tipo="DEV",
            cantidad=linea.cantidad, costo_unitario=Decimal("0"),
            referencia=f"ANU-{factura.numero}", motivo=motivo, usuario=usuario,
        )
    # Sale del cajón lo que entró en efectivo: todo en una venta de contado,
    # solo la parte en efectivo en un pago mixto.
    efectivo = sum((m for medio, m in factura.desglose_pagos() if medio == "EFE"), Decimal("0"))
    if efectivo > 0:
        from caja.services import sesion_abierta_de
        sesion = sesion_abierta_de(usuario)
        if sesion is None:
            raise ValidationError(
                "Para anular una venta en efectivo debe tener una caja abierta "
                "(el dinero devuelto sale de esa caja)."
            )
        registrar_movimiento_caja(
            sesion=sesion, tipo=MovimientoCaja.Tipo.ANULACION, monto=-efectivo,
            descripcion=f"Anulación {factura.numero}: {motivo}", referencia=factura.numero, usuario=usuario,
        )
    elif factura.medio_pago == FacturaVenta.MedioPago.CREDITO:
        # Cancela la CxC y libera el crédito (bloquea si ya tiene abonos).
        from .cxc import cancelar_cxc_por_anulacion
        cancelar_cxc_por_anulacion(factura=factura, usuario=usuario)
    # El cupón de la manada vuelve a quedar disponible: una venta anulada no
    # fue la "primera compra" de nadie.
    from manada.services import liberar_por_anulacion
    liberar_por_anulacion(factura)

    factura.estado = FacturaVenta.Estado.ANULADA
    factura.motivo_anulacion = motivo.strip()
    factura.anulada_en = timezone.now()
    factura.anulada_por = usuario
    factura.save(update_fields=["estado", "motivo_anulacion", "anulada_en", "anulada_por"])

    # Asiento inverso de la venta y del costo.
    from .contabilizar import asentar_anulacion
    asentar_anulacion(factura, usuario=usuario)
    return factura
