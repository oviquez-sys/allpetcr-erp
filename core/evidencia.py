"""Origen y evidencia de los indicadores del Inicio.

Por qué existe este módulo
--------------------------
Un tablero que muestra un número sin poder abrirlo enseña a desconfiar del
número. El caso concreto que lo motivó: el Inicio decía "ventas de hoy
₡184.350" y "efectivo en caja ₡96.410", y no había forma de saber si la
diferencia era normal (SINPE y tarjeta no pasan por la gaveta) o un faltante.
Ante la duda, la reacción sana es no creerle al tablero — y entonces el
tablero no sirve para decidir.

Cada función de acá devuelve tres cosas, siempre en el mismo orden:

1. `formula`: los sumandos que arman el número, en el orden en que se suman.
2. `filas`: los registros reales que lo componen. La suma de las filas tiene
   que dar el total; si no da, es un defecto, no un redondeo.
3. `excluye`: qué NO entra y por qué. Es la parte que más consultas evita.

Ninguna función escribe. Ninguna usa la caché del tablero: si el Inicio
muestra un valor cacheado (hasta 2 minutos) y el detalle lo recalcula, pueden
diferir por instantes. Por eso cada vista informa la hora del cálculo — es
preferible una diferencia explicada a una coincidencia forzada.
"""
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.utils import timezone


# --------------------------------------------------------------------------
#  1. Efectivo en caja
# --------------------------------------------------------------------------

def efectivo_en_caja(empresa):
    """Descompone el efectivo esperado de la sesión de caja abierta.

    El número del Inicio es `caja.services.monto_esperado()`, que suma los
    movimientos de la sesión. Acá se muestran esos mismos movimientos, uno por
    uno, agrupados por tipo. La suma de la columna es, por construcción, el
    mismo valor: no se recalcula por otro camino.
    """
    from caja.models import MovimientoCaja, SesionCaja
    from caja.services import monto_esperado
    from ventas.models import FacturaVenta

    sesion = (
        SesionCaja.objects
        .filter(sucursal__empresa=empresa, estado=SesionCaja.Estado.ABIERTA)
        .select_related("sucursal", "usuario")
        .first()
    )
    if sesion is None:
        return {"sesion": None, "total": Decimal("0"), "formula": [], "filas": [], "excluye": []}

    movimientos = (
        MovimientoCaja.objects
        .filter(sesion=sesion)
        .select_related("usuario")
        .order_by("fecha", "id")
    )

    # Un solo recorrido de la base para el desglose por tipo, en vez de una
    # consulta por cada línea de la fórmula.
    por_tipo = {
        f["tipo"]: f
        for f in movimientos.values("tipo").annotate(t=Sum("monto"), n=Count("id"))
    }

    def _bloque(tipo):
        d = por_tipo.get(tipo, {})
        return (d.get("t") or Decimal("0")), (d.get("n") or 0)

    apertura, _ = _bloque(MovimientoCaja.Tipo.APERTURA)
    ventas_efe, n_ventas = _bloque(MovimientoCaja.Tipo.VENTA)
    ingresos, n_ing = _bloque(MovimientoCaja.Tipo.INGRESO)
    egresos, n_egr = _bloque(MovimientoCaja.Tipo.EGRESO)
    anulaciones, n_anu = _bloque(MovimientoCaja.Tipo.ANULACION)

    formula = [
        {"signo": "=", "concepto": "Monto de apertura",
         "detalle": "Lo que se contó al abrir la caja", "monto": apertura},
        {"signo": "+", "concepto": "Ventas cobradas en efectivo",
         "detalle": f"{n_ventas} movimiento{'s' if n_ventas != 1 else ''} · solo medio Efectivo",
         "monto": ventas_efe},
        {"signo": "+", "concepto": "Ingresos manuales",
         "detalle": f"{n_ing} movimiento{'s' if n_ing != 1 else ''}", "monto": ingresos},
        {"signo": "−", "concepto": "Egresos manuales",
         "detalle": f"{n_egr} movimiento{'s' if n_egr != 1 else ''}", "monto": egresos},
        {"signo": "−", "concepto": "Devoluciones pagadas en efectivo",
         "detalle": f"{n_anu} movimiento{'s' if n_anu != 1 else ''}", "monto": anulaciones},
    ]

    # Cuánto se vendió hoy por medios que NO tocan la gaveta. Es el dato que
    # explica la diferencia entre "ventas de hoy" y "efectivo en caja", que es
    # la duda que trae a esta pantalla a casi todo el mundo.
    hoy = timezone.localdate()
    no_efectivo = (
        FacturaVenta.objects
        .filter(empresa=empresa, estado=FacturaVenta.Estado.EMITIDA, creado_en__date=hoy)
        .exclude(medio_pago=FacturaVenta.MedioPago.EFECTIVO)
        .values("medio_pago").annotate(t=Sum("total"))
    )
    etiquetas = dict(FacturaVenta.MedioPago.choices)
    excluye = [
        {"titulo": f"{etiquetas.get(f['medio_pago'], f['medio_pago'])}: ₡{f['t']:,.0f}".replace(",", "."),
         "detalle": "No entra a la gaveta: se cobra fuera del efectivo."}
        for f in no_efectivo
    ]
    excluye.append({
        "titulo": "El efectivo de sesiones anteriores",
        "detalle": "Cada sesión arranca de cero con su propio monto de apertura.",
    })

    return {
        "sesion": sesion,
        "total": monto_esperado(sesion),
        "formula": formula,
        "filas": movimientos,
        "excluye": excluye,
    }


# --------------------------------------------------------------------------
#  2. Ventas del día por medio de pago
# --------------------------------------------------------------------------

