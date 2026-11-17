"""El sorteo: congelar la lista, sacar el número, suplentes, reclamo y entrega.

Cómo se sortea (y por qué así)
------------------------------
1. Al cierre se CONGELA la lista: cada participante con saldo recibe un
   bloque de números seguidos (María: 1 al 6; Juan: 7; Ana: 8 al 10), en el
   orden en que se inscribieron. La lista se guarda entera junto con su
   huella SHA-256: si alguien cambiara un nombre o un número después, la
   huella ya no coincide.
2. Se elige UN número entre 1 y el total con el generador criptográfico del
   sistema operativo (`secrets`). Cada número tiene exactamente la misma
   probabilidad; quien tiene más números tiene más oportunidades, en
   proporción. No hay semilla que alguien pueda elegir ni repetir.
3. El ganador es el dueño del bloque donde cayó el número.
4. Suplentes (solo si las bases los prevén): se repite el paso 2 sacando de
   la lista a quienes ya salieron, así nadie sale dos veces.

Una segunda pulsación de «Sortear» NO vuelve a sortear: devuelve el resultado
guardado. Eso se garantiza con bloqueo de fila sobre el sorteo, no con el
botón de la pantalla.
"""
import hashlib
import json
import secrets
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Adjudicacion, Campana, CanastaProducto, EntregaPremio, Participante, Sorteo

METODO = (
    "Lista congelada de participantes con sus números consecutivos (huella SHA-256 {huella}). "
    "Se eligió un número entre 1 y {total} con el generador aleatorio criptográfico del sistema "
    "(secrets.randbelow de Python, que usa el del sistema operativo): todos los números tienen la misma "
    "probabilidad. Gana la persona dueña del número que salió."
)
METODO_SUPLENTES = (
    " Los suplentes se eligieron de la misma forma, uno por uno, quitando de la lista a quienes ya habían salido."
)


def puede_sortear(usuario) -> bool:
    return bool(usuario and usuario.is_authenticated and (usuario.is_superuser or usuario.has_perm("campanas.sortear")))


def _telefono_tapado(telefono) -> str:
    """Solo los últimos 4 dígitos: alcanza para que la persona se reconozca
    en una lista publicada sin regalarle su número a nadie."""
    digitos = "".join(c for c in (telefono or "") if c.isdigit())
    return f"····{digitos[-4:]}" if len(digitos) >= 4 else ""


def armar_lista(campana, hasta=None):
    """La lista elegible: participantes con al menos un número, en orden de
    inscripción, cada uno con su bloque. `hasta` deja afuera lo posterior al
    cierre (una inscripción o una compra tardía no cuenta)."""
    hasta = hasta or campana.cierre
    filas, siguiente = [], 1
    participantes = (Participante.objects.filter(campana=campana, creado_en__lte=hasta)
                     .select_related("cliente").order_by("creado_en", "id"))
    for p in participantes:
        numeros = p.movimientos.aggregate(t=Sum("cantidad"))["t"] or 0
        if numeros <= 0:
            continue
        filas.append({"p": p.pk, "c": p.cliente_id, "nombre": p.cliente.nombre,
                      "telefono": _telefono_tapado(p.cliente.telefono), "numeros": numeros,
                      "desde": siguiente, "hasta": siguiente + numeros - 1})
        siguiente += numeros
    return filas


