"""Control antes de comprar (05/11/2026, encargo v3 de Oscar, fase 1).

Contexto: al mes de abierta, 598 de 751 productos con existencia nunca se
habían vendido (₡6,6 millones al costo). La pantalla de compras avisa —no
bloquea: la decisión es de quien compra— cuando se va a comprar más de algo
que no se mueve:

- Nunca se ha vendido y ya hubo existencia (lo nuevo, que nunca entró, no
  avisa: todo producto nuevo empieza sin ventas).
- Se vendió alguna vez, pero nada en los últimos 30 días.
- Ya hay más de 3 meses de inventario al ritmo de los últimos 30 días.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

MESES_MAXIMOS = Decimal("3")
DIAS = 30


def avisos(empresa, productos) -> dict:
    """{producto_id: texto} solo para los productos que merecen aviso.
    `productos` = instancias o dicts con id y stock_actual."""
    from inventario.models import MovimientoInventario
    from ventas.models import FacturaVenta, LineaVenta

    stock = {}
    for p in productos:
        pid = p["id"] if isinstance(p, dict) else p.pk
        stock[pid] = Decimal(str(p["stock_actual"] if isinstance(p, dict) else p.stock_actual))
    if not stock:
        return {}
    ids = list(stock)
    emitidas = LineaVenta.objects.filter(producto_id__in=ids, factura__empresa=empresa,
                                         factura__estado=FacturaVenta.Estado.EMITIDA)
    vendidos_alguna_vez = set(emitidas.values_list("producto_id", flat=True).distinct())
    desde = timezone.localdate() - timedelta(days=DIAS - 1)
    en_30 = dict(emitidas.filter(factura__creado_en__date__gte=desde)
                 .values_list("producto").annotate(u=Sum("cantidad")))
    con_historia = set(MovimientoInventario.objects.filter(producto_id__in=ids, cantidad__gt=0)
                       .values_list("producto_id", flat=True).distinct())
    def num(x):
        return f"{Decimal(x).normalize():f}".replace(".", ",")

    textos = {}
    for pid, hay in stock.items():
        hay_txt = num(hay)
        if pid not in vendidos_alguna_vez:
            if pid in con_historia:
                textos[pid] = f"Nunca se ha vendido (hay {hay_txt} en existencia)."
            continue
        mes = en_30.get(pid) or Decimal("0")
        if mes <= 0:
            textos[pid] = f"No se vende hace más de 30 días (hay {hay_txt})."
            continue
        meses = (hay / mes).quantize(Decimal("0.1"))
        if meses > MESES_MAXIMOS:
            textos[pid] = (f"Ya hay {num(meses)} meses de inventario: {hay_txt} en existencia "
                           f"y se venden {num(mes)} al mes.")
    return textos
