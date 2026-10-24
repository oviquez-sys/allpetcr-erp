"""Fechas de vencimiento (pedido de Oscar, 24/10/2026).

Se escanea el producto, se escribe la fecha que trae el empaque y cuántas
unidades la tienen. Con eso:
- cada producto muestra sus lotes y cuántas quedan de cada uno,
- hay una lista de lo que vence pronto (y lo ya vencido),
- y otra de los alimentos con existencia a los que todavía no se les anotó
  la fecha.

Cuánto queda de cada lote
-------------------------
Las ventas no saben de lotes (el POS no pregunta de qué bolsa salió). Se
supone lo que se hace en el estante: se vende primero lo que vence primero.
Entonces la existencia actual se reparte desde el lote que vence MÁS TARDE
hacia atrás; lo que no alcanza a cubrir es lo que ya se vendió. Si la
existencia es mayor que lo anotado, la diferencia queda "sin fecha".
Ventaja: no hubo que tocar ventas ni compras, y la lista nunca dice que hay
más unidades de las que hay.
"""
import calendar
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import LoteVencimiento

# Categorías raíz que importan para "sin fecha" (lo que se come o se aplica).
RAICES_CON_VENCIMIENTO = {"Alimento", "Snacks y premios"}

VISTAS = {"30": "Vencidos y próximos 30 días", "60": "60 días", "90": "90 días",
          "todos": "Todos", "sin": "Sin fecha"}


def interpretar_fecha(texto, hoy=None):
    """Lo que dice el empaque → fecha.

    "15/08/2027", "15-08-27", "2027-08-15" → ese día.
    "08/2027", "8/27", "ago 2027"            → último día de ese mes (muchas
    bolsas solo traen mes y año; se toma el último día, que es como se lee
    "vence 08/2027")."""
    hoy = hoy or timezone.localdate()
    t = (texto or "").strip().lower()
    if not t:
        raise ValidationError("Escribí la fecha de vencimiento.")
    meses = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
             "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
    for nombre, numero in meses.items():
        t = re.sub(rf"\b{nombre}[a-z]*\b", str(numero), t)
    partes = [p for p in re.split(r"[^0-9]+", t) if p]

    def anio(v):
        v = int(v)
        return v + 2000 if v < 100 else v

    try:
        if len(partes) == 3 and len(partes[0]) == 4:          # 2027-08-15
            f = date(int(partes[0]), int(partes[1]), int(partes[2]))
        elif len(partes) == 3:                                # 15/08/2027
            f = date(anio(partes[2]), int(partes[1]), int(partes[0]))
        elif len(partes) == 2:                                # 08/2027
            a, m = anio(partes[1]), int(partes[0])
            f = date(a, m, calendar.monthrange(a, m)[1])
        else:
            raise ValueError
    except (ValueError, IndexError):
        raise ValidationError("No entendí la fecha. Escribila como 15/08/2027, o 08/2027 si solo trae mes y año.")
    if f < hoy - timedelta(days=730) or f > hoy + timedelta(days=3650):
        raise ValidationError(f"Revisá la fecha: {f:%d/%m/%Y} no parece de vencimiento.")
    return f


def estado(fecha, hoy=None):
    hoy = hoy or timezone.localdate()
    dias = (fecha - hoy).days
    if dias < 0:
        return "vencido", "Vencido"
    if dias <= 30:
        return "pronto", "Vence pronto"
    if dias <= 90:
        return "atento", "En 3 meses"
    return "ok", "Bien"


def repartir(producto, lotes):
    """[(lote, quedan)] y las unidades sin fecha, según la existencia actual."""
    restante = max(producto.stock_actual or Decimal("0"), Decimal("0"))
    quedan = {}
    for lote in sorted(lotes, key=lambda l: (l.fecha_vencimiento, l.id), reverse=True):
        q = min(lote.cantidad, restante)
        quedan[lote.pk] = q
        restante -= q
    ordenados = sorted(lotes, key=lambda l: (l.fecha_vencimiento, l.id))
    return [(l, quedan[l.pk]) for l in ordenados], restante


def ficha_producto(producto, hoy=None):
    lotes, sin_fecha = repartir(producto, list(producto.lotes_vencimiento.all()))
    return {
        "lotes": [{"lote": l, "quedan": q, "estado": estado(l.fecha_vencimiento, hoy),
                   "dias": (l.fecha_vencimiento - (hoy or timezone.localdate())).days} for l, q in lotes],
        "sin_fecha": sin_fecha,
    }


def registrar(producto, texto_fecha, cantidad, usuario=None, nota=""):
    """Anota (o suma a) el lote de esa fecha. Devuelve (lote, fecha)."""
    fecha = interpretar_fecha(texto_fecha)
    try:
        cantidad = Decimal(str(cantidad).replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValidationError("La cantidad tiene que ser un número.")
    if cantidad <= 0 or cantidad > 100000:
        raise ValidationError("La cantidad tiene que ser mayor que cero.")
    lote = LoteVencimiento.objects.filter(producto=producto, fecha_vencimiento=fecha).first()
    if lote:
        lote.cantidad += cantidad
        lote.save(update_fields=["cantidad"])
    else:
        lote = LoteVencimiento.objects.create(producto=producto, fecha_vencimiento=fecha, cantidad=cantidad,
                                              creado_por=usuario, nota=(nota or "").strip()[:120])
    return lote, fecha


def proximos(empresa, dias=30, hoy=None):
    """Lotes con unidades que quedan, que vencen dentro de `dias` (None = todos).
    Los vencidos siempre salen primero."""
    hoy = hoy or timezone.localdate()
    lotes = list(LoteVencimiento.objects.filter(producto__empresa=empresa, producto__activo=True)
                 .select_related("producto", "producto__categoria"))
    por_producto = defaultdict(list)
    for l in lotes:
        por_producto[l.producto_id].append(l)
    filas = []
    for grupo in por_producto.values():
        producto = grupo[0].producto
        repartidos, _ = repartir(producto, grupo)
        for lote, quedan in repartidos:
            if quedan <= 0:
                continue
            if dias is not None and lote.fecha_vencimiento > hoy + timedelta(days=dias):
                continue
            filas.append({"producto": producto, "lote": lote, "quedan": quedan,
                          "dias": (lote.fecha_vencimiento - hoy).days,
                          "estado": estado(lote.fecha_vencimiento, hoy)})
    filas.sort(key=lambda f: (f["lote"].fecha_vencimiento, f["producto"].nombre))
    return filas


def sin_fecha(empresa):
    """Alimentos y snacks con existencia que tienen unidades sin fecha anotada."""
    from catalogo.models import Producto

    productos = (Producto.objects.filter(empresa=empresa, activo=True, stock_actual__gt=0)
                 .filter(Q(categoria__nombre__in=RAICES_CON_VENCIMIENTO)
                         | Q(categoria__padre__nombre__in=RAICES_CON_VENCIMIENTO))
                 .select_related("categoria").prefetch_related("lotes_vencimiento").order_by("nombre"))
    filas = []
    for p in productos:
        _, faltan = repartir(p, list(p.lotes_vencimiento.all()))
        if faltan > 0:
            filas.append({"producto": p, "faltan": faltan})
    return filas
