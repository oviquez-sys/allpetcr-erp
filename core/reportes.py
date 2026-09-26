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
    filas = list(filas)
    # El objeto Producto de cada fila, para que el reporte muestre la foto
    # (20/09/2026). Una sola consulta extra para las N filas, no una por fila.
    from catalogo.models import Producto

    por_id = Producto.objects.in_bulk([f["producto_id"] for f in filas])
    for f in filas:
        f["producto"] = por_id.get(f["producto_id"])
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
    # Pagos mixtos repartidos por medio (VEN-04, ventas/pagos.py).
    from ventas.pagos import por_medio as _por_medio
    _medios = dict(FacturaVenta.MedioPago.choices)
    ventas_por_medio = sorted(
        ({"medio_pago": _medios.get(m, m), "total": d["t"], "cantidad": d["n"]}
         for m, d in _por_medio(facturas).items()),
        key=lambda m: -m["total"],
    )
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


# --------------------------------------------------------------------------
# Ventas por período, por categoría y menos vendidos (auditoría 26/09/2026,
# CAJ-04). Faltaban: el ERP decía qué se vende más, pero no cómo van las
# ventas semana a semana, qué categoría deja la plata ni qué se quedó dormido.
# --------------------------------------------------------------------------
AGRUPACIONES = {"dia": "Por día", "semana": "Por semana", "mes": "Por mes"}


def ventas_por_periodo(empresa, desde, hasta, agrupar="dia"):
    from django.db.models.functions import TruncDay, TruncMonth, TruncWeek

    from ventas.models import DevolucionVenta, FacturaVenta, LineaVenta

    trunc = {"dia": TruncDay, "semana": TruncWeek, "mes": TruncMonth}.get(agrupar, TruncDay)
    facturas = FacturaVenta.objects.filter(
        empresa=empresa, estado=FacturaVenta.Estado.EMITIDA,
        creado_en__date__gte=desde, creado_en__date__lte=hasta,
    )
    dinero = DecimalField(max_digits=14, decimal_places=2)
    por_periodo = {
        f["periodo"]: f for f in facturas.annotate(periodo=trunc("creado_en")).values("periodo")
        .annotate(tiquetes=Count("id"), total=Sum("total"), sin_iva=Sum("subtotal"), iva=Sum("impuesto"))
    }
    costos = {
        c["periodo"]: c["costo"] for c in LineaVenta.objects.filter(factura__in=facturas, es_regalia=False)
        .annotate(periodo=trunc("factura__creado_en")).values("periodo")
        .annotate(costo=Sum(F("costo_unitario") * F("cantidad"), output_field=dinero))
    }
    filas = []
    for periodo in sorted(por_periodo):
        f = por_periodo[periodo]
        costo = costos.get(periodo) or Decimal("0")
        filas.append({
            "periodo": timezone.localtime(periodo).date() if timezone.is_aware(periodo) else periodo,
            "tiquetes": f["tiquetes"], "total": f["total"] or Decimal("0"),
            "sin_iva": f["sin_iva"] or Decimal("0"), "iva": f["iva"] or Decimal("0"),
            "costo": costo, "utilidad": (f["sin_iva"] or Decimal("0")) - costo,
        })

    # Por categoría raíz. La venta sin IVA sale de la línea (VEN-08); en las
    # ventas anteriores al 26/09/2026 la línea no la tiene y se usa el total.
    base = Coalesce("subtotal", "total", output_field=dinero)
    por_categoria = list(
        LineaVenta.objects.filter(factura__in=facturas, es_regalia=False)
        .annotate(cat=Coalesce("producto__categoria__padre__nombre", "producto__categoria__nombre",
                               Value("Sin categoría")))
        .values("cat")
        .annotate(unidades=Sum("cantidad"), venta=Sum(base),
                  costo=Sum(F("costo_unitario") * F("cantidad"), output_field=dinero))
        .order_by("-venta")
    )
    for c in por_categoria:
        c["utilidad"] = (c["venta"] or Decimal("0")) - (c["costo"] or Decimal("0"))

    # Por división: alimentos para perro, para gato, y accesorios (26/09/2026).
    from catalogo.divisiones import ORDEN, anotar_division
    from catalogo.models import Producto

    ventas_div = {
        d["div"]: d for d in LineaVenta.objects.filter(factura__in=facturas, es_regalia=False)
        .annotate(div=anotar_division("producto__")).values("div")
        .annotate(unidades=Sum("cantidad"), venta=Sum(base),
                  costo=Sum(F("costo_unitario") * F("cantidad"), output_field=dinero))
    }
    inventario_div = {
        d["div"]: d for d in Producto.objects.filter(empresa=empresa, activo=True, stock_actual__gt=0)
        .annotate(div=anotar_division()).values("div")
        .annotate(productos=Count("id"),
                  capital=Sum(F("stock_actual") * F("costo_promedio"), output_field=dinero))
    }
    por_division = []
    for nombre in ORDEN:
        v, i = ventas_div.get(nombre, {}), inventario_div.get(nombre, {})
        if not v and not i:
            continue
        venta, costo = v.get("venta") or Decimal("0"), v.get("costo") or Decimal("0")
        por_division.append({"division": nombre, "unidades": v.get("unidades") or Decimal("0"),
                             "venta": venta, "costo": costo, "utilidad": venta - costo,
                             "productos": i.get("productos") or 0,
                             "capital": i.get("capital") or Decimal("0")})

    devoluciones = DevolucionVenta.objects.filter(
        factura__empresa=empresa, creado_en__date__gte=desde, creado_en__date__lte=hasta,
    ).aggregate(t=Sum("total"), n=Count("id"))
    tot = lambda clave: sum((f[clave] for f in filas), Decimal("0"))  # noqa: E731
    return {
        "filas": filas, "por_categoria": por_categoria, "por_division": por_division, "desde": desde, "hasta": hasta, "agrupar": agrupar,
        "totales": {"tiquetes": sum(f["tiquetes"] for f in filas), "total": tot("total"),
                    "sin_iva": tot("sin_iva"), "iva": tot("iva"), "costo": tot("costo"),
                    "utilidad": tot("utilidad")},
        "devoluciones": devoluciones["t"] or Decimal("0"), "n_devoluciones": devoluciones["n"],
    }


def menos_vendidos(empresa, desde, hasta, limite=50):
    """Lo que hay en bodega y casi no se mueve: plata dormida. Incluye lo que
    no se vendió ni una vez en el rango (que es lo más dormido de todo)."""
    from catalogo.models import Producto

    vendidas = Coalesce(Sum(
        "lineaventa__cantidad",
        filter=Q(lineaventa__factura__estado="EMI",
                 lineaventa__factura__creado_en__date__gte=desde,
                 lineaventa__factura__creado_en__date__lte=hasta),
    ), Value(Decimal("0")), output_field=DecimalField(max_digits=14, decimal_places=2))
    productos = (Producto.objects.filter(empresa=empresa, activo=True, stock_actual__gt=0)
                 .annotate(vendidas=vendidas)
                 .annotate(capital=F("stock_actual") * F("costo_promedio"))
                 .order_by("vendidas", "-capital")[:limite])
    return list(productos)
