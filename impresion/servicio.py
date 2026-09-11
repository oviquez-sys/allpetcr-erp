"""Puerta de entrada única a la impresión. El resto del ERP habla con esto.

Ninguna vista debería importar `windows`, `tiquete` ni `etiqueta` por su
cuenta: si mañana la impresión pasa a un agente en la caja, este archivo es el
que cambia de adentro y nadie más se entera.

ESE «MAÑANA» LLEGÓ EL 10/09/2026. Ahora hay dos caminos y este archivo elige:

  - Si el ERP corre en la MISMA computadora que las impresoras (Windows con
    pywin32), imprime directo, como toda la vida. Es el caso de la máquina de
    desarrollo y el de una caja que corra el ERP local.

  - Si corre en el servidor de DigitalOcean (Linux, en Nueva York), no hay
    USB que valga: el trabajo se deja en la cola (`cola.py`) y el agente que
    corre en la computadora de la tienda lo recoge y lo imprime.

Lo que NO cambia: quién arma el tiquete y la etiqueta. Los bytes ESC/POS y la
imagen de la etiqueta se siguen generando acá, en el servidor, con el mismo
código probado. El agente es tonto a propósito —recibe y entrega— para que un
cambio de diseño no obligue a ir a actualizar el programa de la tienda.
"""
from __future__ import annotations

import logging
from io import BytesIO

from django.conf import settings

from . import cola
from . import etiqueta as _etiqueta
from . import tiquete as _tiquete
from . import windows
from .models import TrabajoImpresion
from .windows import ErrorDeImpresion  # noqa: F401  (se reexporta a propósito)

logger = logging.getLogger(__name__)


def por_agente() -> bool:
    """¿Hay que pasar por la cola en vez de imprimir directo?

    La regla es «¿esta máquina ve las impresoras?», no una variable de
    configuración, para que nadie tenga que acordarse de cambiarla al mover
    el ERP. IMPRESION_FORZAR_AGENTE existe solo para poder probar el camino
    del agente desde una computadora con Windows."""
    if getattr(settings, "IMPRESION_FORZAR_AGENTE", False):
        return True
    return not windows.disponible()


def _png(imagen) -> bytes:
    memoria = BytesIO()
    imagen.save(memoria, "PNG")
    return memoria.getvalue()


def enviar_crudo(impresora: str, datos: bytes, titulo: str, tipo: str) -> None:
    """Unos bytes a una impresora, por el camino que corresponda.

    La usan las impresiones de prueba (`prueba.py`), que tienen que llegar al
    papel por el mismo camino que un tiquete de verdad: si la prueba imprimiera
    directo y la venta por la cola, probar no probaría nada."""
    if por_agente():
        cola.encolar_crudo(impresora, datos, titulo, tipo)
        return
    windows.enviar_crudo(impresora, datos, titulo=titulo)


def enviar_imagen(impresora: str, imagen, ancho_mm: float, alto_mm: float,
                  titulo: str, tipo: str) -> None:
    """Una imagen a una impresora, por el camino que corresponda."""
    if por_agente():
        cola.encolar_imagen(impresora, _png(imagen), ancho_mm, alto_mm, titulo, tipo)
        return
    windows.imprimir_imagen(impresora, imagen, ancho_mm, alto_mm, titulo=titulo)


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
    titulo = f"Tiquete {factura.numero}"
    if por_agente():
        cola.encolar_crudo(
            settings.IMPRESORA_RECIBOS, datos, titulo, TrabajoImpresion.TIQUETE
        )
        return
    windows.enviar_crudo(settings.IMPRESORA_RECIBOS, datos, titulo=titulo)


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
    copias = max(1, copias)
    titulo = f"Etiqueta {producto.sku}"

    if por_agente():
        png = _png(imagen)
        for _ in range(copias):
            cola.encolar_imagen(
                settings.IMPRESORA_ETIQUETAS, png,
                settings.ETIQUETA_ANCHO_MM, settings.ETIQUETA_ALTO_MM,
                titulo, TrabajoImpresion.ETIQUETA,
            )
        return copias

    for _ in range(copias):
        windows.imprimir_imagen(
            settings.IMPRESORA_ETIQUETAS,
            imagen,
            settings.ETIQUETA_ANCHO_MM,
            settings.ETIQUETA_ALTO_MM,
            titulo=titulo,
        )
    return copias


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
        "por_agente": por_agente(),
        "impresora_recibos": settings.IMPRESORA_RECIBOS,
        "impresora_etiquetas": settings.IMPRESORA_ETIQUETAS,
        "tiquete_automatico": settings.TIQUETE_AUTOMATICO,
        "instaladas": [],
        "recibos_ok": False,
        "etiquetas_ok": False,
        "cola": None,
    }
    if datos["disponible"]:
        datos["instaladas"] = windows.listar_impresoras()
        datos["recibos_ok"] = settings.IMPRESORA_RECIBOS in datos["instaladas"]
        datos["etiquetas_ok"] = settings.IMPRESORA_ETIQUETAS in datos["instaladas"]
    if datos["por_agente"]:
        datos["cola"] = cola.resumen()
    return datos
