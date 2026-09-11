"""Operaciones sobre la cola de impresión. Las usa el servicio y el agente.

Se separa de `servicio.py` para que ese archivo siga siendo lo que dice ser:
la puerta de entrada que usa el resto del ERP, sin detalles de base de datos.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count
from django.utils import timezone

from .models import TrabajoImpresion

logger = logging.getLogger(__name__)


def encolar_crudo(impresora: str, datos: bytes, titulo: str, tipo: str) -> TrabajoImpresion:
    """Deja unos bytes esperando a que el agente los mande a la impresora."""
    return TrabajoImpresion.objects.create(
        tipo=tipo,
        formato=TrabajoImpresion.CRUDO,
        impresora=impresora,
        titulo=titulo,
        contenido=datos,
    )


def encolar_imagen(impresora: str, png: bytes, ancho_mm: float, alto_mm: float,
                   titulo: str, tipo: str) -> TrabajoImpresion:
    """Deja una imagen esperando, con el tamaño de papel que hay que pedirle
    a Windows."""
    return TrabajoImpresion.objects.create(
        tipo=tipo,
        formato=TrabajoImpresion.IMAGEN,
        impresora=impresora,
        titulo=titulo,
        contenido=png,
        ancho_mm=ancho_mm,
        alto_mm=alto_mm,
    )


def vencer_atrasados() -> int:
    """Marca como vencidos los trabajos que ya nadie quiere ver salir.

    Ver el porqué en models.py: encender la computadora a mediodía no debe
    escupir los tiquetes de toda la mañana."""
    ahora = timezone.now()
    return TrabajoImpresion.objects.filter(
        estado__in=[TrabajoImpresion.PENDIENTE, TrabajoImpresion.TOMADO],
        vence_en__lt=ahora,
    ).update(estado=TrabajoImpresion.VENCIDO, terminado_en=ahora)


def tomar_pendientes(cuantos: int = 5) -> list[TrabajoImpresion]:
    """Entrega los siguientes trabajos y los marca como tomados.

    El bloqueo de filas es lo que evita que dos agentes —o el mismo agente con
    dos ventanas abiertas por error— se lleven el mismo tiquete y salga
    impreso dos veces.

    SQLite no sabe hacer ese bloqueo y Django levanta NotSupportedError si se
    le pide. La base de verdad, acá y en el servidor, es PostgreSQL; SQLite
    solo aparece en las pruebas, donde no hay dos agentes compitiendo. Por eso
    se pregunta antes en vez de exigirlo: es preferible que las pruebas corran
    a proteger de una concurrencia que en SQLite no existe."""
    vencer_atrasados()
    with transaction.atomic():
        consulta = TrabajoImpresion.objects.filter(estado=TrabajoImpresion.PENDIENTE)
        if connection.features.has_select_for_update_skip_locked:
            consulta = consulta.select_for_update(skip_locked=True)
        pendientes = list(consulta.order_by("creado_en")[:cuantos])
        if pendientes:
            TrabajoImpresion.objects.filter(
                pk__in=[t.pk for t in pendientes]
            ).update(estado=TrabajoImpresion.TOMADO, tomado_en=timezone.now())
    return pendientes


def reportar(trabajo_id: int, ok: bool, detalle: str = "") -> bool:
    """El agente cuenta cómo le fue. Devuelve False si el trabajo no existe."""
    try:
        trabajo = TrabajoImpresion.objects.get(pk=trabajo_id)
    except TrabajoImpresion.DoesNotExist:
        return False
    trabajo.estado = TrabajoImpresion.IMPRESO if ok else TrabajoImpresion.ERROR
    trabajo.detalle = detalle[:2000]
    trabajo.terminado_en = timezone.now()
    trabajo.save(update_fields=["estado", "detalle", "terminado_en"])
    if not ok:
        logger.warning("El agente no pudo imprimir el trabajo %s: %s", trabajo_id, detalle)
    return True


def limpiar_viejos() -> int:
    """Borra los trabajos terminados de hace más de N días.

    El contenido de cada trabajo son cientos de kilobytes (la imagen de la
    etiqueta). Sin esta limpieza la tabla crece sin tope y engorda todos los
    respaldos."""
    dias = getattr(settings, "IMPRESION_CONSERVAR_DIAS", 7)
    corte = timezone.now() - timezone.timedelta(days=dias)
    borrados, _ = TrabajoImpresion.objects.filter(
        estado__in=[TrabajoImpresion.IMPRESO, TrabajoImpresion.ERROR,
                    TrabajoImpresion.VENCIDO],
        terminado_en__lt=corte,
    ).delete()
    return borrados


def resumen() -> dict:
    """Cuántos trabajos hay en cada estado, para la pantalla de impresoras."""
    vencer_atrasados()
    conteos = {e: 0 for e, _ in TrabajoImpresion.ESTADOS}
    for fila in TrabajoImpresion.objects.values("estado").annotate(n=Count("id")):
        conteos[fila["estado"]] = fila["n"]
    ultimo = TrabajoImpresion.objects.order_by("-creado_en").first()
    return {
        "conteos": conteos,
        "pendientes": conteos.get(TrabajoImpresion.PENDIENTE, 0),
        "ultimo_en": ultimo.creado_en if ultimo else None,
        "ultimo_estado": ultimo.get_estado_display() if ultimo else "",
    }
