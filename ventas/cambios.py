"""Cambios y devoluciones desde la caja (24/11/2026).

POR QUÉ EXISTE
--------------
Caso real (Oscar, 24/11/2026): una clienta cambió una pechera XL comprada el
viernes por SINPE por una XXL y pagó la diferencia por SINPE. No se pudo
registrar: el sistema solo sabía «devolver la plata» (pantalla aparte, solo
gerente, buscar la venta por fecha) y «vender» (por el total). La XL no
volvió al inventario, la XXL no salió y la diferencia quedó como sobrante en
el cierre.

CÓMO FUNCIONA
-------------
Todo en la pantalla de Vender, en una sola operación:

1. «↩ Cambio / devolución» → se escanea lo que trae el cliente (o el número
   del tiquete, o su WhatsApp / cédula). `buscar` devuelve las ventas de los
   últimos `VENTANA_DIAS` que lo tienen, con lo que queda por devolver.
2. Lo elegido entra a la venta en negativo, al precio que PAGÓ
   (`devoluciones.precio_pagado`).
3. Se escanea lo que se lleva, como cualquier venta. El total es la
   diferencia.
4. `registrar_cambio` hace, en UNA transacción: la venta nueva pagada con el
   valor devuelto (medio CAM) + la diferencia por el medio que se elija, y la
   devolución ligada a la venta original con lo que pagó el cambio
   (`aplicar_a_cambio`). Si lo nuevo vale menos, el resto se le devuelve por
   el medio con que pagó la compra original. Sin productos nuevos es una
   devolución simple.

Caja y banco solo ven lo que de verdad entró o salió: en el caso de la
pechera, la diferencia por SINPE. La contabilidad cuadra sola (la cuenta
«Cambios por aplicar» se llena y se vacía en la misma operación).

REGLAS DE NEGOCIO (Oscar, 24/11/2026)
-------------------------------------
- Lo hace cualquiera (cajero o gerente) dentro del plazo de
  `devoluciones.PLAZO_CAMBIOS_DIAS` (15) días; pasado el plazo, solo el
  gerente. Control: el cierre de caja (pantalla, tiquete y correo) lista
  cada devolución con quién la hizo y cuánta plata salió.
- Si sobra, se devuelve el dinero por el mismo medio con que pagó.
- Un cambio no da números del sorteo (no es una compra nueva).
- Lo que se devuelve es de UNA sola venta por operación (el tiquete de la
  devolución dice de cuál). Dos ventas = dos operaciones.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from catalogo.models import Producto
from core.imagenes import datos_foto

from .devoluciones import PLAZO_CAMBIOS_DIAS, _cantidad_ya_devuelta, dias_desde, precio_pagado, registrar_devolucion, \
    valor_a_favor
from .models import DevolucionVenta, FacturaVenta

# Hasta dónde busca la caja. Más que el plazo a propósito: el gerente puede
# aceptar una compra vieja, y el cajero tiene que VER que está fuera de plazo
# en vez de recibir «no encontré la venta».
VENTA_DIAS = 90
MAX_VENTAS = 12


def _numero_tiquete(texto):
    t = texto.upper().replace(" ", "")
    if t.startswith("FV"):
        t = t[2:].lstrip("-")
    return f"FV-{int(t):08d}" if t.isdigit() and len(t) <= 8 else ""


def _como_pago(factura) -> str:
    """«SINPE Móvil», o «Efectivo + SINPE Móvil» en un pago mixto: «Pago
    mixto» no le dice al cajero por dónde devolver."""
    if factura.medio_pago != FacturaVenta.MedioPago.MIXTO:
        return factura.get_medio_pago_display()
    nombres = dict(FacturaVenta.MedioPago.choices)
    return " + ".join(nombres.get(m, m) for m, _ in factura.desglose_pagos())


def _lo_que_debe(factura) -> float:
    """Lo pendiente de una venta fiada: la caja lo resta de lo que el
    cliente tiene a favor (`devoluciones.valor_a_favor`)."""
    if factura.medio_pago != FacturaVenta.MedioPago.CREDITO:
        return 0
    from .models import DocumentoCxC
    doc = DocumentoCxC.objects.filter(factura=factura).first()
    return float(doc.saldo) if doc else 0


def buscar(empresa, texto):
    """(ventas, cómo se buscó). Cada venta: lo que la caja necesita para
    elegir qué vuelve, con lo que queda por devolver de cada línea."""
    from catalogo.palabras_clave import filtrar
    from manada.identificar import identificar_texto

    texto = (texto or "").strip()[:80]
    if not texto:
        return [], ""
    desde = timezone.now() - timedelta(days=VENTA_DIAS)
    ventas = (FacturaVenta.objects.filter(empresa=empresa, estado=FacturaVenta.Estado.EMITIDA, creado_en__gte=desde)
              .select_related("cliente").order_by("-id"))
    productos = None
    como = ""
    # 1) Lo escaneado: un código de barras de 13 dígitos también parece una
    # cédula, así que el producto exacto va primero.
    exacto = list(Producto.objects.filter(empresa=empresa).filter(sku__iexact=texto)) or \
        list(Producto.objects.filter(empresa=empresa, codigo_barras=texto))
    if exacto:
        productos, como = exacto, "producto"
    elif _numero_tiquete(texto) and (texto.upper().startswith("FV") or len(texto) < 8):
        ventas, como = ventas.filter(numero=_numero_tiquete(texto)), "tiquete"
    else:
        cliente = identificar_texto(empresa, texto).cliente if any(c.isdigit() for c in texto) or "@" in texto else None
        if cliente is not None:
            ventas, como = ventas.filter(cliente=cliente), "cliente"
        else:
            vendidos = Producto.objects.filter(empresa=empresa, lineaventa__factura__in=ventas).distinct()
            productos, como = filtrar(vendidos, texto, limite=30), "producto"
    if productos is not None:
        ids = [p.pk for p in productos]
        if not ids:
            return [], como
        ventas = ventas.filter(lineas__producto_id__in=ids).distinct()
    salida = []
    for f in ventas[:MAX_VENTAS]:
        lineas = []
        for l in f.lineas.select_related("producto").order_by("id"):
            disponible = l.cantidad - _cantidad_ya_devuelta(l)
            if disponible <= 0:
                continue
            p = l.producto
            lineas.append({
                "id": l.pk, "producto_id": p.pk, "nombre": p.nombre, "sku": p.sku,
                "cantidad": int(l.cantidad) if l.cantidad == l.cantidad.to_integral_value() else float(l.cantidad),
                "disponible": int(disponible) if disponible == disponible.to_integral_value() else float(disponible),
                "precio": float(precio_pagado(l)), "regalia": l.es_regalia,
                "buscado": productos is None or p.pk in ids, **datos_foto(p),
            })
        if not lineas:
            continue
        dias = dias_desde(f)
        salida.append({
            "id": f.pk, "numero": f.numero, "fecha": timezone.localtime(f.creado_en).strftime("%d/%m/%Y %I:%M %p"),
            "dias": dias, "fuera_de_plazo": dias > PLAZO_CAMBIOS_DIAS,
            "cliente": str(f.cliente) if f.cliente_id else "", "cliente_id": f.cliente_id,
            "medio": _como_pago(f), "medio_codigo": f.medio_pago, "total": float(f.total),
            "debe": _lo_que_debe(f),
            "lineas": lineas,
        })
    return salida, como


@transaction.atomic
def registrar_cambio(*, sesion_caja, factura_original, devolver, tipo_motivo, motivo="", lineas_nuevas=None,
                     medio_pago="", usuario, es_gerente=False, cliente=None, **venta):
    """(devolución, venta nueva o None). `devolver`: [{linea_venta_id,
    cantidad}] de `factura_original`. `**venta`: lo demás de
    `services.registrar_venta` (pagos, monto recibido, descuentos…)."""
    from .services import registrar_venta

    if factura_original.empresa_id != sesion_caja.sucursal.empresa_id:
        raise ValidationError("Esa venta es de otra empresa.")
    if not es_gerente and dias_desde(factura_original) > PLAZO_CAMBIOS_DIAS:
        raise ValidationError(
            f"Esa compra es de hace {dias_desde(factura_original)} días y el plazo para cambios y devoluciones "
            f"es de {PLAZO_CAMBIOS_DIAS}. Solo el gerente puede hacerla.")
    if tipo_motivo == DevolucionVenta.TipoMotivo.OTRO and not (motivo or "").strip():
        raise ValidationError("Con «Otro», escribí el motivo de la devolución.")
    nueva = None
    usado = Decimal("0")
    if lineas_nuevas:
        a_favor = valor_a_favor(factura_original, devolver)
        if cliente is None and factura_original.cliente_id:
            cliente = factura_original.cliente   # el cambio sigue siendo de la misma persona
        if cliente is None and not venta.get("sin_cliente"):
            venta["sin_cliente"] = factura_original.sin_cliente or FacturaVenta.SinCliente.NO_QUISO
        nueva = registrar_venta(sesion_caja=sesion_caja, lineas=lineas_nuevas, medio_pago=medio_pago,
                                usuario=usuario, cliente=cliente, credito_cambio=a_favor, **venta)
        if getattr(nueva, "repetida", False):
            # El mismo cobro llegó dos veces (red, doble toque): la devolución
            # ya quedó con la primera.
            return nueva.devoluciones_aplicadas.first(), nueva
        usado = nueva.credito_cambio_usado
    dev = registrar_devolucion(factura=factura_original, lineas=devolver, motivo=motivo, usuario=usuario,
                               tipo_motivo=tipo_motivo, aplicar_a_cambio=usado, venta_cambio=nueva,
                               permitir_fuera_de_plazo=es_gerente, sesion_caja=sesion_caja)
    return dev, nueva
