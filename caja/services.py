"""Servicios de dominio de caja: apertura, movimientos y cierre con arqueo."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import MovimientoCaja, SesionCaja


def sesion_abierta_de(usuario):
    """La caja en la que vende este usuario.

    Caja compartida (auditoría 26/09/2026, CAJ-03): en la tienda hay UN cajón
    de dinero. Si Oscar abrió caja y Francisco vende, antes Francisco tenía
    que abrir otra sesión sobre el mismo cajón y ninguno de los dos arqueos
    cuadraba nunca. Ahora, si el usuario no tiene caja propia, vende en la que
    está abierta; cada venta y cada movimiento siguen firmados por quien los
    hizo. Con CAJA_COMPARTIDA=0 vuelve el esquema de una caja por persona."""
    propia = SesionCaja.objects.filter(usuario=usuario, estado=SesionCaja.Estado.ABIERTA).first()
    if propia is not None or not getattr(settings, "CAJA_COMPARTIDA", True):
        return propia
    return (SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA)
            .select_related("usuario").order_by("-abierta_en").first())


@transaction.atomic
def abrir_caja(*, sucursal, usuario, monto_apertura) -> SesionCaja:
    monto_apertura = Decimal(monto_apertura)
    if monto_apertura < 0:
        raise ValidationError("El monto de apertura no puede ser negativo.")
    abierta = sesion_abierta_de(usuario)
    if abierta:
        if abierta.usuario_id == getattr(usuario, "pk", None):
            raise ValidationError("Ya tiene una caja abierta. Ciérrela antes de abrir otra.")
        raise ValidationError(f"Ya hay una caja abierta (la abrió {abierta.usuario.username}): "
                              "se vende en esa misma. Para abrir otra, primero hay que cerrarla.")
    sesion = SesionCaja.objects.create(
        sucursal=sucursal, usuario=usuario, monto_apertura=monto_apertura
    )
    # Abrir con ₡0 es válido; en ese caso no se crea un movimiento nulo
    # (viola el CHECK de monto distinto de cero y no aporta al esperado).
    if monto_apertura > 0:
        MovimientoCaja.objects.create(
            sesion=sesion, tipo=MovimientoCaja.Tipo.APERTURA, monto=monto_apertura,
            descripcion="Apertura de caja", usuario=usuario,
        )
    return sesion


@transaction.atomic
def registrar_movimiento_caja(*, sesion, tipo, monto, descripcion="", referencia="", usuario=None) -> MovimientoCaja:
    monto = Decimal(monto)
    if sesion.estado != SesionCaja.Estado.ABIERTA:
        raise ValidationError("La sesión de caja está cerrada: no admite movimientos.")
    if monto == 0:
        raise ValidationError("El monto no puede ser cero.")
    return MovimientoCaja.objects.create(
        sesion=sesion, tipo=tipo, monto=monto,
        descripcion=descripcion, referencia=referencia, usuario=usuario,
    )


def monto_esperado(sesion) -> Decimal:
    total = sesion.movimientos.aggregate(t=Sum("monto"))["t"]
    return total if total is not None else Decimal("0")


def esperado_por_medio(sesion, hasta=None) -> dict:
    """Lo que tendría que haber entrado por tarjeta y por SINPE durante la
    sesión: lo vendido (pagos mixtos repartidos) más los abonos de fiado
    cobrados por esos medios. Es lo que el cierre del datáfono y el estado de
    SINPE tendrían que mostrar (CAJ-02).

    Los abonos (02/11/2026): un cliente que paga su fiado por SINPE mete plata
    en el SINPE de la tienda sin que haya una venta ese día. Sin sumarlos, el
    arqueo marcaba un sobrante que no era tal. El abono no guarda la caja, así
    que se toman los de la empresa cobrados mientras esta caja estuvo abierta
    (hay UNA caja compartida por tienda, CAJ-03).

    Lo que NO entra: el reembolso por datáfono de una devolución. Se hace
    aparte en el datáfono y no siempre cae el mismo día; si pasa, se explica
    en la diferencia."""
    from ventas.models import Abono, FacturaVenta
    from ventas.pagos import por_medio

    medios = por_medio(sesion.ventas.filter(estado=FacturaVenta.Estado.EMITIDA))
    resultado = {m: (medios.get(m, {}).get("t") or Decimal("0")) for m in ("TAR", "SIN")}
    abonos = (Abono.objects.filter(documento__factura__empresa_id=sesion.sucursal.empresa_id,
                                   medio__in=["TAR", "SIN"], fecha__gte=sesion.abierta_en,
                                   fecha__lte=hasta or sesion.cerrada_en or timezone.now())
              .order_by().values("medio").annotate(t=Sum("monto")))
    for fila in abonos:
        resultado[fila["medio"]] += fila["t"] or Decimal("0")
    return resultado


# Cuánto puede no calzar un medio sin pedir explicación. Cero por defecto:
# "todo debe calzar" (Oscar, 02/11/2026). Para los céntimos del vuelto está
# el redondeo del POS, que deja el total en un monto que se puede pagar.
def tolerancia() -> Decimal:
    return Decimal(str(getattr(settings, "CIERRE_TOLERANCIA", 0) or 0))


NOMBRES_MEDIO = {"EFE": "Efectivo", "TAR": "Tarjeta", "SIN": "SINPE Móvil"}


def calcular_arqueo(sesion, *, efectivo, tarjeta=None, sinpe=None) -> list:
    """Lo esperado contra lo contado, medio por medio, SIN guardar nada.

    Se usa antes de cerrar para mostrarle a quien cierra qué no calzó y
    pedirle la explicación. Un medio con lo contado vacío (None) no se
    revisó y no aparece. Cada fila: medio, nombre, esperado, contado,
    diferencia (contado − esperado) y si `calza` dentro de la tolerancia."""
    esperado = esperado_por_medio(sesion)
    filas = [("EFE", monto_esperado(sesion), efectivo), ("TAR", esperado["TAR"], tarjeta),
             ("SIN", esperado["SIN"], sinpe)]
    margen = tolerancia()
    resultado = []
    for medio, esp, contado in filas:
        if contado in (None, ""):
            continue
        contado = Decimal(contado)
        dif = contado - esp
        resultado.append({"medio": medio, "nombre": NOMBRES_MEDIO[medio], "esperado": esp,
                          "contado": contado, "diferencia": dif, "calza": abs(dif) <= margen})
    return resultado


def sugerir_cruce(filas) -> dict:
    """Si exactamente dos medios no calzan y se compensan (a uno le falta lo
    que al otro le sobra), casi seguro es una venta cobrada por otro medio:
    "iba a pagar con tarjeta y al final hizo un SINPE". Devuelve
    {medio: texto sugerido} para prellenar la explicación; {} si no aplica.

    Es solo una sugerencia: quien cierra la confirma o la cambia."""
    malas = [f for f in filas if not f["calza"]]
    if len(malas) != 2 or malas[0]["diferencia"] + malas[1]["diferencia"] != 0:
        return {}
    falta = next(f for f in malas if f["diferencia"] < 0)
    sobra = next(f for f in malas if f["diferencia"] > 0)
    monto = f"₡{abs(falta['diferencia']):,.0f}".replace(",", ".")
    texto = (f"Una venta de {monto} se registró como {falta['nombre']} "
             f"pero se cobró por {sobra['nombre']}.")
    return {falta["medio"]: texto, sobra["medio"]: texto}


@transaction.atomic
def cerrar_caja(*, sesion, monto_contado=None, usuario=None, tarjeta_contado=None, sinpe_contado=None,
                conteo=None, justificaciones=None, conteos_previos=None) -> SesionCaja:
    """Arqueo: se registra lo contado físicamente y se calcula la diferencia
    contra lo esperado. La sesión queda inmutable.

    tarjeta_contado / sinpe_contado (CAJ-02): lo que dice el cierre del
    datáfono y lo que de verdad entró por SINPE. Opcionales: vacío = no se
    revisó, que no es lo mismo que cero.

    conteo: {"20000": 2, "500": 6, ...}. Si viene, el efectivo contado es su
    suma y queda guardado el desglose.

    justificaciones (02/11/2026): {medio: (motivo, explicación)}. Si viene
    (la pantalla de cierre siempre la manda), TODO medio que no calce tiene
    que traer su explicación o el cierre no se hace. Lo que no calzó queda
    en `DiferenciaCaja`, se haya explicado o no, y se avisa por correo.

    conteos_previos: los conteos que se hicieron antes del definitivo (quien
    cierra vio la diferencia y volvió a contar). Se guardan tal cual."""
    sesion = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
    if sesion.estado != SesionCaja.Estado.ABIERTA:
        raise ValidationError("La sesión ya está cerrada.")
    if conteo is not None:
        # Conteo por billete y moneda (14/10/2026): el total lo calcula el
        # servidor, no se confía en el que mostró el navegador.
        from .denominaciones import TODAS, total
        limpio = {}
        for valor, cantidad in conteo.items():
            if int(valor) not in TODAS:
                raise ValidationError(f"₡{valor} no es un billete ni una moneda vigente.")
            if int(cantidad) < 0:
                raise ValidationError("La cantidad de billetes o monedas no puede ser negativa.")
            if int(cantidad):
                limpio[str(int(valor))] = int(cantidad)
        sesion.conteo_efectivo = limpio
        monto_contado = total(limpio)
    if monto_contado is None:
        raise ValidationError("Falta el efectivo contado.")
    monto_contado = Decimal(monto_contado)
    if monto_contado < 0:
        raise ValidationError("El monto contado no puede ser negativo.")
    sesion.monto_esperado = monto_esperado(sesion)
    esperado = esperado_por_medio(sesion)
    sesion.tarjeta_esperado, sesion.sinpe_esperado = esperado["TAR"], esperado["SIN"]
    for campo, valor in (("tarjeta_contado", tarjeta_contado), ("sinpe_contado", sinpe_contado)):
        if valor not in (None, ""):
            valor = Decimal(valor)
            if valor < 0:
                raise ValidationError("Los montos del cierre no pueden ser negativos.")
            setattr(sesion, campo, valor)
    sesion.cerrada_por = usuario if getattr(usuario, "pk", None) else None
    sesion.monto_contado = monto_contado
    sesion.diferencia = monto_contado - sesion.monto_esperado
    sesion.estado = SesionCaja.Estado.CERRADA
    sesion.cerrada_en = timezone.now()
    if conteos_previos:
        sesion.conteos_previos = list(conteos_previos)

    # Qué no calzó, medio por medio (02/11/2026).
    from .models import DiferenciaCaja
    margen = tolerancia()
    malas = [(m, esp, cont) for m, esp, cont in (
        ("EFE", sesion.monto_esperado, sesion.monto_contado),
        ("TAR", sesion.tarjeta_esperado, sesion.tarjeta_contado),
        ("SIN", sesion.sinpe_esperado, sesion.sinpe_contado),
    ) if cont is not None and abs(cont - esp) > margen]
    justificaciones = None if justificaciones is None else dict(justificaciones)
    filas = []
    for medio, esp, cont in malas:
        motivo, explicacion = (justificaciones or {}).get(medio) or ("", "")
        motivo, explicacion = (motivo or "").strip(), (explicacion or "").strip()
        if justificaciones is not None and not (motivo and explicacion):
            raise ValidationError(f"{NOMBRES_MEDIO[medio]} no calza: falta explicar la diferencia.")
        if motivo and motivo not in DiferenciaCaja.Motivo.values:
            raise ValidationError("Ese motivo no existe.")
        filas.append(DiferenciaCaja(sesion=sesion, medio=medio, esperado=esp, contado=cont,
                                    diferencia=cont - esp, motivo=motivo, explicacion=explicacion[:300]))
    sesion.save()
    DiferenciaCaja.objects.bulk_create(filas)
    if filas:
        # El correo sale DESPUÉS de confirmar el cierre: si la base revierte,
        # no se avisa de un cierre que no existe; si el correo falla, el
        # cierre igual queda hecho (ver avisos.py).
        from .avisos import avisar_diferencia
        transaction.on_commit(lambda: avisar_diferencia(sesion.pk))
    return sesion


def ultimo_cierre(empresa, antes_de=None):
    """La última caja cerrada de la empresa (17/10/2026, pedido de Oscar: al
    abrir, ver cómo se cerró la noche anterior). `antes_de` limita a las
    cerradas antes de esa fecha (para el cierre: la anterior a esta caja)."""
    qs = SesionCaja.objects.filter(estado=SesionCaja.Estado.CERRADA, sucursal__empresa=empresa)
    if antes_de is not None:
        qs = qs.filter(cerrada_en__lte=antes_de)
    return qs.select_related("usuario", "cerrada_por", "sucursal").order_by("-cerrada_en").first()


def resumen_ventas(sesion):
    """Cuántas ventas tuvo la caja, por cuánto, y cuánto se redondeó."""
    from django.db.models import Count
    from ventas.models import FacturaVenta

    r = sesion.ventas.filter(estado=FacturaVenta.Estado.EMITIDA).aggregate(
        n=Count("id"), total=Sum("total"), redondeo=Sum("redondeo"))
    return {"n": r["n"] or 0, "total": r["total"] or Decimal("0"), "redondeo": r["redondeo"] or Decimal("0")}
