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


def esperado_por_medio(sesion) -> dict:
    """Lo vendido en la sesión por tarjeta y por SINPE (pagos mixtos
    repartidos). Es lo que el cierre del datáfono y el estado de SINPE
    tendrían que mostrar (CAJ-02)."""
    from ventas.models import FacturaVenta
    from ventas.pagos import por_medio

    medios = por_medio(sesion.ventas.filter(estado=FacturaVenta.Estado.EMITIDA))
    return {m: (medios.get(m, {}).get("t") or Decimal("0")) for m in ("TAR", "SIN")}


@transaction.atomic
def cerrar_caja(*, sesion, monto_contado=None, usuario=None, tarjeta_contado=None, sinpe_contado=None,
                conteo=None) -> SesionCaja:
    """Arqueo: se registra lo contado físicamente y se calcula la diferencia
    contra lo esperado. La sesión queda inmutable.

    tarjeta_contado / sinpe_contado (CAJ-02): lo que dice el cierre del
    datáfono y lo que de verdad entró por SINPE. Opcionales: vacío = no se
    revisó, que no es lo mismo que cero.

    conteo: {"20000": 2, "500": 6, ...}. Si viene, el efectivo contado es su
    suma y queda guardado el desglose."""
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
    sesion.save()
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
