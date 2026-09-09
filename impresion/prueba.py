"""Impresiones de prueba, para calibrar sin tener que hacer una venta real.

La regla de la impresora de recibos es el instrumento de medición: si el
renglón de números se ve completo en una sola línea, el ancho configurado es
correcto; si se parte, hay que bajar `ANCHO_TIQUETE`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from . import etiqueta as _etiqueta
from . import tiquete as _tiquete
from . import windows


def prueba_recibos() -> None:
    ancho = settings.ANCHO_TIQUETE
    regla = "".join(str(i % 10) for i in range(1, ancho + 1))
    logo = _tiquete.bytes_logo(
        settings.TIQUETE_LOGO_PUNTOS, settings.TIQUETE_PAPEL_PUNTOS
    )
    partes = [
        _tiquete.INICIALIZAR, _tiquete.CODIGOS_CP850, _tiquete.CENTRO,
    ]
    if logo:
        partes += [logo, _tiquete.SALTO]
    partes += [
        _tiquete.NEGRITA_ON, _tiquete.DOBLE, _tiquete._texto("ALLPETCR"),
        _tiquete.NORMAL, _tiquete.NEGRITA_OFF, _tiquete.SALTO,
        _tiquete._texto("Prueba de impresora de recibos"), _tiquete.SALTO,
        _tiquete._texto(f"{timezone.localtime():%d/%m/%Y %I:%M %p}"), _tiquete.SALTO,
        _tiquete.IZQUIERDA, _tiquete.SALTO,
        _tiquete._texto(f"Regla de {ancho} columnas:"), _tiquete.SALTO,
        _tiquete._texto(regla), _tiquete.SALTO,
        _tiquete._texto("Si esa fila se parte en dos, baje ANCHO_TIQUETE."), _tiquete.SALTO,
        _tiquete._texto("Acentos y simbolo: aeiou con tilde -> áéíóú ñ ¢1.000"), _tiquete.SALTO,
        _tiquete.SALTO, _tiquete.SALTO, _tiquete.CORTAR,
    ]
    windows.enviar_crudo(settings.IMPRESORA_RECIBOS, b"".join(partes), "Prueba de recibos")


@dataclass
class _ProductoDePrueba:
    """Producto ficticio: la prueba no debe depender de que haya catálogo."""
    nombre: str = "Producto de prueba AllPetCR"
    sku: str = "PRUEBA1"
    codigo_barras: str = "PRUEBA1"
    precio_venta: Decimal = Decimal("12500")


def prueba_etiquetas() -> None:
    imagen = _etiqueta.imagen_etiqueta(
        _ProductoDePrueba(),
        ancho_mm=settings.ETIQUETA_ANCHO_MM,
        alto_mm=settings.ETIQUETA_ALTO_MM,
        con_precio=settings.ETIQUETA_CON_PRECIO,
    )
    windows.imprimir_imagen(
        settings.IMPRESORA_ETIQUETAS, imagen,
        settings.ETIQUETA_ANCHO_MM, settings.ETIQUETA_ALTO_MM,
        "Etiqueta de prueba",
    )
