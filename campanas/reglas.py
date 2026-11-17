"""Reglas de una campaña: quién participa, cuántos números da cada compra,
cuándo se quitan, y qué beneficios le tocan a un pedido.

TODO el cálculo vive acá. La caja, el comprobante, la API del sitio y la
pantalla de medición leen de estas funciones; ninguna vuelve a calcular por
su cuenta (la misma regla que `catalogo/promociones.py`).

Definiciones (las que Oscar pidió ver antes de activar)
-------------------------------------------------------
- **Monto que se evalúa contra el umbral**: lo que el cliente paga por los
  PRODUCTOS de esa venta, con IVA, DESPUÉS de descuentos, promociones, cupón
  y redondeo. Es `FacturaVenta.total` (o `Pedido.total`). El envío nunca
  entra: no es una línea de la venta. Las regalías valen ₡0.
- **Supera el umbral** = estrictamente mayor. ₡20.000 exactos NO ganan bono.
- **Cuándo se acredita**: una sola vez, al concretarse la venta (al cobrar en
  caja, o al confirmarse el pago de la pasarela). Un pedido web sin cobrar no
  da números.
- **A quién**: al cliente de la venta, si ya estaba inscrito en ese momento.
  Inscribirse antes de cobrar basta para que esa misma compra cuente.
- **Si la venta cambia**: se recalcula con el monto que queda. Devolución
  parcial que la deja en ₡20.000 o menos → pierde el bono; devolución total o
  anulación → pierde todos los números de esa venta. Cada baja queda en el
  libro (`MovimientoNumeros`, tipo REV).
"""
import logging
import unicodedata
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Campana, MovimientoNumeros, NumerosVenta, Participante

logger = logging.getLogger(__name__)


# --- cuál campaña --------------------------------------------------------------

def vigente(empresa, momento=None):
    """La campaña que está corriendo (activa y ya iniciada), o None. Puede
    haber pasado el cierre: sigue «vigente» hasta el sorteo para mostrar
    participación y envío gratis, aunque ya no dé números."""
    momento = momento or timezone.now()
    return (Campana.objects.filter(empresa=empresa, es_demo=False, estado=Campana.Estado.ACTIVA,
                                   inicio__lte=momento).first())


def que_acepta(empresa, momento=None):
    """La campaña en la que HOY se puede inscribir y las compras dan números."""
    c = vigente(empresa, momento)
    return c if c is not None and c.acepta(momento) else None


def bloquea_bienvenida(empresa, momento=None) -> bool:
    """¿Hay que dejar de emitir cupones de bienvenida nuevos?

    Sí mientras una campaña que reemplaza la bienvenida esté en curso (desde
    su inicio hasta que se finaliza), y después también si al finalizarla se
    eligió «queda sin regalo de bienvenida». Los cupones YA emitidos no se
    tocan: esto solo decide si se crean nuevos."""
    momento = momento or timezone.now()
    base = Campana.objects.filter(empresa=empresa, es_demo=False, reemplaza_bienvenida=True)
    en_curso = base.filter(estado__in=[Campana.Estado.ACTIVA, Campana.Estado.CERRADA, Campana.Estado.SORTEADA],
                           inicio__lte=momento)
    if en_curso.exists():
        return True
    ultima = base.filter(estado=Campana.Estado.FINALIZADA).order_by("-finalizada_en", "-id").first()
    return ultima is not None and ultima.despues == Campana.Despues.NADA


# --- números por monto ---------------------------------------------------------

def numeros_por_monto(campana, monto) -> tuple[int, int]:
    """(habituales, bono) para una compra de ese monto."""
    monto = Decimal(monto or 0)
    if monto <= 0 or monto < campana.compra_minima:
        return 0, 0
    bono = campana.numeros_bono if monto > campana.umbral_bono else 0
    return campana.numeros_compra, bono


def saldo(participante) -> int:
    return participante.movimientos.aggregate(t=Sum("cantidad"))["t"] or 0


