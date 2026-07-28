"""Datos de los reportes operativos (centro de reportes).

Son consultas de SOLO LECTURA sobre los datos reales. La lógica vive acá,
separada de las vistas, igual que dashboard.py. Cada función responde una
pregunta de negocio concreta:

- mas_vendidos:  ¿qué se vende? (para reponer y para negociar con proveedores)
- niveles_stock: ¿qué tengo que reordenar YA? (reposición)
- valor_inventario: ¿cuánto capital tengo dormido en bodega? (a costo)
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum, F, DecimalField
from django.utils import timezone


def _rango_por_defecto():
    """Mes en curso: del día 1 a hoy."""
    hoy = timezone.localdate()
    return hoy.replace(day=1), hoy


def mas_vendidos(empresa, desde=None, hasta=None, limite=50):
    """Ranking de productos por unidades vendidas en el rango, con el ingreso
    neto que generaron. Solo facturas emitidas (no anuladas). Excluye regalías
    del ingreso pero cuenta sus unidades entregadas."""
    from ventas.models import LineaVenta

    if desde is None or hasta is None:
        desde, hasta = _rango_por_defecto()

    lineas = LineaVenta.objects.filter(
        factura__empresa=empresa,
        factura__estado="EMI",
        factura__creado_en__date__gte=desde,
        factura__creado_en__date__lte=hasta,
    )
    filas = (
        lineas.values("producto__nombre", "producto__sku", "producto_id")
        .annotate(
            unidades=Sum("cantidad"),
            ingreso=Sum("total"),
        )
        .order_by("-unidades")[:limite]
    )
    total_unidades = sum((f["unidades"] or Decimal("0")) for f in filas)
    total_ingreso = sum((f["ingreso"] or Decimal("0")) for f in filas)
    return {
        "filas": list(filas),
        "desde": desde,
        "hasta": hasta,
        "total_unidades": total_unidades,
        "total_ingreso": total_ingreso,
    }


def niveles_stock(empresa, solo_bajo=False):
    """Existencias actuales contra el mínimo. Si solo_bajo, devuelve únicamente
    los que están en o por debajo del mínimo (los que hay que reponer)."""
    from catalogo.models import Producto

    productos = (
        Producto.objects.filter(empresa=empresa, activo=True)
        .select_related("categoria")
        .order_by("nombre")
    )
    filas = []
    for p in productos:
        bajo = p.stock_actual <= p.stock_minimo
        if solo_bajo and not bajo:
            continue
        filas.append(p)
    # Los bajo mínimo primero, luego por nombre.
    filas.sort(key=lambda p: (not (p.stock_actual <= p.stock_minimo), p.nombre.lower()))
    num_bajo = sum(1 for p in productos if p.stock_actual <= p.stock_minimo)
    return {
        "productos": filas,
        "num_total": productos.count(),
        "num_bajo": num_bajo,
    }


def valor_inventario(empresa):
    """Capital inmovilizado en bodega, valuado a costo promedio, agrupado por
    categoría. La fuente de verdad del stock es el kardex; acá se lee el
    denormalizado stock_actual, que reconciliar mantiene cuadrado."""
    from catalogo.models import Producto

    productos = Producto.objects.filter(empresa=empresa, activo=True).select_related("categoria")

    grupos = {}
    total_valor = Decimal("0")
    total_unidades = Decimal("0")
    for p in productos:
        valor = (p.stock_actual or Decimal("0")) * (p.costo_promedio or Decimal("0"))
        total_valor += valor
        total_unidades += p.stock_actual or Decimal("0")
        cat = p.categoria.nombre if p.categoria else "Sin categoría"
        g = grupos.setdefault(cat, {"categoria": cat, "valor": Decimal("0"), "unidades": Decimal("0"), "items": 0})
        g["valor"] += valor
        g["unidades"] += p.stock_actual or Decimal("0")
        g["items"] += 1

    filas = sorted(grupos.values(), key=lambda g: g["valor"], reverse=True)
    return {
        "filas": filas,
        "total_valor": total_valor,
        "total_unidades": total_unidades,
        "num_productos": productos.count(),
    }
