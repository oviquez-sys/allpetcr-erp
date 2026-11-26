"""«Reponer»: una sola pantalla para saber qué se vendió, qué se agotó y
cuánto pedir (pedido de Oscar, 26/11/2026).

POR QUÉ EXISTE
--------------
Antes había tres reportes que contestaban pedazos de la misma pregunta:

- «Lo vendido» (20/10): qué salió en unas fechas y cuánto queda.
- «Qué reponer» (05/11): cuánto pedir, con una ventana fija de 30 días.
- «Agotados» (02/10): lo que llegó a cero y la decisión de volver a pedirlo.

Cada uno con su Excel, sus columnas y su criterio de «quedan pocas». Oscar:
«necesito unificarlos, que sean más fáciles de entender y usar… poder ponerle
fechas (por ejemplo saber qué se vendió esta semana)». Ahora es una pantalla,
una función (`datos`) y un Excel que sale de esa misma función.

CÓMO SE CALCULA CADA NÚMERO
---------------------------
- **Vendidas**: unidades de facturas emitidas en el rango, menos lo devuelto
  de esas ventas (`vendido.vendidas_netas`). Las regalías cuentan: también
  vacían el estante.
- **Venta por día**: vendidas ÷ días que el producto TUVO existencia en el
  rango. Los días agotados no cuentan (salen de los avisos `Agotamiento`), ni
  los días antes de que el producto existiera. Sin esto, el producto que más
  faltó salía con el promedio más bajo justo cuando más había que pedirlo.
  Piso de PISO_DIAS días: tres ventas en una mañana antes de agotarse no son
  «tres por día».
- **Rango corto**: con menos de DIAS_MINIMOS días (hoy, ayer, esta semana un
  martes) la venta por día no sirve para pedir. Ahí el «Pedir» se calcula con
  los últimos DIAS_BASE días y la pantalla lo dice.
- **Alcanza**: días de venta que cubre lo que queda hoy.
- **Cuándo llega**: si se pide hoy, el día que entrega el proveedor
  (`compras.entregas.llegada`, con los días que se anotan en
  `compras:proveedores`). Sin esos datos no se sabe.
- **Pedir**: lo necesario para tener `cubrir` días de venta (15, 30 o 45)
  DESPUÉS de que llegue el pedido —lo que se vende mientras viene en camino
  también se pide—, redondeado hacia arriba a unidades enteras. Cero si no se vendió nada
  —lo que no se vende no se repone— o si decidieron «No comprar más».
- **Costo**: lo que cuesta reponer UNA unidad pagada en la última compra
  (`catalogo.costos`); sin compras, el costo promedio.
- **Estado**: Agotado (cero o menos) · Quedan pocas (en o bajo el mínimo, o
  se acaba antes de que llegue un pedido hecho hoy; si no se sabe cuándo
  llega, POCOS_DIAS días) · Hay.
- **No se vende** (`dormidos`): con existencia y sin una sola venta en el
  rango; valor a costo promedio.

Límite conocido: el producto estacional. Si se vendieron 40 en diciembre, el
«Pedir» de enero con «Últimos 30 días» va a salir alto. Por eso al lado del
número están las vendidas y las fechas usadas.
"""
import math
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO

from django.db.models import Count, Q
from django.utils import timezone

from compras.entregas import llegada

from .agotados import _ultima_compra, codigo_proveedor
from .models import Agotamiento
from .vendido import ATAJOS, normalizar, rango_de_atajo, vendidas_netas

VISTAS = {
    "pedir": "Para pedir",
    "vendido": "Todo lo vendido",
    "agotados": "Agotados",
    "historial": "Ya repuestos",
    "dormido": "No se vende",
}
COBERTURAS = (15, 30, 45)
COBERTURA = 30          # una compra al mes
DIAS_MINIMOS = 7
DIAS_BASE = 30
PISO_DIAS = 7
POCOS_DIAS = 7
ATAJO_INICIAL = "30"

AGOTADO, POCAS, HAY = "agotado", "pocas", "hay"
ESTADOS = {AGOTADO: "Agotado", POCAS: "Quedan pocas", HAY: "Hay"}
_ORDEN = {AGOTADO: 0, POCAS: 1, HAY: 2}