def huella_de(lista) -> str:
    canonico = json.dumps(lista, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


@transaction.atomic
def congelar(campana, usuario, momento=None):
    """Cierra las inscripciones y deja la lista fija. Se puede repetir antes
    del sorteo (si hubo una devolución después de congelar): la versión
    anterior queda anotada."""
    momento = momento or timezone.now()
    campana = Campana.objects.select_for_update().get(pk=campana.pk)
    if campana.estado not in (Campana.Estado.ACTIVA, Campana.Estado.CERRADA):
        raise ValidationError("La lista solo se congela con la campaña activa o ya cerrada sin sortear.")
    if momento < campana.cierre:
        raise ValidationError(
            f"Todavía no es el cierre ({timezone.localtime(campana.cierre):%d/%m/%Y %I:%M %p}). "
            "La lista se congela cuando cierran las inscripciones."
        )
    lista = armar_lista(campana)
    total = lista[-1]["hasta"] if lista else 0
    sorteo = Sorteo.objects.select_for_update().filter(campana=campana).first()
    if sorteo is not None and sorteo.realizado:
        raise ValidationError("El sorteo ya se realizó: la lista no se cambia.")
    datos = {"lista": lista, "total_participantes": len(lista), "total_numeros": total,
             "huella": huella_de(lista), "congelada_en": momento, "congelada_por": usuario}
    if sorteo is None:
        sorteo = Sorteo.objects.create(campana=campana, **datos)
    else:
        sorteo.congelados_previos = sorteo.congelados_previos + [{
            "fecha": sorteo.congelada_en.isoformat(), "huella": sorteo.huella,
            "participantes": sorteo.total_participantes, "numeros": sorteo.total_numeros,
            "por": getattr(sorteo.congelada_por, "username", ""),
        }]
        for campo, valor in datos.items():
            setattr(sorteo, campo, valor)
        sorteo.save()
    if campana.estado != Campana.Estado.CERRADA:
        campana.estado = Campana.Estado.CERRADA
        campana.save(update_fields=["estado"])
    return sorteo


def cambios_despues_de_congelar(sorteo) -> bool:
    """¿La lista de hoy ya no es la congelada? (una devolución posterior)."""
    return not sorteo.realizado and huella_de(armar_lista(sorteo.campana)) != sorteo.huella


def _dueno(lista, numero):
    return next(f for f in lista if f["desde"] <= numero <= f["hasta"])


def _sacar(lista):
    """Un número al azar de `lista` (que puede tener huecos: se sortea sobre
    la cantidad de números que quedan y se traduce al número real)."""
    total = sum(f["numeros"] for f in lista)
    k = secrets.randbelow(total)          # 0 … total-1, todos iguales
    for fila in lista:
        if k < fila["numeros"]:
            return fila, fila["desde"] + k
        k -= fila["numeros"]
    raise AssertionError("El número cayó fuera de la lista")  # imposible: k < total


@transaction.atomic
def sortear(campana, usuario, momento=None):
    """Realiza el sorteo. Devuelve (sorteo, nuevo): `nuevo` es False cuando ya
    estaba hecho y solo se devuelve el resultado guardado."""
    momento = momento or timezone.now()
    campana = Campana.objects.select_for_update().get(pk=campana.pk)
    sorteo = Sorteo.objects.select_for_update().filter(campana=campana).first()
    if sorteo is not None and sorteo.realizado:
        return sorteo, False
    if not puede_sortear(usuario):
        raise ValidationError("No tenés permiso para realizar el sorteo. Lo da un administrador.")
    if momento < campana.sorteo_en:
        raise ValidationError(
            f"El sorteo es el {timezone.localtime(campana.sorteo_en):%d/%m/%Y a las %I:%M %p}. Todavía no se puede."
        )
    if sorteo is None:
        sorteo = congelar(campana, usuario, momento)
        campana.refresh_from_db()
    if sorteo.total_numeros == 0:
        raise ValidationError("No hay participantes con números: no hay a quién sortear.")

    quedan = list(sorteo.lista)
    elegidos = []
    for orden in range(1 + campana.suplentes):
        if not quedan:
            break
        fila, numero = _sacar(quedan)
        elegidos.append((orden, fila, numero))
        quedan = [f for f in quedan if f["p"] != fila["p"]]

    vence = momento + timedelta(days=campana.plazo_reclamo_dias)
    for orden, fila, numero in elegidos:
        Adjudicacion.objects.create(
            sorteo=sorteo, orden=orden, participante_id=fila["p"], numero=numero,
            estado=Adjudicacion.Estado.TITULAR if orden == 0 else Adjudicacion.Estado.ESPERA,
            notificado_en=momento if orden == 0 else None, vence_en=vence if orden == 0 else None,
        )
    sorteo.numero_ganador = elegidos[0][2]
    sorteo.realizado_en = momento
    sorteo.realizado_por = usuario
    sorteo.metodo = METODO.format(huella=sorteo.huella, total=sorteo.total_numeros) + (
        METODO_SUPLENTES if campana.suplentes else "")
    sorteo.save(update_fields=["numero_ganador", "realizado_en", "realizado_por", "metodo"])
    campana.estado = Campana.Estado.SORTEADA
    campana.save(update_fields=["estado"])
    return sorteo, True


def titular(sorteo):
    """Quien tiene hoy el derecho al premio (o ya lo recibió)."""
    return sorteo.adjudicaciones.filter(
        estado__in=[Adjudicacion.Estado.TITULAR, Adjudicacion.Estado.ENTREGADO]).select_related(
        "participante__cliente").first()


@transaction.atomic
def no_respondio(sorteo, usuario, nota="", momento=None):
    """El titular no reclamó a tiempo: pierde el derecho y sube el siguiente
    suplente (si hay). Devuelve el nuevo titular o None (premio desierto)."""
    momento = momento or timezone.now()
    sorteo = Sorteo.objects.select_for_update().get(pk=sorteo.pk)
    actual = sorteo.adjudicaciones.filter(estado=Adjudicacion.Estado.TITULAR).first()
    if actual is None:
        raise ValidationError("No hay nadie con el premio por reclamar.")
    if actual.vence_en and momento < actual.vence_en:
        raise ValidationError(
            f"Todavía está en plazo: tiene hasta el {timezone.localtime(actual.vence_en):%d/%m/%Y %I:%M %p}."
        )
    actual.estado = Adjudicacion.Estado.NO_RESPONDIO
    actual.nota = (nota or f"No respondió. Anotó: {getattr(usuario, 'username', '')}")[:200]
    actual.save(update_fields=["estado", "nota"])
    siguiente = sorteo.adjudicaciones.filter(estado=Adjudicacion.Estado.ESPERA).order_by("orden").first()
    if siguiente is None:
        return None
    siguiente.estado = Adjudicacion.Estado.TITULAR
    siguiente.notificado_en = momento
    siguiente.vence_en = momento + timedelta(days=sorteo.campana.plazo_reclamo_dias)
    siguiente.save(update_fields=["estado", "notificado_en", "vence_en"])
    return siguiente


# --- canasta y entrega ---------------------------------------------------------

def costo_canasta(campana, version) -> Decimal:
    """Lo que cuesta hoy esa versión (costo promedio, sin IVA)."""
    return sum((c.producto.costo_promedio * c.cantidad
                for c in campana.canasta.filter(version=version).select_related("producto")), Decimal("0"))


def unidades_canasta(campana, version) -> int:
    return campana.canasta.filter(version=version).aggregate(t=Sum("cantidad"))["t"] or 0


@transaction.atomic
def entregar(sorteo, *, version, recibe_nombre, recibe_identificacion="", nota="", usuario, sesion_caja):
    """Entrega la canasta al titular: los productos salen del inventario como
    una venta de regalía (kardex REG + asiento de gasto de promoción, el
    mismo camino de cualquier regalo) y queda la constancia.

    Necesita una caja abierta porque toda venta —aunque sea de ₡0— pertenece
    a una sesión de caja; no entra ni sale efectivo."""
    from ventas.services import registrar_venta

    sorteo = Sorteo.objects.select_for_update().select_related("campana").get(pk=sorteo.pk)
    campana = sorteo.campana
    if campana.es_demo:
        raise ValidationError("En la demostración no se entrega nada: no se toca el inventario real.")
    if hasattr(sorteo, "entrega"):
        raise ValidationError("El premio ya se entregó.")
    actual = sorteo.adjudicaciones.filter(estado=Adjudicacion.Estado.TITULAR).select_related(
        "participante__cliente").first()
    if actual is None:
        raise ValidationError("No hay ganador con el premio por reclamar.")
    if version not in CanastaProducto.Version.values:
        raise ValidationError("Elegí la canasta: para perro o para gato.")
    recibe_nombre = " ".join((recibe_nombre or "").split())[:150]
    if not recibe_nombre:
        raise ValidationError("Anotá el nombre de quien recibe la canasta.")
    productos = list(campana.canasta.filter(version=version).select_related("producto"))
    if not productos:
        raise ValidationError("Esa versión de la canasta no tiene productos cargados.")
    if sesion_caja is None:
        raise ValidationError("Abrí la caja para registrar la entrega (no se mueve efectivo).")

    motivo = f"Premio {campana.nombre} — {actual.participante.cliente.nombre}"[:200]
    factura = registrar_venta(
        sesion_caja=sesion_caja, medio_pago="EFE", usuario=usuario, cliente=actual.participante.cliente,
        permitir_regalia_alta=True,
        lineas=[{"producto_id": c.producto_id, "cantidad": c.cantidad, "es_regalia": True, "motivo": motivo}
                for c in productos],
    )
    costo = sum((l.costo_unitario * l.cantidad for l in factura.lineas.all()), Decimal("0"))
    entrega = EntregaPremio.objects.create(
        sorteo=sorteo, adjudicacion=actual, version=version, factura=factura, costo=costo,
        recibe_nombre=recibe_nombre, recibe_identificacion=(recibe_identificacion or "").strip()[:30],
        nota=(nota or "").strip()[:200], entregado_por=usuario,
    )
    actual.estado = Adjudicacion.Estado.ENTREGADO
    actual.save(update_fields=["estado"])
    return entrega
