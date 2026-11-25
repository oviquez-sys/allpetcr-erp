"""Costo de reposición: con qué costo se deciden precios y descuentos (25/11/2026).

POR QUÉ EXISTE
--------------
Caso real (Oscar, 25/11/2026): en la compra del 26/09 el proveedor regaló un
saco de NutriSource Cat-Kitten 12 lb (pagado 1, entraron 2). El costo
promedio quedó a la mitad —lo correcto para la contabilidad: es lo que de
verdad costó ese inventario—, pero el descuento máximo del POS (la cifra gris,
`ventas.views._filas_pos`) salió de ese costo: decía 54 % cuando el margen
contra lo que cuesta volver a comprar el saco ronda el 8 %. En caja se dio un
descuento grande creyendo que sobraba margen.

LA REGLA (decisión de Oscar, 25/11/2026)
----------------------------------------
- `costo_promedio` sigue siendo EL costo contable (kardex, asientos, costo de
  ventas, ganancia del mes). No se toca.
- Para DECIDIR precio y descuento se usa `costo_para_decidir`: el MAYOR entre
  el promedio y el costo de reposición. El regalo del proveedor es una vez;
  el próximo saco se paga completo. Y si el proveedor bajó el precio, el
  promedio (lo que costó lo que hay en bodega) sigue mandando.
- Costo de reposición = lo que costó UNA unidad FACTURADA en la última
  compra recibida: (total de la línea − su parte del descuento de la
  factura) ÷ unidades facturadas. Sin repartir las bonificadas. Una línea
  solo de regalo no cuenta; se mira la compra anterior. Sin compras con
  unidades pagadas, no hay reposición y manda el promedio.
- Unidad suelta de una caja abierta (`Producto.unidad_suelta`): la
  reposición de la caja ÷ unidades por empaque, si no tiene compras propias.

Dónde se usa: tope de descuento del POS, piso de «no vender bajo costo» en
caja (solo cuando la línea lleva descuento, redondeo o cupón: el precio de
lista lo decide el gerente), máximo sin perder de las promociones, margen de
la carga desde Excel, y la lista `inventario:costos_regalias`.
"""
from decimal import ROUND_FLOOR, Decimal

CENTIMO = Decimal("0.01")


def _unitario(linea) -> Decimal:
    return ((linea.total - linea.descuento) / linea.cantidad).quantize(CENTIMO)


def ultimas_lineas_pagadas(producto_ids):
    """{producto_id: LineaCompra} con la última compra recibida que traía
    unidades pagadas de cada producto."""
    from compras.models import Compra, LineaCompra

    salida = {}
    lineas = (LineaCompra.objects.filter(producto_id__in=list(producto_ids), cantidad__gt=0,
                                         compra__estado=Compra.Estado.RECIBIDA)
              .select_related("compra", "compra__proveedor")
              .order_by("producto_id", "-compra__recibida_en", "-compra_id", "-id"))
    for l in lineas:
        salida.setdefault(l.producto_id, l)
    return salida


def reposiciones(productos) -> dict:
    """{producto_id: Decimal o None} para una lista de productos (dos consultas)."""
    from .models import Producto

    productos = list(productos)
    salida = {pid: _unitario(l) for pid, l in ultimas_lineas_pagadas([p.pk for p in productos]).items()}
    # Unidades sueltas sin compras propias: la caja que las trae.
    sin = [p.pk for p in productos if p.pk not in salida]
    if sin:
        cajas = {}
        for caja in Producto.objects.filter(empresa_id=productos[0].empresa_id, unidad_suelta_id__in=sin,
                                            unidades_por_empaque__gt=0).order_by("id"):
            cajas.setdefault(caja.unidad_suelta_id, caja)
        ultimas_cajas = ultimas_lineas_pagadas([c.pk for c in cajas.values()])
        for unidad_id, caja in cajas.items():
            l = ultimas_cajas.get(caja.pk)
            if l is not None:
                salida[unidad_id] = (_unitario(l) / caja.unidades_por_empaque).quantize(CENTIMO)
    return {p.pk: salida.get(p.pk) for p in productos}


def costo_reposicion(producto):
    return reposiciones([producto])[producto.pk]


def costo_para_decidir(producto, reposicion=None) -> Decimal:
    """El mayor entre el costo promedio y el de reposición. Pasar
    `reposicion` evita la consulta cuando ya se tiene (listas)."""
    if reposicion is None:
        reposicion = costo_reposicion(producto)
    return max(producto.costo_promedio or Decimal("0"), reposicion or Decimal("0"))


def margen(producto, costo):
    """Margen % sobre el precio sin IVA con ese costo (misma fórmula que
    `Producto.margen_pct`). None sin precio."""
    base = producto.precio_sin_iva
    if not base:
        return None
    return round((base - costo) / base * Decimal("100"), 2)


def tope(producto, costo):
    """Descuento máximo entero sin vender bajo ese costo (hacia abajo)."""
    m = margen(producto, costo)
    return max(0, int((m).to_integral_value(rounding=ROUND_FLOOR))) if m is not None else None


# Diferencia mínima para que la revisión muestre un producto: menos de esto es
# ruido de redondeo o un cambio chico de precio del proveedor.
DIFERENCIA_MINIMA_PCT = Decimal("3")


def revision(empresa):
    """La lista de `inventario:costos_regalias`: dos grupos de productos
    activos.

    - `rebajados`: el costo promedio está al menos DIFERENCIA_MINIMA_PCT %
      por debajo del de reposición (casi siempre, un regalo del proveedor).
      Con el tope que el POS mostraba antes y el que muestra ahora, y la
      última compra que trajo unidades de regalo.
    - `perdiendo`: el precio de lista, sin IVA, no alcanza para reponerlo.
      Esos se venden perdiendo aunque no les den descuento.
    """
    from compras.models import Compra, LineaCompra

    from .models import Producto

    productos = list(Producto.objects.filter(empresa=empresa, activo=True, precio_venta__gt=0)
                     .select_related("empresa", "impuesto", "categoria"))
    repos = reposiciones(productos)
    regalos = {}
    for l in (LineaCompra.objects.filter(producto__in=productos, cantidad_bonificada__gt=0,
                                         compra__estado=Compra.Estado.RECIBIDA)
              .select_related("compra", "compra__proveedor").order_by("producto_id", "-compra__recibida_en", "-id")):
        regalos.setdefault(l.producto_id, l)
    rebajados, perdiendo = [], []
    for p in productos:
        rep = repos[p.pk]
        if not rep:
            continue
        decidir = costo_para_decidir(p, rep)
        fila = {"producto": p, "promedio": p.costo_promedio, "reposicion": rep, "regalo": regalos.get(p.pk),
                "tope_antes": tope(p, p.costo_promedio), "tope_ahora": tope(p, decidir),
                "margen": margen(p, decidir)}
        if p.costo_promedio > 0 and rep > p.costo_promedio * (1 + DIFERENCIA_MINIMA_PCT / 100):
            rebajados.append(fila)
        if fila["margen"] is not None and fila["margen"] < 0:
            perdiendo.append(fila)
    rebajados.sort(key=lambda f: (f["tope_antes"] or 0) - (f["tope_ahora"] or 0), reverse=True)
    perdiendo.sort(key=lambda f: f["margen"])
    return {"rebajados": rebajados, "perdiendo": perdiendo}