def participante_de(campana, cliente):
    if campana is None or cliente is None:
        return None
    return Participante.objects.filter(campana=campana, cliente=cliente).first()


# --- inscripción ---------------------------------------------------------------

def _limpiar_origen(texto) -> str:
    permitido = " /-_."
    return "".join(c for c in (texto or "").lower() if c.isalnum() or c in permitido).strip()[:80]


@transaction.atomic
def inscribir(*, campana, cliente, canal, origen_visita="", usuario=None, cliente_nuevo=False,
              miembro_nuevo=False, momento=None):
    """Inscribe a un cliente. Devuelve (participante, creado).

    Inscribirse dos veces no da dos participaciones ni dos números de
    inscripción: la segunda vez devuelve la que ya tenía."""
    momento = momento or timezone.now()
    if not campana.es_demo and not campana.acepta(momento):
        if campana.estado != Campana.Estado.ACTIVA:
            raise ValidationError("La campaña no está activa.")
        if momento < campana.inicio:
            raise ValidationError("La campaña todavía no empieza.")
        raise ValidationError("Las inscripciones ya cerraron.")
    existente = Participante.objects.filter(campana=campana, cliente=cliente).first()
    if existente is not None:
        return existente, False
    try:
        with transaction.atomic():
            participante = Participante.objects.create(
                campana=campana, cliente=cliente, canal=canal, origen_visita=_limpiar_origen(origen_visita),
                acepto_bases_en=momento, inscrito_por=usuario, cliente_nuevo=cliente_nuevo,
                miembro_nuevo=miembro_nuevo,
            )
    except IntegrityError:
        # Dos inscripciones simultáneas de la misma persona: ganó la otra.
        return Participante.objects.get(campana=campana, cliente=cliente), False
    if campana.numeros_inscripcion:
        MovimientoNumeros.objects.create(
            campana=campana, participante=participante, tipo=MovimientoNumeros.Tipo.INSCRIPCION,
            cantidad=campana.numeros_inscripcion, motivo="Inscripción", usuario=usuario,
        )
    return participante, True


# --- acreditar una venta -------------------------------------------------------

def _margen_factura(factura) -> Decimal:
    return sum(((l.subtotal if l.subtotal is not None else l.total) - l.costo_unitario * l.cantidad
                for l in factura.lineas.all()), Decimal("0")).quantize(Decimal("0.01"))


def _margen_pedido(pedido) -> Decimal:
    """El pedido no guarda el costo de cada línea: se usa el costo promedio
    de hoy, que al acreditar (recién pagado) es el del momento."""
    costo = sum((l.producto.costo_promedio * l.cantidad for l in pedido.lineas.select_related("producto")),
                Decimal("0"))
    return (pedido.subtotal - costo).quantize(Decimal("0.01"))


def _crear_numeros(campana, participante, *, documento, canal, monto, fecha, factura=None, pedido=None,
                   usuario=None, margen=None):
    """`margen` solo lo manda la demostración, que no tiene venta detrás."""
    habituales, bono = numeros_por_monto(campana, monto)
    if habituales + bono == 0:
        return None
    if margen is None:
        margen = _margen_factura(factura) if factura is not None else _margen_pedido(pedido)
    venta = NumerosVenta.objects.create(
        campana=campana, participante=participante, factura=factura, pedido=pedido, documento=documento,
        canal=canal, fecha=fecha, monto_evaluado=monto, monto_vigente=monto, habituales=habituales, bono=bono,
        margen=margen,
    )
    MovimientoNumeros.objects.create(
        campana=campana, participante=participante, tipo=MovimientoNumeros.Tipo.COMPRA, cantidad=habituales,
        venta=venta, motivo=f"Compra {documento}", usuario=usuario,
    )
    if bono:
        MovimientoNumeros.objects.create(
            campana=campana, participante=participante, tipo=MovimientoNumeros.Tipo.BONO, cantidad=bono,
            venta=venta, motivo=f"Compra {documento}: supera ₡{campana.umbral_bono:,.0f}".replace(",", "."),
            usuario=usuario,
        )
    return venta


