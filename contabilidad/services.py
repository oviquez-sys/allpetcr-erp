"""Libro contable: servicio genérico de registro de asientos.

Reglas (Fase 1):
- Todo asiento debe cuadrar: suma de débitos = suma de créditos, o se rechaza.
- El asiento nace en la MISMA transacción que la operación que lo origina
  (se llama desde ventas dentro de su transacción atómica): si el asiento no
  se puede cuadrar, la operación entera se revierte. No hay documento sin
  asiento ni asiento sin documento.
- Los asientos no se editan ni se borran; para corregir se registra la reversa.

Este módulo NO conoce ventas ni caja: recibe cuentas y montos. Así el libro
queda desacoplado y reutilizable (compras, planilla, etc. en el futuro).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import Empresa

from .models import Asiento, CierrePeriodo, CuentaContable, LineaAsiento
from .plan_cuentas import CODIGOS, PLANTILLA


def fecha_bloqueo(empresa):
    """Fecha hasta la cual el período está cerrado (o None si no hay cierre
    vigente). Es la mayor fecha_cierre entre los cierres activos: todo asiento
    con fecha igual o anterior queda bloqueado."""
    c = (CierrePeriodo.objects
         .filter(empresa=empresa, activo=True)
         .order_by("-fecha_cierre")
         .first())
    return c.fecha_cierre if c else None


def periodo_cerrado(empresa, fecha) -> bool:
    fb = fecha_bloqueo(empresa)
    return fb is not None and fecha <= fb


@transaction.atomic
def cerrar_periodo(*, empresa, fecha_cierre, usuario=None, nota="") -> CierrePeriodo:
    """Cierra el período hasta fecha_cierre (inclusive). Solo debe llamarse
    desde una vista protegida para gerentes."""
    actual = fecha_bloqueo(empresa)
    if actual is not None and fecha_cierre <= actual:
        raise ValidationError(
            f"El período ya está cerrado hasta el {actual:%d/%m/%Y}. "
            f"Solo se puede cerrar hacia adelante (una fecha posterior)."
        )
    return CierrePeriodo.objects.create(
        empresa=empresa, fecha_cierre=fecha_cierre, nota=nota.strip(), cerrado_por=usuario,
    )


@transaction.atomic
def reabrir_periodo(*, cierre, usuario=None, motivo="") -> CierrePeriodo:
    """Reabre un cierre (para corregir un error real). Queda auditado."""
    from django.utils import timezone
    if not motivo or not motivo.strip():
        raise ValidationError("El motivo de la reapertura es obligatorio.")
    cierre = CierrePeriodo.objects.select_for_update().get(pk=cierre.pk)
    if not cierre.activo:
        raise ValidationError("Este cierre ya estaba reabierto.")
    cierre.activo = False
    cierre.reabierto_por = usuario
    cierre.reabierto_en = timezone.now()
    cierre.motivo_reapertura = motivo.strip()
    cierre.save(update_fields=["activo", "reabierto_por", "reabierto_en", "motivo_reapertura"])
    return cierre


def asegurar_plan(empresa: Empresa):
    """Crea la plantilla de cuentas de la empresa si aún no existe."""
    if CuentaContable.objects.filter(empresa=empresa).exists():
        return
    creadas = {}
    for codigo, nombre, naturaleza, mov in PLANTILLA:
        padre = None
        for largo in range(len(codigo) - 1, 0, -1):
            if codigo[:largo] in creadas:
                padre = creadas[codigo[:largo]]
                break
        creadas[codigo] = CuentaContable.objects.create(
            empresa=empresa, codigo=codigo, nombre=nombre,
            naturaleza=naturaleza, movimiento=mov, padre=padre,
        )


def cuenta(empresa: Empresa, logico: str) -> CuentaContable:
    """Devuelve una cuenta del motor por nombre lógico ('caja', 'ventas'…),
    creando el plan si hace falta. Si la empresa ya tenía un plan antiguo al
    que le falta esta cuenta (p. ej. cuentas nuevas como 'descuentos' o
    'gasto_regalias'), la crea al vuelo desde la plantilla."""
    asegurar_plan(empresa)
    codigo = CODIGOS[logico]
    try:
        return CuentaContable.objects.get(empresa=empresa, codigo=codigo)
    except CuentaContable.DoesNotExist:
        datos = next((fila for fila in PLANTILLA if fila[0] == codigo), None)
        if datos is None:
            raise
        _, nombre, naturaleza, mov = datos
        padre = None
        for largo in range(len(codigo) - 1, 0, -1):
            padre = CuentaContable.objects.filter(empresa=empresa, codigo=codigo[:largo]).first()
            if padre:
                break
        obj, _ = CuentaContable.objects.get_or_create(
            empresa=empresa, codigo=codigo,
            defaults={"nombre": nombre, "naturaleza": naturaleza, "movimiento": mov, "padre": padre},
        )
        return obj


def _siguiente_numero(empresa) -> str:
    """Número de asiento seguro ante concurrencia: consecutivo con bloqueo de
    fila (el mismo mecanismo de las facturas). Con count()+1, dos asientos
    simultáneos (en PostgreSQL/varios cajeros) podían recibir el mismo número y
    chocar contra la restricción de unicidad.

    Siembra inicial (auditoría 2026-07-28, hallazgo BE-05)
    ------------------------------------------------------
    La primera vez el contador se siembra a partir de los asientos que ya
    existen, para no colisionar con una numeración anterior.

    Antes esa siembra usaba `count()`: contaba filas y ponía el contador en
    "cantidad + 1". Eso es frágil por una razón concreta: si alguna vez
    faltara un asiento —hoy no debería, son inmutables, pero una restauración
    parcial o una migración de datos puede dejar huecos— el contador
    RETROCEDERÍA y el siguiente asiento chocaría contra la restricción de
    unicidad, justo en medio de una venta.

    Ahora se siembra con el número MÁS ALTO ya emitido, que es el dato que de
    verdad importa. Se extrae el entero del campo `numero` (formato
    "AS-00000123") y se sigue desde ahí. Con huecos en la secuencia el
    resultado sigue siendo correcto.
    """
    from ventas.models import Consecutivo

    with transaction.atomic():
        fila, creado = (Consecutivo.objects
                        .select_for_update()
                        .get_or_create(empresa=empresa, tipo="AS"))
        if creado or fila.siguiente <= 1:
            siguiente_seguro = _ultimo_numero_emitido(empresa) + 1
            if siguiente_seguro > fila.siguiente:
                fila.siguiente = siguiente_seguro
        numero = fila.siguiente
        fila.siguiente = numero + 1
        fila.save(update_fields=["siguiente"])
    return f"AS-{numero:08d}"


def _ultimo_numero_emitido(empresa) -> int:
    """Mayor número de asiento ya emitido para la empresa, como entero.

    Se ordena por el texto del campo `numero`: como el formato tiene ancho
    fijo con ceros a la izquierda ("AS-00000123"), el orden alfabético
    coincide con el numérico. Los valores que no siguen el formato se ignoran
    en vez de romper la numeración.
    """
    ultimo = (
        Asiento.objects.filter(empresa=empresa, numero__startswith="AS-")
        .order_by("-numero")
        .values_list("numero", flat=True)
        .first()
    )
    if not ultimo:
        return 0
    try:
        return int(ultimo.split("-", 1)[1])
    except (IndexError, ValueError):
        return 0


@transaction.atomic
def registrar_asiento(*, empresa, fecha, descripcion, origen, referencia="", lineas, usuario=None) -> Asiento:
    """lineas: lista de dicts {"cuenta": CuentaContable, "debe": D, "haber": D}."""
    # Guard de período cerrado: todo asiento pasa por aquí (ventas, compras,
    # costos, cobros, anulaciones), así que este único punto blinda la
    # contabilidad contra registros con fecha ya declarada.
    fb = fecha_bloqueo(empresa)
    if fb is not None and fecha <= fb:
        raise ValidationError(
            f"El período contable está cerrado hasta el {fb:%d/%m/%Y}. "
            f"No se puede registrar nada con fecha {fecha:%d/%m/%Y}. "
            f"Si de verdad hay que corregir, pedile a un gerente que reabra el período."
        )

    total_debe = sum((Decimal(str(l.get("debe", 0))) for l in lineas), Decimal("0"))
    total_haber = sum((Decimal(str(l.get("haber", 0))) for l in lineas), Decimal("0"))
    if total_debe != total_haber:
        raise ValidationError(
            f"Asiento descuadrado: debe {total_debe} ≠ haber {total_haber}."
        )
    if total_debe == 0:
        raise ValidationError("El asiento no tiene montos.")

    asiento = Asiento.objects.create(
        empresa=empresa, numero=_siguiente_numero(empresa), fecha=fecha,
        descripcion=descripcion, origen=origen, referencia=referencia, usuario=usuario,
    )
    for l in lineas:
        debe = Decimal(str(l.get("debe", 0)))
        haber = Decimal(str(l.get("haber", 0)))
        if debe == 0 and haber == 0:
            continue  # línea vacía: se omite
        LineaAsiento.objects.create(
            asiento=asiento, cuenta=l["cuenta"],
            debe=debe, haber=haber, detalle=l.get("detalle", ""),
        )
    return asiento
