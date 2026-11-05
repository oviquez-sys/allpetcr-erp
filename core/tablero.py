"""Tablero «¿Cómo vamos?» (05/11/2026, encargo v3 de Oscar, fase 1).

Para decidir en el momento, sin esperar el cierre. Se calcula al abrirlo (no
hay caché: con ~5 ventas al día cuesta milisegundos) y todo sale de las
ventas EMITIDAS; las anuladas no cuentan.

Definiciones que hay que conocer para leerlo bien:

- **Ganancia bruta** = lo vendido SIN IVA − el costo de lo vendido (incluye el
  costo de las regalías, que salen sin cobrar). No descuenta comisiones del
  datáfono ni gastos fijos.
- **Punto de equilibrio del periodo** = gastos fijos de los días abiertos del
  periodo ÷ la ganancia por cada ₡100 vendidos de los últimos 30 días. Se usa
  el margen de 30 días y no el del periodo porque un solo día con dos ventas
  da un margen que no dice nada. Sin ventas en 30 días, el margen de respaldo
  de MetaNegocio (25 %, el que dio Oscar).
- **Gasto fijo de un día abierto** = gasto del mes × 12 ÷ 52 ÷ días que abre
  por semana. Con ₡855.000 y lunes a sábado: ₡32.885.
- **Cliente nuevo** = su primera compra (en caja) cae en el periodo.
  **Volvió** = compró en el periodo y no era su primera compra.
- **Cliente activo de alimento** = compró alimento en los últimos 60 días.
- **Días sin venta** de un producto = desde su última venta o, si nunca se
  vendió, desde que entró al inventario: un saco que llegó ayer no está
  «parado».
- Las devoluciones no se restan todavía (hay muy pocas); los pedidos web
  cuentan cuando se cobran en caja.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Max, Min, Q, Sum
from django.utils import timezone

from catalogo.models import Producto
from manada.exclusiones import RAICES_SIN_CUPON, TIPOS_FICHA_SIN_CUPON, producto_es_alimento
from ventas.models import Cliente, FacturaVenta, LineaVenta

from .models import MetaNegocio

CERO = Decimal("0")
CIEN = Decimal("100")
DIAS_CLIENTE_ACTIVO = 60
DIAS_PARADO = (30, 60, 90)

PERIODOS = [("hoy", "Hoy"), ("semana", "Esta semana"), ("mes", "Este mes"), ("rango", "Fechas")]


# ---------------------------------------------------------------------------
# Periodo
# ---------------------------------------------------------------------------
def _fecha(texto):
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def periodo(params, hoy=None):
    """(desde, hasta, clave). Semana = de lunes a hoy; mes = del 1.º a hoy.
    Un rango sin fechas válidas cae en hoy; nunca pasa de hoy ni de 366 días."""
    hoy = hoy or timezone.localdate()
    clave = params.get("periodo") or "hoy"
    if clave == "semana":
        return hoy - timedelta(days=hoy.weekday()), hoy, clave
    if clave == "mes":
        return hoy.replace(day=1), hoy, clave
    if clave == "rango":
        desde, hasta = _fecha(params.get("desde")), _fecha(params.get("hasta"))
        if desde and hasta:
            desde, hasta = min(desde, hasta), min(max(desde, hasta), hoy)
            desde = max(desde, hasta - timedelta(days=365))
            return min(desde, hasta), hasta, clave
    return hoy, hoy, "hoy"


def dias_abiertos(meta, desde, hasta) -> int:
    return sum(1 for i in range((hasta - desde).days + 1) if meta.abre(desde + timedelta(days=i)))


def gasto_fijo_dia(meta) -> Decimal:
    por_semana = len(set(meta.dias_abiertos or "")) or 1
    # Decimal(str()): una meta sin guardar trae los valores de fábrica como int.
    return (Decimal(str(meta.gasto_fijo_mensual)) * 12 / 52 / por_semana).quantize(Decimal("1"))


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------
@dataclass
class Semaforo:
    titulo: str
    valor: Decimal
    meta: Decimal
    formato: str = "crc"          # crc | pct | num
    nota: str = ""

    @property
    def avance(self):
        if not self.meta:
            return None
        return int(self.valor * 100 / self.meta)

    @property
    def color(self):
        a = self.avance
        if a is None:
            return "gris"
        return "verde" if a >= 100 else ("amarillo" if a >= 70 else "rojo")


def _filtro_alimento():
    return (Q(producto__categoria__padre__nombre__in=RAICES_SIN_CUPON)
            | Q(producto__categoria__padre__isnull=True, producto__categoria__nombre__in=RAICES_SIN_CUPON)
            | Q(producto__ficha_alimento__tipo__in=TIPOS_FICHA_SIN_CUPON))


def clientes_activos_alimento(empresa, hasta, dias=DIAS_CLIENTE_ACTIVO) -> int:
    desde = hasta - timedelta(days=dias - 1)
    return (LineaVenta.objects
            .filter(_filtro_alimento(), factura__empresa=empresa, factura__estado=FacturaVenta.Estado.EMITIDA,
                    factura__cliente__isnull=False, factura__creado_en__date__gte=desde,
                    factura__creado_en__date__lte=hasta)
            .values("factura__cliente").distinct().count())


def _sin_iva(linea):
    return linea.subtotal if linea.subtotal is not None else linea.total


def _ventas(empresa, desde, hasta):
    return list(FacturaVenta.objects
                .filter(empresa=empresa, estado=FacturaVenta.Estado.EMITIDA,
                        creado_en__date__gte=desde, creado_en__date__lte=hasta)
                .select_related("usuario", "cliente")
                .prefetch_related("lineas__producto__categoria__padre", "lineas__producto__ficha_alimento"))


def _venta_y_ganancia(facturas):
    venta = sum((f.total for f in facturas), CERO)
    sin_iva = costo = CERO
    for f in facturas:
        for l in f.lineas.all():
            sin_iva += _sin_iva(l)
            costo += l.costo_unitario * l.cantidad
    return venta, sin_iva - costo


def _nombre(u):
    if u is None:
        return "—"
    return (u.get_full_name() or u.username).split(" ")[0]


def _clientes(empresa, facturas, desde):
    """Nuevos, que volvieron y de dónde vinieron los nuevos."""
    por_cliente = Counter(f.cliente_id for f in facturas if f.cliente_id)
    if not por_cliente:
        return {"nuevos": 0, "volvieron": 0, "origen": []}
    primeras = dict(FacturaVenta.objects
                    .filter(estado=FacturaVenta.Estado.EMITIDA, cliente_id__in=por_cliente)
                    .values_list("cliente").annotate(p=Min("creado_en")))
    nuevos = [cid for cid, p in primeras.items() if timezone.localtime(p).date() >= desde]
    volvieron = sum(1 for cid, n in por_cliente.items()
                    if timezone.localtime(primeras[cid]).date() < desde or n >= 2)
    origen = Counter()
    for c in Cliente.objects.filter(pk__in=nuevos).select_related("manada"):
        if c.como_nos_conocio:
            origen[c.get_como_nos_conocio_display()] += 1
        elif getattr(getattr(c, "manada", None), "origen", "") in ("GOO", "COR", "FOR"):
            origen["Se registró en la web"] += 1
        else:
            origen["Sin dato"] += 1
    return {"nuevos": len(nuevos), "volvieron": volvieron, "origen": origen.most_common()}


def _con_cliente(facturas):
    total = len(facturas)
    con = sum(1 for f in facturas if f.cliente_id)
    motivos = Counter(f.get_sin_cliente_display() or "Antes de que la caja preguntara"
                      for f in facturas if not f.cliente_id)
    cajeros = defaultdict(lambda: [0, 0, 0])      # ventas, con cliente, «no quiso»
    dias = defaultdict(lambda: [0, 0])
    for f in facturas:
        c = cajeros[_nombre(f.usuario)]
        c[0] += 1
        c[1] += 1 if f.cliente_id else 0
        c[2] += 1 if f.sin_cliente == FacturaVenta.SinCliente.NO_QUISO else 0
        d = dias[timezone.localtime(f.creado_en).date()]
        d[0] += 1
        d[1] += 1 if f.cliente_id else 0
    return {
        "total": total, "con": con, "pct": int(con * 100 / total) if total else None,
        "motivos": motivos.most_common(),
        "cajeros": sorted(({"nombre": k, "ventas": v[0], "con": v[1], "no_quiso": v[2],
                            "pct": int(v[1] * 100 / v[0])} for k, v in cajeros.items()),
                          key=lambda x: -x["ventas"]),
        "dias": [{"fecha": k, "ventas": v[0], "pct": int(v[1] * 100 / v[0])} for k, v in sorted(dias.items())],
    }


def _alimento_con_otra_cosa(facturas):
    con_alimento = con_otra = 0
    for f in facturas:
        tipos = {producto_es_alimento(l.producto) for l in f.lineas.all()}
        if True in tipos:
            con_alimento += 1
            con_otra += 1 if False in tipos else 0
    return {"con_alimento": con_alimento, "con_otra": con_otra,
            "pct": int(con_otra * 100 / con_alimento) if con_alimento else None}


def _promociones(empresa, hoy):
    from catalogo.models import Promocion
    from catalogo.promociones import resultados
    filas = []
    for p in (Promocion.objects.filter(empresa=empresa, estado=Promocion.Estado.ACTIVA,
                                       inicio__lte=hoy, fin__gte=hoy).prefetch_related("items__producto")):
        r = resultados(p)
        prods = [i.producto for i in p.items.all()]
        filas.append({"promo": p, **r,
                      "quedan": sum((x.stock_actual for x in prods), CERO),
                      "quedan_costo": sum((x.stock_actual * x.costo_promedio for x in prods), CERO)})
    return filas


def _raiz(p):
    c = p.categoria
    if c is None:
        return "Sin categoría"
    return c.padre.nombre if c.padre_id else c.nombre


def inventario_parado(empresa, hoy, limite=15):
    """Plata parada en lo que no se vende y meses de inventario por categoría."""
    from inventario.models import MovimientoInventario

    productos = list(Producto.objects.filter(empresa=empresa, activo=True, stock_actual__gt=0)
                     .select_related("categoria__padre"))
    ids = [p.pk for p in productos]
    ultima = dict(LineaVenta.objects.filter(producto_id__in=ids, factura__estado=FacturaVenta.Estado.EMITIDA)
                  .values_list("producto").annotate(u=Max("factura__creado_en")))
    entrada = dict(MovimientoInventario.objects.filter(producto_id__in=ids, cantidad__gt=0)
                   .values_list("producto").annotate(p=Min("fecha")))
    desde30 = hoy - timedelta(days=29)
    costo30 = defaultdict(lambda: CERO)
    for l in (LineaVenta.objects.filter(factura__empresa=empresa, factura__estado=FacturaVenta.Estado.EMITIDA,
                                        factura__creado_en__date__gte=desde30)
              .select_related("producto__categoria__padre")):
        costo30[_raiz(l.producto)] += l.costo_unitario * l.cantidad

    tramos = {d: {"dias": d, "productos": 0, "costo": CERO} for d in DIAS_PARADO}
    nunca = {"productos": 0, "costo": CERO}
    lista, por_cat = [], defaultdict(lambda: CERO)
    total = CERO
    for p in productos:
        colones = p.stock_actual * p.costo_promedio
        total += colones
        por_cat[_raiz(p)] += colones
        base = ultima.get(p.pk) or entrada.get(p.pk)
        dias = (hoy - timezone.localtime(base).date()).days if base else None
        if p.pk not in ultima:
            nunca["productos"] += 1
            nunca["costo"] += colones
        for d in DIAS_PARADO:
            if dias is not None and dias >= d:
                tramos[d]["productos"] += 1
                tramos[d]["costo"] += colones
        if p.pk not in ultima or (dias or 0) >= DIAS_PARADO[0]:
            lista.append({"producto": p, "colones": colones, "dias": dias, "nunca": p.pk not in ultima})
    lista.sort(key=lambda x: -x["colones"])
    categorias = sorted(({"nombre": k, "costo": v,
                          "meses": (v / costo30[k]).quantize(Decimal("0.1")) if costo30[k] else None}
                         for k, v in por_cat.items()), key=lambda x: -x["costo"])
    return {"total": total, "tramos": list(tramos.values()), "nunca": nunca,
            "lista": lista[:limite], "categorias": categorias}


def _vencimientos(empresa, hoy):
    from inventario.vencimientos import proximos
    filas = proximos(empresa, dias=90, hoy=hoy)
    return {"filas": filas[:10], "lotes": len(filas),
            "unidades": sum((f["quedan"] for f in filas), CERO),
            "costo": sum((f["quedan"] * f["producto"].costo_promedio for f in filas), CERO)}


def _avisar_hoy(empresa, hoy):
    from manada.historial import recordatorios
    filas = recordatorios(empresa, dias=3, hoy=hoy)
    return {"filas": filas[:8], "total": len(filas), "con_permiso": sum(1 for f in filas if f.acepta)}


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------
def calcular(empresa, desde, hasta, hoy=None) -> dict:
    hoy = hoy or timezone.localdate()
    meta = MetaNegocio.de(empresa)
    facturas = _ventas(empresa, desde, hasta)
    venta, ganancia = _venta_y_ganancia(facturas)

    venta30, ganancia30 = _venta_y_ganancia(_ventas(empresa, hasta - timedelta(days=29), hasta))
    margen = (ganancia30 / venta30) if venta30 > 0 else Decimal(str(meta.margen_respaldo_pct)) / CIEN
    abiertos = dias_abiertos(meta, desde, hasta)
    gasto = gasto_fijo_dia(meta) * abiertos
    equilibrio = (gasto / margen).quantize(Decimal("1")) if margen > 0 else None

    totales = [f.total for f in facturas if f.total > 0]
    cli = _con_cliente(facturas)
    clientes = _clientes(empresa, facturas, desde)
    alimento = _alimento_con_otra_cosa(facturas)

    activos = clientes_activos_alimento(empresa, hasta)
    activos_antes = clientes_activos_alimento(empresa, hasta - timedelta(days=30))

    semaforos = [
        Semaforo("Venta", venta, equilibrio or CERO,
                 nota=f"Punto de equilibrio de {abiertos} día{'s' if abiertos != 1 else ''} abierto"
                      f"{'s' if abiertos != 1 else ''}: ganando ₡{int(margen * 100)} por cada ₡100."),
        Semaforo("Ganancia bruta", ganancia, gasto,
                 nota="Contra los gastos fijos del periodo. Sin comisiones del datáfono."),
        Semaforo("Ventas con cliente", Decimal(cli["pct"] or 0), Decimal(meta.meta_con_cliente_pct), "pct",
                 nota=f"{cli['con']} de {cli['total']} ventas."),
    ]
    return {
        "desde": desde, "hasta": hasta, "hoy": hoy, "meta": meta,
        "abiertos": abiertos, "gasto": gasto, "equilibrio": equilibrio, "margen_pct": int(margen * 100),
        "venta": venta, "ganancia": ganancia, "ventas": len(facturas),
        "semaforos": semaforos,
        "activos": activos, "activos_antes": activos_antes, "activos_cambio": activos - activos_antes,
        "tiquete_promedio": (sum(totales, CERO) / len(totales)).quantize(Decimal("1")) if totales else None,
        "tiquete_mediano": Decimal(statistics.median(totales)).quantize(Decimal("1")) if totales else None,
        "con_cliente": cli, "clientes": clientes, "alimento": alimento,
        "promociones": _promociones(empresa, hoy),
        "inventario": inventario_parado(empresa, hoy),
        "vencimientos": _vencimientos(empresa, hoy),
        "avisar": _avisar_hoy(empresa, hoy),
    }