def acreditar_venta(factura, *, es_web=False, usuario=None):
    """Da los números de una venta de caja. Una sola vez por venta.

    La llama `ventas.services.registrar_venta` dentro de su transacción. Si
    algo de la campaña falla, la VENTA no se cae por eso: se anota en el log
    y los números se pueden reponer con `recalcular_venta`. Cobrarle al
    cliente es más importante que su número del sorteo."""
    try:
        with transaction.atomic():
            return _acreditar_venta(factura, es_web=es_web, usuario=usuario)
    except Exception:  # noqa: BLE001 — la venta manda; ver docstring
        logger.exception("No se pudieron acreditar los números de la venta %s", factura.numero)
        return None


def _acreditar_venta(factura, *, es_web, usuario):
    if factura.cliente_id is None or factura.total <= 0:
        return None
    if NumerosVenta.objects.filter(factura=factura).exists():
        return factura.numeros_campana
    campana = que_acepta(factura.empresa, factura.creado_en)
    participante = participante_de(campana, factura.cliente)
    if participante is None:
        return None
    return _crear_numeros(
        campana, participante, documento=factura.numero, factura=factura, monto=factura.total,
        fecha=factura.creado_en, usuario=usuario,
        canal=NumerosVenta.Canal.WEB if es_web else NumerosVenta.Canal.TIENDA,
    )


def acreditar_pedido(pedido, usuario=None):
    """Lo mismo para un pedido pagado por la pasarela del sitio."""
    try:
        with transaction.atomic():
            if pedido.cliente_id is None or pedido.total <= 0:
                return None
            if NumerosVenta.objects.filter(pedido=pedido).exists():
                return pedido.numeros_campana
            campana = que_acepta(pedido.empresa, pedido.creado_en)
            participante = participante_de(campana, pedido.cliente)
            if participante is None:
                return None
            return _crear_numeros(campana, participante, documento=pedido.numero, pedido=pedido,
                                  monto=pedido.total, fecha=pedido.creado_en, usuario=usuario,
                                  canal=NumerosVenta.Canal.WEB)
    except Exception:  # noqa: BLE001 — el pedido ya está pagado; no se cae por la campaña
        logger.exception("No se pudieron acreditar los números del pedido %s", pedido.numero)
        return None


def desglose_de(factura):
    """Lo que el comprobante dice de los números de esta venta: habituales,
    bono, total, lo revertido y cuántos lleva la persona. None si la venta
    no dio números. Lo usan el tiquete impreso, el de pantalla y el recibo."""
    venta = (NumerosVenta.objects.filter(factura=factura)
             .select_related("campana", "participante").first()) if getattr(factura, "pk", None) else None
    if venta is None:
        return None
    campana = venta.campana
    return {
        "campana": campana.nombre, "habituales": venta.habituales, "bono": venta.bono, "total": venta.total,
        "revertidos": venta.revertidos, "lleva": saldo(venta.participante), "umbral": campana.umbral_bono,
        "sorteo": timezone.localtime(campana.sorteo_en).date(), "monto": venta.monto_evaluado,
    }


# --- recalcular ----------------------------------------------------------------

def _monto_vigente_factura(factura) -> Decimal:
    if factura.estado == factura.Estado.ANULADA:
        return Decimal("0")
    devuelto = factura.devoluciones.aggregate(t=Sum("total"))["t"] or Decimal("0")
    return max(Decimal("0"), factura.total - devuelto)