def leer_rango(get):
    """(desde, hasta, atajo) desde los parámetros de la pantalla."""
    atajo = get.get("atajo", "")
    rango = rango_de_atajo(atajo)
    if rango:
        return rango[0], rango[1], atajo

    def fecha(valor):
        try:
            return datetime.strptime(valor or "", "%Y-%m-%d").date()
        except ValueError:
            return None

    desde, hasta = fecha(get.get("desde")), fecha(get.get("hasta"))
    if desde is None and hasta is None:
        d, h = rango_de_atajo(ATAJO_INICIAL)
        return d, h, ATAJO_INICIAL
    desde, hasta = normalizar(desde, hasta)
    return desde, hasta, ""


def leer_cubrir(get):
    try:
        n = int(get.get("cubrir", COBERTURA))
    except (TypeError, ValueError):
        n = COBERTURA
    return n if n in COBERTURAS else COBERTURA


def _inicio(fecha):
    return timezone.make_aware(datetime.combine(fecha, time.min))


def _dias_con_existencia(productos, desde, hasta):
    """{producto_id: días (float) que tuvo existencia entre desde y hasta}."""
    # Días enteros, hoy incluido (como «Últimos 30 días» = hoy y los 29 de
    # antes). Un agotado abierto cuenta hasta el final de hoy.
    ini = _inicio(desde)
    fin = _inicio(hasta + timedelta(days=1))
    total = float((hasta - desde).days + 1)
    afuera = defaultdict(float)
    ids = [p.pk for p in productos]
    for a in Agotamiento.objects.filter(producto_id__in=ids, fecha__lt=fin).filter(
            Q(repuesto_en__isnull=True) | Q(repuesto_en__gt=ini)).only("producto_id", "fecha", "repuesto_en"):
        tramo = (min(a.repuesto_en or fin, fin) - max(a.fecha, ini)).total_seconds() / 86400
        afuera[a.producto_id] += max(tramo, 0)
    salida = {}
    for p in productos:
        dias = total
        if p.creado_en and p.creado_en > ini:            # el producto no existía
            dias = max((fin - p.creado_en).total_seconds() / 86400, 0)
        salida[p.pk] = max(dias - afuera[p.pk], min(PISO_DIAS, total))
    return salida


