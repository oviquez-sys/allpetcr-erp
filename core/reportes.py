"""Datos de los reportes operativos (centro de reportes).

Son consultas de SOLO LECTURA sobre los datos reales. La lógica vive acá,
separada de las vistas, igual que dashboard.py. Cada función responde una
pregunta de negocio concreta:

- mas_vendidos:  ¿qué se vende? (para reponer y para negociar con proveedores)
- niveles_stock: ¿qué tengo que reordenar YA? (reposición)
- valor_inventario: ¿cuánto capital tengo dormido en bodega? (a costo)
- resumen_diario: ¿qué pasó ayer que un socio debería ver, aunque no entre
  a revisar? (FRA-004, auditoría 2026-08-15)
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


# Documentos financieros cuya edición/borrado interesa reportar (FRA-004):
# los mismos que la familia FRA-001/002/003 señala como editables sin rastro
# si se hace por QuerySet.update()/SQL directo — acá se muestra lo que SÍ
# quedó en AuditLog (edición/borrado por el ORM normal).
_TABLAS_FINANCIERAS = (
    "ventas.facturaventa",
    "ventas.devolucionventa",
    "compras.compra",
    "contabilidad.asiento",
    "caja.sesioncaja",
)


def resumen_diario(empresa, fecha):
    """Resumen de un día para el reporte automático a los socios (FRA-004).

    No inventa datos nuevos: junta lo que ya registran ventas, caja y
    AuditLog. Devuelve un dict con 5 secciones, pensado para pasar directo
    a una plantilla de correo."""
    from ventas.models import FacturaVenta, LineaVenta
    from ventas.services import DESCUENTO_MAXIMO_SIN_AUTORIZACION, REGALIA_MAXIMA_SIN_AUTORIZACION
    from caja.models import SesionCaja
    from core.models import AuditLog

    facturas = FacturaVenta.objects.filter(
        empresa=empresa, estado=FacturaVenta.Estado.EMITIDA, creado_en__date=fecha,
    )
    ventas_por_medio = list(
        facturas.values("medio_pago").annotate(total=Sum("total"), cantidad=Count("id")).order_by("-total")
    )
    _medios = dict(FacturaVenta.MedioPago.choices)
    for m in ventas_por_medio:
        m["medio_pago"] = _medios.get(m["medio_pago"], m["medio_pago"])
    total_ventas = facturas.aggregate(t=Sum("total"))["t"] or Decimal("0")
    num_ventas = facturas.count()

    lineas = LineaVenta.objects.filter(factura__in=facturas)

    regalias_altas = list(
        lineas.filter(es_regalia=True)
        .annotate(valor=F("producto__precio_venta") * F("cantidad"))
        .filter(valor__gt=REGALIA_MAXIMA_SIN_AUTORIZACION)
        .select_related("producto", "factura")
        .values("factura__numero", "producto__nombre", "cantidad", "valor")
    )
    descuentos_altos = list(
        lineas.filter(es_regalia=False, descuento_pct__gt=DESCUENTO_MAXIMO_SIN_AUTORIZACION)
        .select_related("producto", "factura")
        .values("factura__numero", "producto__nombre", "descuento_pct", "descuento_monto")
    )

    sesiones = list(
        SesionCaja.objects.filter(
            sucursal__empresa=empresa, estado=SesionCaja.Estado.CERRADA, cerrada_en__date=fecha,
        )
        .select_related("usuario", "sucursal")
        .values("usuario__username", "sucursal__nombre", "monto_esperado", "monto_contado", "diferencia")
    )
    sesiones_con_diferencia = [s for s in sesiones if s["diferencia"]]

    ediciones_auditlog = list(
        AuditLog.objects.filter(
            tabla__in=_TABLAS_FINANCIERAS, accion__in=("editar", "borrar"), fecha__date=fecha,
        )
        .select_related("usuario")
        .values("tabla", "objeto_id", "accion", "usuario__username", "fecha")
        .order_by("tabla", "fecha")
    )

    return {
        "empresa": empresa,
        "fecha": fecha,
        "ventas": {
            "total": total_ventas,
            "num_ventas": num_ventas,
            "por_medio": ventas_por_medio,
        },
        "regalias_altas": regalias_altas,
        "descuentos_altos": descuentos_altos,
        "sesiones_cerradas": sesiones,
        "sesiones_con_diferencia": sesiones_con_diferencia,
        "ediciones_auditlog": ediciones_auditlog,
    }
