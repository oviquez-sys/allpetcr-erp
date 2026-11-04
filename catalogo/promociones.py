"""Promociones: precio de oferta, vigencia y reglas (04/11/2026, pedido de Oscar).

Un solo lugar sabe cuánto cuesta un producto HOY si está en oferta. Lo usan
la caja (`ventas.services.registrar_venta`, que lo aplica sola), el POS, la
API del sitio y los pedidos web: así el precio de la tienda y el de la web no
pueden ser distintos, que es lo que pide el MEIC.

El precio normal (`Producto.precio_venta`) nunca se toca. La oferta es:

    precio de oferta = precio normal × (100 − %) / 100, redondeado HACIA ABAJO
                       al precio bonito más cercano (catalogo/precios_bonitos)

y se vende como un DESCUENTO en la factura, que es como lo pide la factura
electrónica y como lo cuentan los reportes de descuentos.

Reglas, y por qué:
- Una promoción vigente por producto. Dos a la vez obligarían a decidir cuál
  gana a escondidas; mejor que el sistema no deje armarlo.
- Fecha de fin obligatoria (el modelo la exige). Una oferta sin vigencia es
  la falla más común que encontró el MEIC en los comercios.
- Bajo costo solo marcado a propósito por un gerente, producto por producto.
- Aviso si el precio normal subió en los últimos 30 días: el precio tachado
  tiene que ser el precio real de antes, no uno inflado para la ocasión.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import CambioPrecio, Producto, Promocion, PromocionProducto
from .precios_bonitos import bonito_hacia_abajo

CIEN = Decimal("100")
DIAS_PRECIO_SUBIDO = 30
DIAS_SIN_VENTAS = 60


def precio_oferta(precio_normal, pct) -> Decimal:
    """El precio con el descuento, redondeado hacia abajo a un precio bonito."""
    precio_normal = Decimal(precio_normal)
    exacto = precio_normal * (CIEN - Decimal(pct)) / CIEN
    oferta = bonito_hacia_abajo(exacto)
    return min(oferta, precio_normal)


def vigentes(empresa, fecha=None, productos=None) -> dict:
    """{producto_id: PromocionProducto} de lo que está en oferta en `fecha`
    (hoy por defecto). `productos` limita a esos ids (la caja solo necesita
    los de la venta)."""
    fecha = fecha or timezone.localdate()
    qs = (PromocionProducto.objects
          .filter(promocion__empresa=empresa, promocion__estado=Promocion.Estado.ACTIVA,
                  promocion__inicio__lte=fecha, promocion__fin__gte=fecha)
          .select_related("promocion"))
    if productos is not None:
        qs = qs.filter(producto_id__in=list(productos))
    # Si por un error de datos hubiera dos, gana la de mayor descuento; la
    # regla de "una a la vez" se cuida al activar (ver chocan_con).
    resultado = {}
    for item in qs:
        actual = resultado.get(item.producto_id)
        if actual is None or item.pct > actual.pct:
            resultado[item.producto_id] = item
    return resultado


def oferta_de(producto, item=None):
    """Lo que necesita mostrar quien vende o publica: precio de oferta, precio
    normal, % anunciado, nombre y hasta cuándo. None si no hay oferta."""
    if item is None:
        item = vigentes(producto.empresa, productos=[producto.pk]).get(producto.pk)
    if item is None or producto.precio_venta <= 0:
        return None
    precio = precio_oferta(producto.precio_venta, item.pct)
    if precio >= producto.precio_venta:
        return None
    return {"precio": precio, "precio_antes": producto.precio_venta, "pct": item.pct,
            "nombre": item.promocion.texto, "hasta": item.promocion.fin, "item": item}


def precio_vigente(producto) -> Decimal:
    """Lo que se le cobra hoy al cliente por una unidad (con la oferta si hay)."""
    o = oferta_de(producto)
    return o["precio"] if o else producto.precio_venta


# ---------------------------------------------------------------------------
# Para la pantalla de armar la promoción
# ---------------------------------------------------------------------------

def _sin_iva(producto, precio):
    if not producto.desglosa_iva:
        return Decimal(precio)
    return (Decimal(precio) / (1 + producto.tarifa_iva / 100)).quantize(Decimal("0.01"))


def max_pct_sin_perder(producto):
    """El mayor % entero que no deja el precio de oferta (sin IVA) bajo el
    costo. None si no hay costo cargado (no se puede saber)."""
    if producto.costo_promedio <= 0 or producto.precio_venta <= 0:
        return None
    for pct in range(90, 0, -1):
        if _sin_iva(producto, precio_oferta(producto.precio_venta, pct)) >= producto.costo_promedio:
            return pct
    return 0


def subio_precio(producto, dias=DIAS_PRECIO_SUBIDO):
    """El último aumento de precio de los últimos `dias`, o None."""
    desde = timezone.now() - timedelta(days=dias)
    return (CambioPrecio.objects.filter(producto=producto, fecha__gte=desde, valor_nuevo__gt=F("valor_anterior"))
            .order_by("-fecha").first())


def fila(item) -> dict:
    """Todo lo que la pantalla muestra de un producto de la promoción."""
    p = item.producto
    pct = item.pct
    oferta = precio_oferta(p.precio_venta, pct)
    sin_iva = _sin_iva(p, oferta)
    margen = ((sin_iva - p.costo_promedio) / sin_iva * CIEN).quantize(Decimal("1"), ROUND_FLOOR) \
        if sin_iva > 0 and p.costo_promedio > 0 else None
    bajo_costo = p.costo_promedio > 0 and sin_iva < p.costo_promedio
    real = ((p.precio_venta - oferta) / p.precio_venta * CIEN).quantize(Decimal("0.1")) if p.precio_venta else 0
    return {"item": item, "producto": p, "pct": pct, "pct_propio": item.descuento_pct is not None,
            "precio": p.precio_venta, "oferta": oferta, "ahorro": p.precio_venta - oferta, "pct_real": real,
            "margen": margen, "bajo_costo": bajo_costo, "max_pct": max_pct_sin_perder(p) if bajo_costo else None,
            "subio": subio_precio(p), "stock": p.stock_actual,
            "ganancia": ((sin_iva - p.costo_promedio) * p.stock_actual) if p.costo_promedio > 0 else None,
            "choca": chocan_con(item)}


def resumen(filas) -> dict:
    return {
        "productos": len(filas),
        "unidades": sum((f["stock"] for f in filas), Decimal("0")),
        "ventas": sum((f["oferta"] * f["stock"] for f in filas), Decimal("0")),
        "ganancia": sum((f["ganancia"] for f in filas if f["ganancia"] is not None), Decimal("0")),
        "bajo_costo": [f for f in filas if f["bajo_costo"] and not f["item"].permitir_bajo_costo],
        "chocan": [f for f in filas if f["choca"]],
    }


def chocan_con(item):
    """Otra promoción ACTIVA con este mismo producto y fechas que se cruzan."""
    promo = item.promocion
    return (PromocionProducto.objects
            .filter(producto_id=item.producto_id, promocion__estado=Promocion.Estado.ACTIVA,
                    promocion__inicio__lte=promo.fin, promocion__fin__gte=promo.inicio)
            .exclude(promocion=promo).select_related("promocion").first())


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def buscar_producto(empresa, codigo):
    """El producto de un escaneo: código de barras o SKU exacto."""
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    return (Producto.objects.filter(empresa=empresa, activo=True)
            .filter(Q(codigo_barras=codigo) | Q(sku__iexact=codigo)).first())


@transaction.atomic
def agregar(promocion, producto, usuario=None):
    """Agrega un producto (si ya estaba, lo devuelve sin duplicar)."""
    if promocion.estado == Promocion.Estado.TERMINADA:
        raise ValidationError("La promoción ya terminó.")
    if producto.empresa_id != promocion.empresa_id:
        raise ValidationError("Ese producto es de otra empresa.")
    if producto.precio_venta <= 0:
        raise ValidationError(f"{producto.nombre} no tiene precio.")
    item, creado = PromocionProducto.objects.get_or_create(
        promocion=promocion, producto=producto,
        defaults={"agregado_por": usuario if getattr(usuario, "pk", None) else None})
    if creado and promocion.estado == Promocion.Estado.ACTIVA:
        otra = chocan_con(item)
        if otra is not None:
            raise ValidationError(f"{producto.nombre} ya está en «{otra.promocion}» en esas fechas.")
    return item, creado


@transaction.atomic
def activar(promocion, usuario=None):
    """Pasa de borrador a activa (queda programada si empieza otro día)."""
    promocion = Promocion.objects.select_for_update().get(pk=promocion.pk)
    if promocion.estado == Promocion.Estado.TERMINADA:
        raise ValidationError("La promoción ya terminó.")
    if promocion.fin < timezone.localdate():
        raise ValidationError("La fecha de fin ya pasó.")
    items = list(promocion.items.select_related("producto"))
    if not items:
        raise ValidationError("La promoción no tiene productos.")
    for item in items:
        otra = chocan_con(item)
        if otra is not None:
            raise ValidationError(f"{item.producto.nombre} ya está en «{otra.promocion}» en esas fechas. "
                                  "Quitalo de una de las dos.")
        f = fila(item)
        if f["bajo_costo"] and not item.permitir_bajo_costo:
            raise ValidationError(f"{item.producto.nombre} queda por debajo del costo con {item.pct} %. "
                                  f"Bajalo a {f['max_pct']} % o marcá «vender bajo costo».")
    promocion.estado = Promocion.Estado.ACTIVA
    promocion.activada_en = timezone.now()
    promocion.save(update_fields=["estado", "activada_en"])
    return promocion


@transaction.atomic
def terminar(promocion, usuario=None):
    """Termina YA (antes de su fecha). Las ventas hechas quedan como fueron."""
    promocion = Promocion.objects.select_for_update().get(pk=promocion.pk)
    hoy = timezone.localdate()
    promocion.estado = Promocion.Estado.TERMINADA
    promocion.terminada_en = timezone.now()
    campos = ["estado", "terminada_en"]
    if promocion.fin >= hoy:
        # La fecha de fin pasa a ayer para que todo lo que mira fechas (web,
        # caja) la dé por terminada hoy mismo. Si empezaba hoy, empieza ayer:
        # el modelo exige fin ≥ inicio.
        promocion.fin = hoy - timedelta(days=1)
        promocion.inicio = min(promocion.inicio, promocion.fin)
        campos += ["fin", "inicio"]
    promocion.save(update_fields=campos)
    return promocion


def estado_visible(promocion, hoy=None) -> str:
    """Borrador · Programada · Vigente · Vencida · Terminada (para pantalla)."""
    hoy = hoy or timezone.localdate()
    if promocion.estado == Promocion.Estado.BORRADOR:
        return "Borrador"
    if promocion.estado == Promocion.Estado.TERMINADA:
        return "Terminada"
    if promocion.inicio > hoy:
        return "Programada"
    if promocion.fin < hoy:
        return "Vencida"
    return "Vigente"


def sugeridos(empresa, promocion=None, dias=DIAS_SIN_VENTAS, limite=40):
    """Productos con existencia y sin ventas en los últimos `dias`: los que
    más sentido tiene poner en oferta (sacar mercadería parada). Los más
    valiosos en bodega primero (existencia × costo)."""
    from inventario.models import MovimientoInventario

    desde = timezone.now() - timedelta(days=dias)
    vendidos = (MovimientoInventario.objects.filter(producto__empresa=empresa, tipo="VEN", fecha__gte=desde)
                .values_list("producto_id", flat=True).distinct())
    ya = vigentes(empresa).keys()
    qs = (Producto.objects.filter(empresa=empresa, activo=True, stock_actual__gt=0, precio_venta__gt=0)
          .exclude(pk__in=vendidos).exclude(pk__in=list(ya)))
    if promocion is not None:
        qs = qs.exclude(pk__in=promocion.items.values("producto_id"))
    # Más de `dias` desde que entró: un producto que llegó ayer no está
    # "parado", simplemente no le tocó venderse todavía.
    recientes = (MovimientoInventario.objects.filter(producto__empresa=empresa, cantidad__gt=0, fecha__gte=desde)
                 .exclude(tipo="VEN").values_list("producto_id", flat=True).distinct())
    qs = qs.exclude(pk__in=recientes)
    productos = sorted(qs.select_related("categoria"), key=lambda p: p.stock_actual * p.costo_promedio, reverse=True)
    return productos[:limite]


def resultados(promocion) -> dict:
    """Lo que vendió la promoción (ventas emitidas con líneas de esta promo)."""
    from ventas.models import FacturaVenta, LineaVenta

    lineas = LineaVenta.objects.filter(promocion=promocion, factura__estado=FacturaVenta.Estado.EMITIDA)
    r = lineas.aggregate(unidades=Sum("cantidad"), ventas=Sum("total"), descuento=Sum("descuento_monto"),
                         subtotal=Sum("subtotal"))
    costo = sum((l.costo_unitario * l.cantidad for l in lineas.only("costo_unitario", "cantidad")), Decimal("0"))
    sub = r["subtotal"] or Decimal("0")
    return {"unidades": r["unidades"] or Decimal("0"), "ventas": r["ventas"] or Decimal("0"),
            "descuento": r["descuento"] or Decimal("0"), "ganancia": sub - costo,
            "facturas": lineas.values("factura").distinct().count()}