def datos(empresa, desde, hasta, ver="pedir", proveedor="", cubrir=COBERTURA):
    """Todo lo de la pantalla y el Excel. Una sola función a propósito."""
    from catalogo.costos import reposiciones, ultimas_lineas_pagadas
    from catalogo.models import Producto

    ver = ver if ver in VISTAS else "pedir"
    if ver == "dormido":
        return dormidos(empresa, desde, hasta, proveedor, cubrir)
    dias_rango = (hasta - desde).days + 1
    vendidas = vendidas_netas(empresa, desde, hasta)
    if dias_rango >= DIAS_MINIMOS:
        base_desde, base_hasta, base = desde, hasta, vendidas
    else:
        base_hasta = timezone.localdate()
        base_desde = base_hasta - timedelta(days=DIAS_BASE - 1)
        base = vendidas_netas(empresa, base_desde, base_hasta)

    # Qué avisos de agotado entran según la vista.
    avisos = Agotamiento.objects.filter(producto__empresa=empresa).select_related("decidido_por", "movimiento")
    if ver == "historial":
        avisos = avisos.filter(repuesto_en__isnull=False, repuesto_en__date__gte=desde,
                               repuesto_en__date__lte=hasta).order_by("-repuesto_en", "-id")
    else:
        avisos = avisos.filter(repuesto_en__isnull=True).order_by("-fecha", "-id")
    aviso_de = {}
    for a in avisos:
        aviso_de.setdefault(a.producto_id, a)

    if ver in ("agotados", "historial"):
        ids = set(aviso_de)
    elif ver == "vendido":
        ids = set(vendidas)
    else:   # pedir: lo vendido más los agotados abiertos que no descartaron
        ids = set(vendidas) | {pid for pid, a in aviso_de.items() if a.decision != Agotamiento.Decision.NO_COMPRAR}

    productos = list(Producto.objects.filter(empresa=empresa, pk__in=ids).select_related("categoria", "empresa"))
    costos = reposiciones(productos) if productos else {}
    pagadas = ultimas_lineas_pagadas([p.pk for p in productos])
    cualquiera = _ultima_compra([p.pk for p in productos if p.pk not in pagadas])
    dias = _dias_con_existencia(productos, base_desde, base_hasta)
    # Unidades sueltas de una caja abierta: al proveedor se le pide la caja.
    cajas = {}
    for caja in Producto.objects.filter(empresa=empresa, unidad_suelta_id__in=[p.pk for p in productos],
                                        unidades_por_empaque__gt=0).order_by("id"):
        cajas.setdefault(caja.unidad_suelta_id, caja)
    veces = dict(Agotamiento.objects.filter(producto_id__in=[p.pk for p in productos])
                 .values_list("producto_id").annotate(n=Count("id")))
    hoy = timezone.localdate()
    ahora = timezone.localtime()
    llegadas = {}       # proveedor_id → fecha en que llega un pedido de hoy
    elegido = None

    filas, proveedores = [], set()
    for p in productos:
        linea = pagadas.get(p.pk) or cualquiera.get(p.pk)
        prov = linea.compra.proveedor if linea else None
        nombre_prov = prov.nombre if prov else ""
        if prov is not None and prov.pk not in llegadas:
            llegadas[prov.pk] = llegada(prov, ahora)
        llega = llegadas.get(prov.pk) if prov else None
        dias_llegada = (llega - hoy).days if llega else None
        if nombre_prov:
            proveedores.add(nombre_prov)
        if proveedor and nombre_prov != proveedor:
            continue
        if proveedor:
            elegido = prov
        aviso = aviso_de.get(p.pk)
        descartado = aviso is not None and aviso.decision == Agotamiento.Decision.NO_COMPRAR
        stock = p.stock_actual
        diaria = Decimal(str(base.get(p.pk, 0))) / Decimal(str(dias[p.pk])) if base.get(p.pk) else Decimal("0")
        alcanza = (stock / diaria) if diaria > 0 and stock > 0 else (Decimal("0") if diaria > 0 else None)
        if descartado or diaria <= 0:
            pedir = 0
        else:
            # Lo que se vende mientras el pedido viene en camino también hay
            # que pedirlo: si no, llega y alcanza para menos de lo elegido.
            pedir = max(math.ceil(diaria * (cubrir + (dias_llegada or 0)) - stock), 0)
        umbral = dias_llegada if dias_llegada is not None else POCOS_DIAS
        if stock <= 0:
            estado = AGOTADO
        elif stock <= p.stock_minimo or (alcanza is not None and alcanza <= umbral):
            estado = POCAS
        else:
            estado = HAY
        if ver == "pedir" and not (pedir > 0 or (estado != HAY and not descartado)):
            continue
        costo = costos.get(p.pk) or p.costo_promedio or None
        caja = cajas.get(p.pk)
        filas.append({
            "producto": p,
            "codigo_proveedor": codigo_proveedor(p.sku),
            "proveedor": nombre_prov,
            "proveedor_id": prov.pk if prov else None,
            "llega": llega,
            "dias_llegada": dias_llegada,
            "ultima_factura": (linea.compra.factura_proveedor or linea.compra.numero) if linea else "",
            "vendidas": vendidas.get(p.pk, Decimal("0")),
            "quedan": stock,
            "diaria": diaria,
            "alcanza": int(alcanza) if alcanza is not None else None,
            "pedir": pedir,
            "costo": costo,
            "subtotal": (costo * pedir) if costo and pedir else Decimal("0"),
            "estado": estado,
            "estado_texto": ESTADOS[estado],
            "aviso": aviso,
            "descartado": descartado,
            "veces": veces.get(p.pk, 0),
            "caja": caja,
            "cajas": math.ceil(pedir / caja.unidades_por_empaque) if caja and pedir else 0,
            "dias_agotado": (hoy - timezone.localtime(aviso.fecha).date()).days if aviso and not aviso.repuesto_en else None,
        })
    filas.sort(key=lambda f: (_ORDEN[f["estado"]], -f["pedir"], -f["vendidas"], f["producto"].nombre))
    if ver == "agotados":   # primero los que esperan decisión
        filas.sort(key=lambda f: f["aviso"].decision != Agotamiento.Decision.PENDIENTE)
    return {
        "filas": filas,
        "ver": ver,
        "desde": desde, "hasta": hasta, "dias_rango": dias_rango,
        "base_desde": base_desde, "base_hasta": base_hasta, "base_distinta": base is not vendidas,
        "cubrir": cubrir,
        "proveedor": proveedor,
        "proveedor_ficha": elegido,
        "proveedor_llega": llegadas.get(elegido.pk) if elegido else None,
        "proveedores": sorted(proveedores),
        "resumen": {
            "productos": len(filas),
            "vendidas": sum((f["vendidas"] for f in filas), Decimal("0")),
            "agotados": sum(1 for f in filas if f["estado"] == AGOTADO),
            "pocas": sum(1 for f in filas if f["estado"] == POCAS),
            "a_pedir": sum(1 for f in filas if f["pedir"]),
            "unidades_pedir": sum(f["pedir"] for f in filas),
            "total": sum((f["subtotal"] for f in filas), Decimal("0")),
        },
    }