def _ajustar(venta, monto, motivo, usuario):
    """Deja `venta` con los números que le tocan a `monto`. Solo baja: una
    venta no gana números después de hecha."""
    habituales, bono = numeros_por_monto(venta.campana, monto)
    habituales, bono = min(habituales, venta.habituales), min(bono, venta.bono)
    quita = (venta.habituales - habituales) + (venta.bono - bono)
    cambio_monto = venta.monto_vigente != monto
    if quita:
        MovimientoNumeros.objects.create(
            campana=venta.campana, participante=venta.participante, tipo=MovimientoNumeros.Tipo.REVERSION,
            cantidad=-quita, venta=venta, motivo=motivo[:200], usuario=usuario,
        )
        venta.habituales, venta.bono = habituales, bono
        venta.revertidos += quita
    if quita or cambio_monto:
        venta.monto_vigente = monto
        venta.save(update_fields=["habituales", "bono", "revertidos", "monto_vigente", "actualizado_en"])
    return quita


def recalcular_venta(factura, *, motivo="", usuario=None) -> int:
    """Después de una devolución o una anulación: quita los números que la
    venta ya no merece. Devuelve cuántos quitó. Nunca tumba la operación que
    la llamó (misma razón que `acreditar_venta`)."""
    try:
        with transaction.atomic():
            venta = NumerosVenta.objects.select_for_update().filter(factura=factura).first()
            if venta is None:
                return 0
            monto = _monto_vigente_factura(factura)
            return _ajustar(venta, monto, motivo or f"Cambio en la venta {factura.numero}", usuario)
    except Exception:  # noqa: BLE001 — la devolución o anulación manda
        logger.exception("No se pudieron recalcular los números de la venta %s", factura.numero)
        return 0


def revertir_pedido(pedido, *, motivo="", usuario=None) -> int:
    """Pedido de la pasarela cancelado: pierde sus números."""
    try:
        with transaction.atomic():
            venta = NumerosVenta.objects.select_for_update().filter(pedido=pedido).first()
            if venta is None:
                return 0
            return _ajustar(venta, Decimal("0"), motivo or f"Pedido {pedido.numero} cancelado", usuario)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudieron revertir los números del pedido %s", pedido.numero)
        return 0


# --- beneficios de un pedido o de una venta en curso ---------------------------

def _plano(texto) -> str:
    sin = unicodedata.normalize("NFD", (texto or "").lower())
    return " ".join("".join(c for c in sin if unicodedata.category(c) != "Mn").split())


def zona_califica(campana, canton, distrito="") -> bool:
    """¿Esa dirección está en una zona con envío gratis? Cada zona es un
    cantón («Heredia») o cantón / distrito («Heredia / Mercedes»). «Heredia
    Central» y «Central» valen como el cantón Heredia: así lo escribe la
    gente."""
    canton, distrito = _plano(canton), _plano(distrito)
    if canton in ("heredia central", "central", "central heredia", "heredia centro"):
        canton = "heredia"
    if not canton:
        return False
    for zona in campana.lista_zonas:
        partes = [_plano(p) for p in zona.split("/")]
        if partes[0] != canton:
            continue
        if len(partes) == 1 or not partes[1] or partes[1] == distrito:
            return True
    return False


def beneficios(campana, *, monto, participa, entrega="RET", canton="", distrito="", momento=None) -> dict:
    """Qué le da la campaña a una compra de `monto` (productos con IVA, ya con
    descuentos, sin envío). Lo usan la caja (antes de cobrar) y el sitio."""
    momento = momento or timezone.now()
    monto = Decimal(monto or 0)
    supera = monto > campana.umbral_bono
    habituales, bono = numeros_por_monto(campana, monto) if campana.acepta(momento) else (0, 0)
    falta = Decimal("0") if supera else (campana.umbral_bono - monto + Decimal("1")).quantize(Decimal("1"))
    envio = {"aplica": False, "gratis": False, "motivo": ""}
    if entrega == "ENV":
        envio["aplica"] = True
        if not campana.da_envio_gratis(momento):
            envio["motivo"] = "El envío gratis de la campaña no está vigente."
        elif not supera:
            envio["motivo"] = f"El pedido tiene que superar ₡{campana.umbral_bono:,.0f} en productos.".replace(",", ".")
        elif not zona_califica(campana, canton, distrito):
            envio["motivo"] = "La dirección está fuera de la zona con envío gratis."
        else:
            envio["gratis"] = True
            envio["motivo"] = "Envío gratis: supera el monto y está dentro de la zona."
    return {
        "monto_evaluado": monto,
        "umbral": campana.umbral_bono,
        "supera_umbral": supera,
        "falta_para_bono": falta,
        "participa": bool(participa),
        "da_numeros": campana.acepta(momento),
        # Lo que ganaría la compra SI la persona está inscrita al cobrar.
        "numeros": {"habituales": habituales, "bono": bono, "total": habituales + bono},
        "envio": envio,
    }


