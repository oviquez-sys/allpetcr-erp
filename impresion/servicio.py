"""Puerta de entrada única a la impresión. El resto del ERP habla con esto.

Ninguna vista debería importar `windows`, `tiquete` ni `etiqueta` por su
cuenta: si mañana la impresión pasa a un agente en la caja, este archivo es el
que cambia de adentro y nadie más se entera.
"""
from __future__ import annotations

import logging

from django.conf import settings

from . import etiqueta as _etiqueta
from . import tiquete as _tiquete
from . import windows
from .windows import ErrorDeImpresion  # noqa: F401  (se reexporta a propósito)

logger = logging.getLogger(__name__)


def imprimir_tiquete(factura) -> None:
    """Saca el tiquete de la venta por la térmica de recibos."""
    datos = _tiquete.bytes_tiquete(
        factura,
        ancho=settings.ANCHO_TIQUETE,
        pie=settings.PIE_TIQUETE,
        logo=_tiquete.bytes_logo(
            settings.TIQUETE_LOGO_PUNTOS, settings.TIQUETE_PAPEL_PUNTOS
        ),
    )
    windows.enviar_crudo(
        settings.IMPRESORA_RECIBOS, datos, titulo=f"Tiquete {factura.numero}"
    )


def imprimir_etiqueta(producto, copias: int = 1) -> int:
    """Imprime `copias` etiquetas de un producto. Devuelve cuántas salieron.

    La imagen se dibuja UNA vez y se manda tantas veces como copias: dibujar
    el código de barras es lo caro, mandarlo no."""
    if not producto.codigo_barras:
        raise ErrorDeImpresion(
            f"«{producto.nombre}» no tiene código de barras, así que no se le "
            "puede imprimir etiqueta."
        )
    imagen = _etiqueta.imagen_etiqueta(
        producto,
        ancho_mm=settings.ETIQUETA_ANCHO_MM,
        alto_mm=settings.ETIQUETA_ALTO_MM,
        con_precio=settings.ETIQUETA_CON_PRECIO,
    )
    for _ in range(max(1, copias)):
        windows.imprimir_imagen(
            settings.IMPRESORA_ETIQUETAS,
            imagen,
            settings.ETIQUETA_ANCHO_MM,
            settings.ETIQUETA_ALTO_MM,
            titulo=f"Etiqueta {producto.sku}",
        )
    return max(1, copias)


def imprimir_etiquetas(pares) -> int:
    """`pares` es una lista de (producto, copias). Devuelve el total impreso.

    Se corta en el primer error en vez de seguir: si la impresora se quedó sin
    etiquetas en la número 3 de 40, seguir mandando las 37 restantes solo
    llena la cola de Windows de trabajos que hay que ir a borrar a mano."""
    total = 0
    for producto, copias in pares:
        total += imprimir_etiqueta(producto, copias)
    return total


def diagnostico() -> dict:
    """Estado de la impresión, para la pantalla de prueba y los .bat."""
    datos = {
        "disponible": windows.disponible(),
        "impresora_recibos": settings.IMPRESORA_RECIBOS,
        "impresora_etiquetas": settings.IMPRESORA_ETIQUETAS,
        "tiquete_automatico": settings.TIQUETE_AUTOMATICO,
        "instaladas": [],
        "recibos_ok": False,
        "etiquetas_ok": False,
    }
    if datos["disponible"]:
        datos["instaladas"] = windows.listar_impresoras()
        datos["recibos_ok"] = settings.IMPRESORA_RECIBOS in datos["instaladas"]
        datos["etiquetas_ok"] = settings.IMPRESORA_ETIQUETAS in datos["instaladas"]
    return datos
