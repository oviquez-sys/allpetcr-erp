"""Qué se vendió en un rango de fechas, para reponerlo.

Pedido de Oscar (20/10/2026): "encuentro que se agotó y que quedan pocas
unidades, pero no sé qué se vendió para reponer… ojalá con un rango de
fechas". Los otros reportes no responden eso directo: "Qué reponer" usa una
ventana fija de 60 días y un cálculo de velocidad, "Más vendidos" no dice
cuánto queda ni a quién se le compra, y "Agotados" solo muestra lo que llegó
a cero.

Cada fila: un producto que salió en el rango, cuántas unidades salieron,
cuántas quedan HOY, a quién se le compró la última vez y con qué código se le
pide. Primero lo agotado, después lo que quedó con pocas, después el resto.

- Cuenta facturas EMITIDAS (las anuladas no). Las regalías cuentan, porque
  también vacían el estante. Lo que se devolvió de esas mismas ventas se
  resta: volvió al estante y no hay que reponerlo.
- "Pocas" = existencia en o bajo el mínimo del producto (el mismo criterio
  de "Stock contra el mínimo").
- Desde el 26/11/2026 la pantalla es `inventario:reponer`, que junta esto
  con «Agotados» y «Qué reponer». Aquí quedan las fechas, el conteo neto y
  la consulta de la herramienta `lo_vendido` del chat.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone


# Más de un año de una vez no sirve para reponer y pone lenta la pantalla.
MAX_DIAS = 366

ATAJOS = [
    ("hoy", "Hoy"),
    ("ayer", "Ayer"),
    ("semana", "Esta semana"),
    ("semana_pasada", "Semana pasada"),
    ("7", "Últimos 7 días"),
    ("15", "Últimos 15 días"),
    ("30", "Últimos 30 días"),
    ("mes", "Este mes"),
    ("mes_pasado", "Mes pasado"),
]

AGOTADO, POCAS, HAY = "agotado", "pocas", "hay"


def rango_de_atajo(clave, hoy=None):
    hoy = hoy or timezone.localdate()
    if clave == "hoy":
        return hoy, hoy
    if clave == "ayer":
        ayer = hoy - timedelta(days=1)
        return ayer, ayer
    if clave == "semana":                  # de lunes a hoy
        return hoy - timedelta(days=hoy.weekday()), hoy
    if clave == "semana_pasada":           # de lunes a domingo
        lunes = hoy - timedelta(days=hoy.weekday() + 7)
        return lunes, lunes + timedelta(days=6)
    if clave == "mes":
        return hoy.replace(day=1), hoy
    if clave == "mes_pasado":
        fin = hoy.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin
    if clave in ("7", "15", "30"):
        return hoy - timedelta(days=int(clave) - 1), hoy
    return None


def normalizar(desde, hasta, hoy=None):
    """Rango válido: en orden, sin futuro y de máximo MAX_DIAS."""
    hoy = hoy or timezone.localdate()
    hasta = min(hasta or hoy, hoy)
    desde = desde or hasta - timedelta(days=6)
    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days + 1 > MAX_DIAS:
        desde = hasta - timedelta(days=MAX_DIAS - 1)
    return desde, hasta


def vendidas_netas(empresa, desde, hasta):
    """{producto_id: unidades} que salieron del {desde} al {hasta}, ambos
    incluidos, menos lo que se devolvió de esas mismas ventas. Solo los que
    quedan en más de cero."""
    from ventas.models import LineaDevolucion, LineaVenta

    lineas = LineaVenta.objects.filter(
        factura__empresa=empresa,
        factura__estado="EMI",
        factura__creado_en__date__gte=desde,
        factura__creado_en__date__lte=hasta,
    )
    salieron = {
        f["producto_id"]: f["u"] or Decimal("0")
        for f in lineas.values("producto_id").annotate(u=Sum("cantidad"))
    }
    devueltas = {
        f["linea_venta__producto_id"]: f["u"] or Decimal("0")
        for f in LineaDevolucion.objects.filter(linea_venta__in=lineas)
        .values("linea_venta__producto_id").annotate(u=Sum("cantidad"))
    }
    netas = {pid: u - devueltas.get(pid, Decimal("0")) for pid, u in salieron.items()}
    return {pid: u for pid, u in netas.items() if u > 0}


def filas(empresa, desde, hasta, proveedor=""):
    """Lo que usa la herramienta `lo_vendido` del chat: las mismas filas de la
    pestaña «Todo lo vendido» de `inventario:reponer`, para que el chat y la
    pantalla digan lo mismo."""
    from .reponer import datos

    return datos(empresa, desde, hasta, ver="vendido", proveedor=proveedor)["filas"]


def resumen(lista):
    return {
        "productos": len(lista),
        "unidades": sum((f["vendidas"] for f in lista), Decimal("0")),
        "agotados": sum(1 for f in lista if f["estado"] == AGOTADO),
        "pocas": sum(1 for f in lista if f["estado"] == POCAS),
    }