# --- cambios de estado ---------------------------------------------------------

@transaction.atomic
def activar(campana, usuario=None):
    campana = Campana.objects.select_for_update().get(pk=campana.pk)
    if campana.es_demo:
        raise ValidationError("La demostración no se activa: ya trae sus datos ficticios.")
    if campana.estado != Campana.Estado.BORRADOR:
        raise ValidationError("Solo se activa una campaña en borrador.")
    campana.full_clean()
    if not campana.bases.strip():
        raise ValidationError("Antes de activar, escribí las bases: es lo que el cliente acepta al inscribirse.")
    if "[POR DEFINIR" in campana.bases:
        raise ValidationError("Las bases todavía tienen partes marcadas «[POR DEFINIR]». "
                              "Decidilas y corregí el texto antes de activar.")
    if Campana.objects.filter(empresa=campana.empresa, es_demo=False, estado=Campana.Estado.ACTIVA).exists():
        raise ValidationError("Ya hay otra campaña activa. Finalizala primero.")
    ahora = timezone.now()
    campana.estado = Campana.Estado.ACTIVA
    campana.activada_en = ahora
    campana.activada_por = usuario
    # Un borrador preparado días antes queda con un inicio ya pasado: la
    # campaña empieza de verdad al activarla, y así lo dicen las bases
    # («desde la fecha de inicio publicada») y la medición (primeras compras).
    if campana.inicio < ahora:
        campana.inicio = ahora
    campana.save(update_fields=["estado", "activada_en", "activada_por", "inicio"])
    return campana


@transaction.atomic
def finalizar(campana, usuario=None):
    """Cierra la campaña del todo. Lo que sigue con el regalo de bienvenida
    lo dice `campana.despues` (ver `bloquea_bienvenida`)."""
    campana = Campana.objects.select_for_update().get(pk=campana.pk)
    if campana.estado == Campana.Estado.FINALIZADA:
        return campana
    if campana.estado == Campana.Estado.BORRADOR:
        raise ValidationError("Una campaña en borrador no se finaliza: se borra o se activa.")
    campana.estado = Campana.Estado.FINALIZADA
    campana.finalizada_en = timezone.now()
    campana.save(update_fields=["estado", "finalizada_en"])
    return campana


def al_unir_clientes(conservar, absorber):
    """Dos fichas resultaron ser la misma persona (manada.identificar): sus
    participaciones también se juntan. Si las dos estaban inscritas en la
    misma campaña, queda una sola con las compras de ambas y UN solo número
    de inscripción (nadie se inscribe dos veces)."""
    for vieja in Participante.objects.filter(cliente=absorber).select_related("campana"):
        propia = Participante.objects.filter(campana=vieja.campana, cliente=conservar).first()
        if propia is None:
            vieja.cliente = conservar
            vieja.save(update_fields=["cliente"])
            continue
        NumerosVenta.objects.filter(participante=vieja).update(participante=propia)
        MovimientoNumeros.objects.filter(participante=vieja).exclude(
            tipo=MovimientoNumeros.Tipo.INSCRIPCION).update(participante=propia)
        sobra = saldo(vieja)
        if sobra:
            MovimientoNumeros.objects.create(
                campana=vieja.campana, participante=vieja, tipo=MovimientoNumeros.Tipo.REVERSION,
                cantidad=-sobra, motivo=f"Era la misma persona que {conservar.nombre}: inscripción repetida",
            )
