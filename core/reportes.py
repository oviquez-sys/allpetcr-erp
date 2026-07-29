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

from django.db.models import (
    BooleanField,
    Case,
    Count,
    DecimalField,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Lower
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

    # Auditoría 2026-07-28 (BE-06): antes esto traía TODOS los productos a
    # memoria, los recorría en Python para filtrar y ordenar, y remataba con
    # un .count() que disparaba otra consulta. Con 184 productos da igual; con
    # 5 000 SKU se carga la tabla entera en cada reporte. El patrón correcto
    # ya estaba en dashboard.py — acá se aplica el mismo criterio.
    productos = (
        Producto.objects.filter(empresa=empresa, activo=True)
        .select_related("categoria")
        # `bajo` lo calcula la base, no Python: así se puede filtrar y ordenar
        # por ese valor sin traerse las filas.
        .annotate(bajo=Case(
            When(stock_actual__lte=F("stock_minimo"), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ))
    )
    # Un solo recorrido de la base para los dos conteos, en vez de dos
    # consultas más (num_total y num_bajo).
    conteos = productos.aggregate(
        num_total=Count("id"),
        num_bajo=Count("id", filter=Q(stock_actual__lte=F("stock_minimo"))),
    )
    filas = productos
    if solo_bajo:
        filas = filas.filter(stock_actual__lte=F("stock_minimo"))
    # Los bajo mínimo primero, luego por nombre — mismo orden que antes.
    filas = filas.order_by("-bajo", Lower("nombre"))
    return {
        "productos": filas,
        "num_total": conteos["num_total"],
        "num_bajo": conteos["num_bajo"],
    }


def valor_inventario(empresa):
    """Capital inmovilizado en bodega, valuado a costo promedio, agrupado por
    categoría. La fuente de verdad del stock es el kardex; acá se lee el
    denormalizado stock_actual, que reconciliar mantiene cuadrado."""
    from catalogo.models import Producto

    # Auditoría 2026-07-28 (BE-06): el agrupado por categoría lo hace la base
    # con values()+annotate(), no un diccionario de Python alimentado fila a
    # fila. Mismo resultado, sin traerse el catálogo completo a memoria.
    productos = Producto.objects.filter(empresa=empresa, activo=True)

    valor_linea = Coalesce(F("stock_actual"), Value(Decimal("0"))) * Coalesce(
        F("costo_promedio"), Value(Decimal("0"))
    )
    filas = list(
        productos.values("categoria__nombre")
        .annotate(
            valor=Sum(valor_linea, output_field=DecimalField(max_digits=18, decimal_places=4)),
            unidades=Sum(Coalesce(F("stock_actual"), Value(Decimal("0")))),
            items=Count("id"),
        )
        .order_by("-valor")
    )
    # La plantilla espera la clave "categoria"; los productos sin categoría
    # llegan con None y se muestran igual que antes.
    for f in filas:
        f["categoria"] = f.pop("categoria__nombre") or "Sin categoría"
        f["valor"] = f["valor"] or Decimal("0")
        f["unidades"] = f["unidades"] or Decimal("0")

    totales = productos.aggregate(
        total_valor=Sum(valor_linea, output_field=DecimalField(max_digits=18, decimal_places=4)),
        total_unidades=Sum(Coalesce(F("stock_actual"), Value(Decimal("0")))),
        num_productos=Count("id"),
    )
    return {
        "filas": filas,
        "total_valor": totales["total_valor"] or Decimal("0"),
        "total_unidades": totales["total_unidades"] or Decimal("0"),
        "num_productos": totales["num_productos"],
    }
