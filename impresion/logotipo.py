"""El logotipo de AllPetcr.com, listo para mandar a una impresora térmica.

Vive aparte de `etiqueta.py` y `tiquete.py` porque lo usan los dos: la etiqueta
lo dibuja dentro de la imagen del producto y el tiquete lo manda como imagen de
trama ESC/POS. Tenerlo en un solo lugar es lo que evita que un día el logo de
la etiqueta y el del recibo dejen de ser el mismo.

Los PNG de `marca/` están guardados ya binarizados —blanco y negro puro, sin
grises— porque la térmica solo imprime negro o nada. Convertir el logo original
a color en cada impresión gastaría tiempo y, peor, daría un resultado distinto
según el umbral que se usara ese día.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CARPETA = Path(__file__).resolve().parent / "marca"

# La P sale más alta que la palabra, como en el logo original.
PROPORCION_MARCA = 1.45

# Después de escalar hay que volver a decidir blanco o negro: LANCZOS deja
# bordes grises y la térmica los imprime como manchas.
UMBRAL = 150


def _pieza(nombre: str, alto_px: int):
    """Una pieza del logo escalada a la altura pedida, en blanco y negro.

    Devuelve `None` si el archivo no está: el ERP tiene que poder imprimir
    igual —sin logo— en vez de dejar a la cajera sin cobrar porque se movió una
    imagen.
    """
    from PIL import Image

    ruta = CARPETA / f"logo_{nombre}.png"
    if not ruta.exists():
        logger.warning("Falta el logotipo %s; la impresión sale sin logo.", ruta)
        return None
    imagen = Image.open(ruta).convert("L")
    ancho = max(1, round(imagen.width * alto_px / imagen.height))
    return _binarizar(imagen.resize((ancho, max(1, alto_px)), Image.LANCZOS))


def _binarizar(imagen):
    return imagen.point(lambda v: 0 if v < UMBRAL else 255, mode="L")


def _escalar(imagen, factor: float):
    from PIL import Image

    nuevo = (max(1, int(imagen.width * factor)), max(1, int(imagen.height * factor)))
    return _binarizar(imagen.resize(nuevo, Image.LANCZOS))


def bloque(alto_texto_px: int, separacion_px: int, ancho_maximo_px: int | None = None):
    """La P y la palabra juntas, alineadas por abajo. `None` si no hay archivos.

    `separacion_px` es el aire entre las dos piezas y NO se escala cuando hay
    que reducir para que el bloque quepa: reducirlo también junta demasiado la
    P con la palabra y el logo se lee como una sola mancha.
    """
    from PIL import Image

    texto = _pieza("texto", alto_texto_px)
    marca = _pieza("marca", int(alto_texto_px * PROPORCION_MARCA))

    if texto is None and marca is None:
        return None
    if marca is None:
        return _encajar(texto, ancho_maximo_px)
    if texto is None:
        return _encajar(marca, ancho_maximo_px)

    total = marca.width + separacion_px + texto.width
    if ancho_maximo_px and total > ancho_maximo_px:
        factor = ancho_maximo_px / total
        marca = _escalar(marca, factor)
        texto = _escalar(texto, factor)
        total = marca.width + separacion_px + texto.width

    alto = max(marca.height, texto.height)
    lienzo = Image.new("L", (total, alto), 255)
    lienzo.paste(marca, (0, alto - marca.height))
    lienzo.paste(texto, (marca.width + separacion_px, alto - texto.height))
    return lienzo


def _encajar(imagen, ancho_maximo_px: int | None):
    if imagen is None or not ancho_maximo_px or imagen.width <= ancho_maximo_px:
        return imagen
    return _escalar(imagen, ancho_maximo_px / imagen.width)


def bloque_de_ancho(ancho_px: int):
    """El logo compuesto para que mida `ancho_px` de ancho. `None` si no hay.

    Es la forma que necesita el tiquete: ahí la medida que manda es el ancho
    del papel, no una altura en milímetros como en la etiqueta. La altura sale
    de las proporciones del logo.
    """
    if ancho_px < 40:
        return None
    # Anchos naturales del logo compuesto, para despejar la altura del texto
    # sin tener que escalar dos veces (escalar dos veces come nitidez).
    #   marca 432 × 490   ·   texto 737 × 100
    alto_texto = max(8, round(ancho_px / 8.77))
    separacion = max(2, round(alto_texto * 0.26))
    return bloque(alto_texto, separacion, ancho_maximo_px=ancho_px)