def dormidos(empresa, desde, hasta, proveedor="", cubrir=COBERTURA):
    """«No se vende»: lo que tiene existencia y no se vendió ni una unidad en
    el rango. Ahí está la plata parada (05/11/2026: 598 de 751 productos sin
    venderse). Valor = existencia × costo promedio, que es lo que de verdad
    costó lo que está en bodega. No entra lo que llegó o se creó dentro del
    rango: todavía no tuvo tiempo de venderse."""
    from django.db.models import Max

    from catalogo.models import Producto
    from ventas.models import LineaVenta

    vendidas = vendidas_netas(empresa, desde, hasta)
    ini = _inicio(desde)
    candidatos = list(Producto.objects.filter(empresa=empresa, activo=True, stock_actual__gt=0, creado_en__lt=ini)
                      .exclude(pk__in=list(vendidas)).select_related("categoria"))
    ids = [p.pk for p in candidatos]
    compras = _ultima_compra(ids)
    ultima_venta = dict(LineaVenta.objects.filter(producto_id__in=ids, factura__empresa=empresa, factura__estado="EMI")
                        .values_list("producto_id").annotate(u=Max("factura__creado_en")))
    hoy = timezone.localdate()
    filas, proveedores = [], set()
    for p in candidatos:
        linea = compras.get(p.pk)
        llegada_compra = linea.compra.recibida_en if linea else None
        if llegada_compra and llegada_compra >= ini:
            continue
        nombre_prov = linea.compra.proveedor.nombre if linea else ""
        if nombre_prov:
            proveedores.add(nombre_prov)
        if proveedor and nombre_prov != proveedor:
            continue
        uv = ultima_venta.get(p.pk)
        desde_cuando = timezone.localtime(uv or llegada_compra or p.creado_en).date()
        costo = p.costo_promedio or Decimal("0")
        filas.append({
            "producto": p,
            "codigo_proveedor": codigo_proveedor(p.sku),
            "proveedor": nombre_prov,
            "proveedor_id": linea.compra.proveedor_id if linea else None,
            "quedan": p.stock_actual,
            "costo": costo,
            "valor": (costo * p.stock_actual).quantize(Decimal("1")),
            "ultima_venta": timezone.localtime(uv).date() if uv else None,
            "ultima_compra": timezone.localtime(llegada_compra).date() if llegada_compra else None,
            "dias_sin_vender": (hoy - desde_cuando).days,
        })
    filas.sort(key=lambda f: (-f["valor"], f["producto"].nombre))
    return {
        "filas": filas, "ver": "dormido",
        "desde": desde, "hasta": hasta, "dias_rango": (hasta - desde).days + 1,
        "base_desde": desde, "base_hasta": hasta, "base_distinta": False,
        "cubrir": cubrir, "proveedor": proveedor, "proveedor_ficha": None, "proveedor_llega": None,
        "proveedores": sorted(proveedores),
        "resumen": {
            "productos": len(filas),
            "unidades": sum((f["quedan"] for f in filas), Decimal("0")),
            "valor": sum((f["valor"] for f in filas), Decimal("0")),
            "nunca": sum(1 for f in filas if f["ultima_venta"] is None),
        },
    }


# ---------------------------------------------------------------- Excel ----

COLUMNAS = [
    ("Código proveedor", 15), ("Código de barras", 16), ("Producto", 44), ("Marca", 14),
    ("Vendidas", 9), ("Quedan hoy", 9), ("Alcanza (días)", 9), ("Estado", 13),
    ("Pedir", 9), ("Costo ₡", 12), ("Subtotal ₡", 13), ("Nota", 28),
]
_INVALIDOS = str.maketrans({c: " " for c in '[]:*?/\\'})


