"""Qué compró cada cliente y cuándo se le acaba (14/10/2026, pedido de Oscar).

Junta las dos fuentes de compras de una persona —las ventas de la caja
(`ventas.FacturaVenta`) y los pedidos del sitio (`pedidos.Pedido`)— y saca de
ahí tres cosas: el historial, un resumen (marcas, frecuencia, total) y cuándo
se le va a acabar lo que compra seguido (alimento y arena).

Cómo se estima "cuándo se le acaba"
-----------------------------------
Con el ritmo REAL de la persona, no con una tabla: se mide cuánto compró entre
la primera y la última compra y en cuántos días se lo comió. Con eso se calcula
cuánto le dura lo último que llevó. Se mide en kilos cuando el producto dice su
contenido (así una bolsa de 2 kg y una de 15 kg de la misma fórmula cuentan
bien) y en unidades cuando no.

Con UNA sola compra no se sabe el ritmo y no se inventa: dice "falta otra
compra". Estimar con el peso de la mascota y la guía de la bolsa queda para
más adelante, si hace falta.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db.models import Prefetch
from django.utils import timezone

# Lo que se acaba y se vuelve a comprar: por eso tiene sentido avisar.
RAICES_CONSUMIBLES = {"Alimento", "Arena y sanitarios"}

# Contenido del empaque llevado a kilos (o litros, que para esto es igual).
_A_KILOS = {"kg": Decimal("1"), "g": Decimal("0.001"), "lb": Decimal("0.4536"),
            "oz": Decimal("0.02835"), "l": Decimal("1"), "ml": Decimal("0.001")}

# Si el pronóstico quedó más de esto en el pasado, ya no es "se le acaba":
# probablemente compra en otro lado o dejó de tener mascota. No se le insiste.
DIAS_OLVIDADO = 45


@dataclass
class Compra:
    fecha: date
    canal: str            # "Tienda" o "Sitio web"
    numero: str
    total: Decimal
    lineas: list          # [(producto, cantidad)]
    con_cupon: bool = False


@dataclass
class Consumible:
    clave: tuple
    producto: object      # el último que compró (su nombre es el que se muestra)
    veces: int
    cada_dias: int | None
    ultima: date
    se_acaba: date | None
    dias_para: int | None = None

    @property
    def estado(self):
        if self.se_acaba is None:
            return "sin_ritmo"
        if self.dias_para is not None and self.dias_para <= 7:
            return "pronto"
        return "bien"


@dataclass
class Resumen:
    compras: int = 0
    total: Decimal = Decimal("0")
    ultima: date | None = None
    cada_dias: int | None = None
    marcas: list = field(default_factory=list)   # [(marca, veces)]


# ---------------------------------------------------------------------------
# Compras de un cliente
# ---------------------------------------------------------------------------

def _facturas(clientes_ids, desde=None):
    from ventas.models import FacturaVenta, LineaVenta

    qs = (FacturaVenta.objects.filter(cliente_id__in=clientes_ids, estado=FacturaVenta.Estado.EMITIDA)
          .prefetch_related(Prefetch("lineas", queryset=LineaVenta.objects.select_related(
              "producto", "producto__categoria", "producto__categoria__padre")))
          .select_related("cupon_manada"))
    if desde:
        qs = qs.filter(creado_en__date__gte=desde)
    return qs


def _pedidos(clientes_ids, desde=None):
    from pedidos.models import LineaPedido, Pedido

    qs = (Pedido.objects.filter(cliente_id__in=clientes_ids).exclude(estado=Pedido.Estado.CANCELADO)
          .prefetch_related(Prefetch("lineas", queryset=LineaPedido.objects.select_related(
              "producto", "producto__categoria", "producto__categoria__padre"))))
    if desde:
        qs = qs.filter(creado_en__date__gte=desde)
    return qs


def _a_compra_factura(f):
    return Compra(fecha=timezone.localtime(f.creado_en).date(), canal="Tienda", numero=f.numero, total=f.total,
                  lineas=[(l.producto, l.cantidad) for l in f.lineas.all()],
                  con_cupon=hasattr(f, "cupon_manada"))


def _a_compra_pedido(p):
    return Compra(fecha=timezone.localtime(p.creado_en).date(), canal="Sitio web", numero=p.numero, total=p.total,
                  lineas=[(l.producto, l.cantidad) for l in p.lineas.all()])


def compras_de(cliente, desde=None):
    compras = [_a_compra_factura(f) for f in _facturas([cliente.pk], desde)]
    compras += [_a_compra_pedido(p) for p in _pedidos([cliente.pk], desde)]
    return sorted(compras, key=lambda c: (c.fecha, c.numero), reverse=True)


def compras_por_cliente(clientes_ids, desde=None):
    """Lo mismo para muchos clientes de una vez (dos consultas, no una por
    cliente): lo usan las listas de recordatorios y promociones."""
    por_cliente = defaultdict(list)
    for f in _facturas(clientes_ids, desde):
        por_cliente[f.cliente_id].append(_a_compra_factura(f))
    for p in _pedidos(clientes_ids, desde):
        por_cliente[p.cliente_id].append(_a_compra_pedido(p))
    for lista in por_cliente.values():
        lista.sort(key=lambda c: (c.fecha, c.numero), reverse=True)
    return por_cliente


def cantidad_de_compras(cliente):
    from pedidos.models import Pedido
    from ventas.models import FacturaVenta

    return (FacturaVenta.objects.filter(cliente=cliente, estado=FacturaVenta.Estado.EMITIDA).count()
            + Pedido.objects.filter(cliente=cliente).exclude(estado=Pedido.Estado.CANCELADO).count())


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def _cada_cuanto(fechas):
    fechas = sorted(set(fechas))
    if len(fechas) < 2:
        return None
    return round((fechas[-1] - fechas[0]).days / (len(fechas) - 1))


def resumir(compras):
    r = Resumen(compras=len(compras), total=sum((c.total for c in compras), Decimal("0")))
    if compras:
        r.ultima = max(c.fecha for c in compras)
        r.cada_dias = _cada_cuanto([c.fecha for c in compras])
    # "Veces" = en cuántas compras apareció la marca, no cuántas unidades:
    # tres bolsas el mismo día son una visita.
    marcas = Counter()
    for c in compras:
        for m in {(p.marca or "").strip() for p, _ in c.lineas if (p.marca or "").strip()}:
            marcas[m] += 1
    r.marcas = marcas.most_common()
    return r


# ---------------------------------------------------------------------------
# Lo que se le acaba
# ---------------------------------------------------------------------------

def _raiz(producto):
    cat = producto.categoria
    if cat is None:
        return ""
    return cat.padre.nombre if cat.padre_id else cat.nombre


def es_consumible(producto):
    return bool(producto.ficha_alimento_id) or _raiz(producto) in RAICES_CONSUMIBLES


def _kilos(producto):
    factor = _A_KILOS.get(producto.peso_unidad or "")
    if factor is None or not producto.peso_valor:
        return None
    return producto.peso_valor * factor


def consumibles(compras, hoy=None):
    """Una fila por cada alimento (o arena) que la persona compra.

    Cuenta como el mismo alimento la misma FÓRMULA aunque cambie el tamaño de
    la bolsa (`ficha_alimento`); sin ficha, el mismo producto.
    """
    hoy = hoy or timezone.localdate()
    grupos = defaultdict(lambda: defaultdict(list))   # clave -> fecha -> [(producto, cantidad)]
    for c in compras:
        for producto, cantidad in c.lineas:
            if es_consumible(producto):
                clave = ("F", producto.ficha_alimento_id) if producto.ficha_alimento_id else ("P", producto.pk)
                grupos[clave][c.fecha].append((producto, cantidad))

    filas = []
    for clave, por_fecha in grupos.items():
        fechas = sorted(por_fecha)
        ultima = fechas[-1]
        producto = por_fecha[ultima][-1][0]
        todos = [x for f in fechas for x in por_fecha[f]]
        # En kilos si TODOS dicen su contenido; si uno no, en unidades, para
        # no sumar kilos con bolsas.
        en_kilos = all(_kilos(p) for p, _ in todos)

        def cuanto(items):
            return sum(((_kilos(p) if en_kilos else Decimal("1")) * q for p, q in items), Decimal("0"))

        se_acaba = None
        if len(fechas) >= 2:
            dias = (ultima - fechas[0]).days
            consumido = sum((cuanto(por_fecha[f]) for f in fechas[:-1]), Decimal("0"))
            if dias > 0 and consumido > 0:
                por_dia = consumido / dias
                se_acaba = ultima + timedelta(days=int(cuanto(por_fecha[ultima]) / por_dia))
        filas.append(Consumible(
            clave=clave, producto=producto, veces=len(fechas), cada_dias=_cada_cuanto(fechas),
            ultima=ultima, se_acaba=se_acaba, dias_para=(se_acaba - hoy).days if se_acaba else None,
        ))
    # Lo más urgente arriba; lo que todavía no tiene ritmo, al final.
    return sorted(filas, key=lambda f: (f.se_acaba is None, f.se_acaba or f.ultima))


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------

def numero_whatsapp(telefono):
    digitos = "".join(c for c in (telefono or "") if c.isdigit())
    if len(digitos) == 8:
        return "506" + digitos  # número de Costa Rica sin el código de país
    return digitos if len(digitos) >= 10 else ""


def enlace_whatsapp(telefono, mensaje):
    numero = numero_whatsapp(telefono)
    return f"https://wa.me/{numero}?text={quote(mensaje)}" if numero else ""


def primer_nombre(cliente):
    return (cliente.nombre or "").split()[0].capitalize() if cliente.nombre else ""


def mascota_para(cliente, producto):
    """El nombre de la mascota que come eso, si el cliente nos contó: un
    alimento de perro se lo come el perro, no el gato."""
    mascotas = list(cliente.mascotas.all())
    if not mascotas:
        return ""
    destino = (producto.mascota or "").lower()
    for m in mascotas:
        if (m.especie == "PER" and "perro" in destino) or (m.especie == "GAT" and "gato" in destino):
            return m.nombre
    return mascotas[0].nombre if len(mascotas) == 1 else ""


def mensaje_recordatorio(cliente, consumible):
    mascota = mascota_para(cliente, consumible.producto)
    saludo = f"Hola {primer_nombre(cliente)}" + (f", ¿cómo está {mascota}?" if mascota else ", ¿cómo está?")
    return (f"{saludo} Ya casi se le acaba su {consumible.producto.nombre}. "
            "Se lo tenemos listo en la tienda o se lo enviamos. — AllPetcr.com")


# ---------------------------------------------------------------------------
# Listas para escribirle a la gente
# ---------------------------------------------------------------------------

def _clientes_con_compras(empresa, desde):
    from pedidos.models import Pedido
    from ventas.models import Cliente, FacturaVenta

    ids = set(FacturaVenta.objects.filter(empresa=empresa, cliente__isnull=False, creado_en__date__gte=desde,
                                          estado=FacturaVenta.Estado.EMITIDA).values_list("cliente_id", flat=True))
    ids |= set(Pedido.objects.filter(empresa=empresa, cliente__isnull=False, creado_en__date__gte=desde)
               .values_list("cliente_id", flat=True))
    return (Cliente.objects.filter(empresa=empresa, activo=True, pk__in=ids)
            .select_related("manada").prefetch_related("mascotas"))


@dataclass
class Recordatorio:
    cliente: object
    consumible: Consumible
    acepta: bool
    enlace: str


def recordatorios(empresa, dias=7, hoy=None):
    """A quién se le acaba algo en los próximos `dias` (o ya se le acabó hace
    poco). Solo los que aceptaron mensajes llevan botón de WhatsApp: a los
    demás se los ve, pero no se les escribe (Ley 8968)."""
    hoy = hoy or timezone.localdate()
    desde = hoy - timedelta(days=365)
    clientes = list(_clientes_con_compras(empresa, desde))
    compras = compras_por_cliente([c.pk for c in clientes], desde)
    filas = []
    for cliente in clientes:
        acepta = bool(getattr(getattr(cliente, "manada", None), "acepta_promociones", False))
        for item in consumibles(compras.get(cliente.pk, []), hoy):
            if item.se_acaba is None or not (-DIAS_OLVIDADO <= item.dias_para <= dias):
                continue
            enlace = enlace_whatsapp(cliente.telefono, mensaje_recordatorio(cliente, item)) if acepta else ""
            filas.append(Recordatorio(cliente=cliente, consumible=item, acepta=acepta, enlace=enlace))
    return sorted(filas, key=lambda r: r.consumible.se_acaba)


@dataclass
class Destinatario:
    cliente: object
    veces: int
    ultima: date


def marcas_compradas(empresa, meses=6):
    desde = timezone.localdate() - timedelta(days=30 * meses)
    clientes = list(_clientes_con_compras(empresa, desde))
    compras = compras_por_cliente([c.pk for c in clientes], desde)
    marcas = Counter()
    for lista in compras.values():
        for m in {(p.marca or "").strip() for c in lista for p, _ in c.lineas if (p.marca or "").strip()}:
            marcas[m] += 1
    return marcas.most_common()


def destinatarios(empresa, *, marca="", especie="", meses=6):
    """Miembros que aceptaron promociones y compraron esa marca en los últimos
    meses (y, si se pide, que tienen esa especie de mascota)."""
    desde = timezone.localdate() - timedelta(days=30 * meses)
    clientes = [c for c in _clientes_con_compras(empresa, desde)
                if getattr(getattr(c, "manada", None), "acepta_promociones", False)]
    if especie:
        clientes = [c for c in clientes if any(m.especie == especie for m in c.mascotas.all())]
    compras = compras_por_cliente([c.pk for c in clientes], desde)
    filas = []
    for c in clientes:
        lista = compras.get(c.pk, [])
        if marca:
            lista = [x for x in lista if any((p.marca or "").strip().lower() == marca.lower() for p, _ in x.lineas)]
        if lista:
            filas.append(Destinatario(cliente=c, veces=len(lista), ultima=max(x.fecha for x in lista)))
    return sorted(filas, key=lambda d: (-d.veces, d.cliente.nombre))
