"""Imprime UNA etiqueta con cada version del logo, para elegir en papel.

Script temporal (09/09/2026). No es parte del ERP: solo dibuja el diseño nuevo
con las dos versiones del logotipo y las manda a la impresora de etiquetas.
Se borra cuando Oscar decida cual queda.
"""
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.conf import settings
from PIL import Image, ImageDraw

from impresion import windows
from impresion.etiqueta import (
    MARGEN_MM, _envolver, _fuente, _mm_a_px, imagen_codigo_barras,
)

CARPETA_MARCA = Path(settings.BASE_DIR) / "impresion" / "marca"
ALTO_LOGO_MM = 4.4
ALTO_BARRAS_MM = 9.5
MARGEN_SUP_MM = 1.4
MARGEN_INF_MM = 0.9
HUECO_LOGO_MM = 0.3
HUECO_PRECIO_MM = 0.7
HUECO_DESC_MM = 0.6


def _logo(nombre: str, alto_px: int):
    ruta = CARPETA_MARCA / f"logo_{nombre}.png"
    im = Image.open(ruta).convert("L")
    ancho = max(1, round(im.width * alto_px / im.height))
    chico = im.resize((ancho, alto_px), Image.LANCZOS)
    return chico.point(lambda v: 0 if v < 150 else 255, mode="L")


def dibujar(producto, con_marca: bool):
    ancho_px = _mm_a_px(settings.ETIQUETA_ANCHO_MM)
    alto_px = _mm_a_px(settings.ETIQUETA_ALTO_MM)
    margen = _mm_a_px(MARGEN_MM)
    util = ancho_px - 2 * margen

    lienzo = Image.new("L", (ancho_px, alto_px), 255)
    pincel = ImageDraw.Draw(lienzo)

    def centrar_texto(texto, fuente, y):
        pincel.text(((ancho_px - pincel.textlength(texto, font=fuente)) / 2, y),
                    texto, font=fuente, fill=0)

    def centrar_imagen(imagen, y):
        lienzo.paste(imagen, ((ancho_px - imagen.width) // 2, y))

    y = _mm_a_px(MARGEN_SUP_MM)
    tope = alto_px - _mm_a_px(MARGEN_INF_MM)
    alto_logo = _mm_a_px(ALTO_LOGO_MM)

    if not con_marca:
        centrar_imagen(_logo("texto", alto_logo), y)
        y += alto_logo
    else:
        marca = _logo("marca", int(alto_logo * 1.45))
        texto = _logo("texto", alto_logo)
        separacion = _mm_a_px(1.1)
        total = marca.width + separacion + texto.width
        if total > util:
            factor = util / total
            marca = marca.resize((int(marca.width * factor), int(marca.height * factor)), Image.LANCZOS)
            texto = texto.resize((int(texto.width * factor), int(texto.height * factor)), Image.LANCZOS)
            total = marca.width + separacion + texto.width
        x = (ancho_px - total) // 2
        base = y + max(marca.height, texto.height)
        lienzo.paste(marca, (x, base - marca.height))
        lienzo.paste(texto, (x + marca.width + separacion, base - texto.height))
        y = base
    y += _mm_a_px(HUECO_LOGO_MM)

    fuente_precio = _fuente("negrita", _mm_a_px(6.2))
    entero = int(Decimal(producto.precio_venta).quantize(Decimal("1")))
    texto_precio = f"\u20a1{entero:,}".replace(",", ".")
    while (fuente_precio.size > _mm_a_px(3)
           and pincel.textlength(texto_precio, font=fuente_precio) > util):
        fuente_precio = _fuente("negrita", fuente_precio.size - 2)
    centrar_texto(texto_precio, fuente_precio, y)
    y += int(fuente_precio.size * 1.02) + _mm_a_px(HUECO_PRECIO_MM)

    barras = imagen_codigo_barras(str(producto.codigo_barras),
                                  settings.ETIQUETA_ANCHO_MM, _mm_a_px(ALTO_BARRAS_MM))
    limite = ancho_px - 2 * _mm_a_px(0.5)
    if barras.width > limite:
        barras = barras.resize((limite, max(1, int(barras.height * limite / barras.width))),
                               Image.LANCZOS)
    centrar_imagen(barras, y)
    y += barras.height

    fuente_codigo = _fuente("normal", _mm_a_px(2.3))
    centrar_texto(str(producto.codigo_barras), fuente_codigo, y)
    y += int(fuente_codigo.size * 1.15) + _mm_a_px(HUECO_DESC_MM)

    fuente_desc = _fuente("normal", _mm_a_px(2.1))
    alto_renglon = int(fuente_desc.size * 1.14)
    caben = max(1, (tope - y) // alto_renglon)
    renglones = _envolver(producto.nombre, fuente_desc, util, min(2, caben))
    y += max(0, ((tope - y) - alto_renglon * len(renglones)) // 2)
    for renglon in renglones:
        centrar_texto(renglon, fuente_desc, y)
        y += alto_renglon

    return lienzo.convert("RGB")


@dataclass
class Muestra:
    nombre: str = "Arenero Cuadrado Semicerrado con Pala"
    codigo_barras: str = "7852052794412"
    precio_venta: Decimal = Decimal("18500")


if __name__ == "__main__":
    muestra = Muestra()
    for etiqueta_nombre, con_marca in (("A (solo texto)", False), ("B (logo completo)", True)):
        imagen = dibujar(muestra, con_marca)
        print(f"Opcion {etiqueta_nombre}: lienzo {imagen.size}")
        windows.imprimir_imagen(
            settings.IMPRESORA_ETIQUETAS, imagen,
            settings.ETIQUETA_ANCHO_MM, settings.ETIQUETA_ALTO_MM,
            f"Comparacion etiqueta {etiqueta_nombre}",
        )
        print(f"  -> enviada")
    print("Listo: deberian salir DOS etiquetas, primero la A y luego la B.")