def _nombre_hoja(nombre, usados):
    base = (nombre or "Sin proveedor").translate(_INVALIDOS).strip()[:28] or "Sin proveedor"
    nombre, n = base, 2
    while nombre.lower() in usados:
        nombre, n = f"{base[:26]} {n}", n + 1
    usados.add(nombre.lower())
    return nombre


def excel(empresa, desde, hasta, ver="pedir", proveedor="", cubrir=COBERTURA):
    """Una hoja «Resumen» y una hoja por proveedor, lista para mandar el
    pedido. «Pedir» viene con la sugerencia y se puede cambiar: el subtotal y
    los totales son fórmulas y se recalculan solos."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    d = datos(empresa, desde, hasta, ver, proveedor, cubrir)
    if d["ver"] == "dormido":
        return _excel_dormidos(d)
    azul = PatternFill("solid", fgColor="0B3161")
    amarillo = PatternFill("solid", fgColor="FFF4C2")
    gris = Font(color="6E6E73", size=10)
    linea = Border(top=Side(style="thin", color="0B3161"))
    periodo = f"Vendido del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
    regla = f"«Pedir» alcanza para {cubrir} días de venta"
    if d["base_distinta"]:
        regla += f" (calculado con lo vendido del {d['base_desde']:%d/%m} al {d['base_hasta']:%d/%m})"
    regla += ". Cambiá la columna amarilla; los totales se recalculan."

    from compras.models import Proveedor

    fichas = {p.pk: p for p in Proveedor.objects.filter(
        pk__in={f["proveedor_id"] for f in d["filas"] if f["proveedor_id"]})}
    grupos = defaultdict(list)
    for f in d["filas"]:
        grupos[f["proveedor"] or ""].append(f)
    orden = sorted(grupos, key=lambda n: (n == "", n.lower()))

    wb = Workbook()
    res = wb.active
    res.title = "Resumen"
    res.append([f"{VISTAS[d['ver']]} — {periodo}"])
    res["A1"].font = Font(bold=True, size=13)
    res.append([regla])
    res["A2"].font = gris
    res.append([])
    res.append(["Proveedor", "Productos", "Unidades a pedir", "Total ₡"])
    for i, ancho in enumerate((34, 11, 16, 16), start=1):
        c = res.cell(row=4, column=i)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), azul
        res.column_dimensions[get_column_letter(i)].width = ancho

    usados = {"resumen"}
    primera_fila = 5
    for nombre in orden:
        filas = grupos[nombre]
        ws = wb.create_sheet(_nombre_hoja(nombre, usados))
        ws.append([nombre or "Sin proveedor (nunca se le ha comprado)"])
        ws["A1"].font = Font(bold=True, size=13)
        prov = fichas.get(filas[0]["proveedor_id"])
        datos_prov = []
        if prov is not None:
            datos_prov = [x for x in (prov.contacto, prov.telefono, prov.email) if x]
            if filas[0]["llega"]:
                datos_prov.append(f"Si se pide hoy llega el {_dia_y_fecha(filas[0]['llega'])}")
            elif prov.horario_entrega:
                datos_prov.append(prov.horario_entrega)
        ws.append([f"{periodo}. {regla}" + (f"  ·  {' · '.join(datos_prov)}" if datos_prov else "")])
        ws["A2"].font = gris
        ws.append([])
        ws.append([t for t, _ in COLUMNAS])
        for i, (_, ancho) in enumerate(COLUMNAS, start=1):
            c = ws.cell(row=4, column=i)
            c.font, c.fill = Font(bold=True, color="FFFFFF"), azul
            c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.column_dimensions[get_column_letter(i)].width = ancho
        for f in filas:
            p, a = f["producto"], f["aviso"]
            nota = []
            if f["descartado"]:
                nota.append("Decidieron no comprar más")
            elif a and a.decision == Agotamiento.Decision.PEDIR:
                nota.append("Decidieron volver a pedir")
            if a and a.nota:
                nota.append(a.nota)
            if f["caja"]:
                nota.append(f"Se pide por caja de {f['caja'].unidades_por_empaque:g}: {f['caja'].nombre}")
            ws.append([
                f["codigo_proveedor"], p.codigo_barras, p.nombre, p.marca,
                float(f["vendidas"]), float(f["quedan"]), f["alcanza"], f["estado_texto"],
                f["pedir"], float(f["costo"]) if f["costo"] else None, None, " · ".join(nota),
            ])
            r = ws.max_row
            ws.cell(row=r, column=9).fill = amarillo
            ws.cell(row=r, column=11).value = f"=IF(ISNUMBER(J{r}),I{r}*J{r},0)"
            for col in (10, 11):
                ws.cell(row=r, column=col).number_format = "#,##0"
        fin = ws.max_row
        ws.append([None, None, "TOTAL", None, None, None, None, None, f"=SUM(I5:I{fin})", None, f"=SUM(K5:K{fin})"])
        t = ws.max_row
        for col in range(1, len(COLUMNAS) + 1):
            ws.cell(row=t, column=col).font = Font(bold=True)
            ws.cell(row=t, column=col).border = linea
        ws.cell(row=t, column=11).number_format = "#,##0"
        ws.freeze_panes = "A5"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
        hoja = ws.title.replace("'", "''")
        res.append([nombre or "Sin proveedor", len(filas), f"='{hoja}'!I{t}", f"='{hoja}'!K{t}"])
        res.cell(row=res.max_row, column=4).number_format = "#,##0"

    ult = res.max_row
    res.append(["TOTAL", f"=SUM(B{primera_fila}:B{ult})" if ult >= primera_fila else 0,
                f"=SUM(C{primera_fila}:C{ult})" if ult >= primera_fila else 0,
                f"=SUM(D{primera_fila}:D{ult})" if ult >= primera_fila else 0])
    for col in range(1, 5):
        res.cell(row=res.max_row, column=col).font = Font(bold=True)
        res.cell(row=res.max_row, column=col).border = linea
    res.cell(row=res.max_row, column=4).number_format = "#,##0"
    if not d["filas"]:
        res.append([])
        res.append(["No hay productos con estos filtros."])
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


_DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _dia_y_fecha(fecha):
    return f"{_DIAS_SEMANA[fecha.weekday()]} {fecha:%d/%m}"


def _excel_dormidos(d):
    """«No se vende»: una sola hoja, de lo que más plata tiene parada a lo
    que menos."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    columnas = [("Código proveedor", 15), ("Código de barras", 16), ("Producto", 44), ("Proveedor", 22),
                ("Quedan", 9), ("Costo ₡", 12), ("Valor ₡", 13), ("Última venta", 12),
                ("Última compra", 12), ("Días sin vender", 10)]
    wb = Workbook()
    ws = wb.active
    ws.title = "No se vende"
    ws.append([f"No se vendió del {d['desde']:%d/%m/%Y} al {d['hasta']:%d/%m/%Y}"
               + (f" — {d['proveedor']}" if d["proveedor"] else "")])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Con existencia y sin una sola venta en esas fechas. Valor = existencia × costo promedio."])
    ws["A2"].font = Font(color="6E6E73", size=10)
    ws.append([])
    ws.append([t for t, _ in columnas])
    for i, (_, ancho) in enumerate(columnas, start=1):
        c = ws.cell(row=4, column=i)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="0B3161")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = ancho
    for f in d["filas"]:
        p = f["producto"]
        ws.append([f["codigo_proveedor"], p.codigo_barras, p.nombre, f["proveedor"], float(f["quedan"]),
                   float(f["costo"]), None, f["ultima_venta"] or "Nunca", f["ultima_compra"], f["dias_sin_vender"]])
        r = ws.max_row
        ws.cell(row=r, column=7).value = f"=E{r}*F{r}"
        for col in (6, 7):
            ws.cell(row=r, column=col).number_format = "#,##0"
        for col in (8, 9):
            ws.cell(row=r, column=col).number_format = "dd/mm/yyyy"
    fin = ws.max_row
    ws.append([None, None, "TOTAL", None, f"=SUM(E5:E{fin})" if fin >= 5 else 0, None,
               f"=SUM(G5:G{fin})" if fin >= 5 else 0])
    for col in range(1, len(columnas) + 1):
        ws.cell(row=ws.max_row, column=col).font = Font(bold=True)
        ws.cell(row=ws.max_row, column=col).border = Border(top=Side(style="thin", color="0B3161"))
    ws.cell(row=ws.max_row, column=7).number_format = "#,##0"
    ws.freeze_panes = "A5"
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()