def ventas_por_medio(empresa, fecha=None):
    """Ventas del día abiertas por medio de pago, con el puente hacia el
    dinero realmente recibido.

    Son dos números distintos y confundirlos es un error contable, no de
    presentación:

    - Ventas del día: incluye el crédito, que es venta sin cobro.
    - Recibido en el día: excluye el crédito e incluye los abonos que entraron
      hoy contra créditos de días anteriores.

    Esta pantalla muestra los dos y la diferencia entre ambos.
    """
    from ventas.models import Abono, FacturaVenta

    fecha = fecha or timezone.localdate()
    facturas = (
        FacturaVenta.objects
        .filter(empresa=empresa, estado=FacturaVenta.Estado.EMITIDA, creado_en__date=fecha)
        .select_related("cliente", "usuario")
        .order_by("creado_en", "id")
    )

    agrupado = {
        f["medio_pago"]: f
        for f in facturas.values("medio_pago").annotate(t=Sum("total"), n=Count("id"))
    }
    formula = []
    total_ventas = Decimal("0")
    for codigo, etiqueta in FacturaVenta.MedioPago.choices:
        d = agrupado.get(codigo, {})
        monto = d.get("t") or Decimal("0")
        n = d.get("n") or 0
        total_ventas += monto
        formula.append({
            "signo": "+", "concepto": etiqueta, "codigo": codigo,
            "detalle": f"{n} tiquete{'s' if n != 1 else ''}", "monto": monto,
        })

    credito = next(
        (f["monto"] for f in formula if f["codigo"] == FacturaVenta.MedioPago.CREDITO),
        Decimal("0"),
    )
    abonos = (
        Abono.objects
        .filter(documento__cliente__empresa=empresa, fecha__date=fecha)
        .select_related("documento__factura", "documento__cliente", "usuario")
        .order_by("fecha", "id")
    )
    total_abonos = abonos.aggregate(t=Sum("monto"))["t"] or Decimal("0")

    puente = [
        {"signo": "=", "concepto": "Ventas del día", "detalle": "Todos los medios",
         "monto": total_ventas},
        {"signo": "−", "concepto": "Ventas a crédito",
         "detalle": "Se facturaron hoy, pero el dinero no entró", "monto": credito},
        {"signo": "+", "concepto": "Abonos cobrados hoy",
         "detalle": f"{abonos.count()} abono(s) a créditos anteriores", "monto": total_abonos},
    ]
    recibido = total_ventas - credito + total_abonos

    return {
        "fecha": fecha,
        "total_ventas": total_ventas,
        "recibido": recibido,
        "formula": formula,
        "puente": puente,
        "filas": facturas,
        "abonos": abonos,
        "excluye": [
            {"titulo": "Las facturas anuladas",
             "detalle": "Solo se cuentan las emitidas; una anulación revierte inventario y caja."},
            {"titulo": "Las devoluciones parciales",
             "detalle": "Ajustan la venta original, no aparecen como una línea aparte acá."},
        ],
    }


# --------------------------------------------------------------------------
#  3. Cuentas por cobrar
# --------------------------------------------------------------------------

def por_cobrar(empresa):
    """Documentos de crédito abiertos, con antigüedad, y el contraste entre
    los documentos y el campo `saldo` del cliente.

    El KPI del Inicio suma `Cliente.saldo`, que es un valor denormalizado. La
    fuente de verdad son los documentos. Acá se calculan los dos y se comparan:
    si no cuadran, el control de crédito está autorizando contra un número
    equivocado y hay que correr `manage.py reconciliar` antes de seguir dando
    fiado. Ese contraste es el motivo principal de esta pantalla.
    """
    from ventas.models import Cliente, DocumentoCxC

    hoy = timezone.localdate()
    documentos = (
        DocumentoCxC.objects
        .filter(cliente__empresa=empresa, estado=DocumentoCxC.Estado.PENDIENTE)
        .select_related("cliente", "factura")
        .annotate(abonado=F("monto_original") - F("saldo"))
        .order_by("creado_en", "id")
    )

    filas = []
    for d in documentos:
        dias = (hoy - timezone.localtime(d.creado_en).date()).days
        filas.append({"doc": d, "dias": dias, "vencido": dias > 30})

    total_documentos = documentos.aggregate(t=Sum("saldo"))["t"] or Decimal("0")
    total_original = documentos.aggregate(t=Sum("monto_original"))["t"] or Decimal("0")
    vencido = sum((f["doc"].saldo for f in filas if f["vencido"]), Decimal("0"))

    # El otro camino al mismo número: el denormalizado.
    total_denormalizado = (
        Cliente.objects.filter(empresa=empresa).aggregate(t=Sum("saldo"))["t"] or Decimal("0")
    )
    cuadra = total_documentos == total_denormalizado

    return {
        "filas": filas,
        "total": total_documentos,
        "total_original": total_original,
        "total_abonado": total_original - total_documentos,
        "total_denormalizado": total_denormalizado,
        "cuadra": cuadra,
        "diferencia": total_denormalizado - total_documentos,
        "vencido": vencido,
        "clientes": documentos.values("cliente_id").distinct().count(),
        "dias_mas_viejo": max((f["dias"] for f in filas), default=0),
        "excluye": [
            {"titulo": "Los documentos ya pagados",
             "detalle": "Solo se listan los que siguen en estado Pendiente."},
            {"titulo": "Las facturas anuladas",
             "detalle": "Al anular una venta a crédito su documento se cancela."},
            {"titulo": "Las ventas de contado",
             "detalle": "Efectivo, tarjeta y SINPE se cobran en el acto y no generan documento."},
        ],
    }
