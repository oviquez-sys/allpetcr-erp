"""Dibuja la etiqueta de producto de 44,5 × 31,8 mm para la Xprinter XP-360B.

Se dibuja como imagen y se manda por el driver de Windows. El camino de
comandos crudos (TSPL/ZPL/EPL) se probó el 05/09/2026 con esta impresora y no
imprimió nada: la XP-360B solo responde por el driver. Ver `windows.py`.

De arriba abajo lleva: el logo de AllPetcr.com, el precio en grande, el código
de barras con su número debajo y la descripción corta del producto. Ese orden
lo eligió Oscar el 09/09/2026 copiando la etiqueta de fábrica de un proveedor:
el logo manda, el precio es lo que el cliente busca en la góndola y el nombre
va al final porque quien lo necesita ya tiene el producto en la mano.

El código es el mismo `Producto.codigo_barras` que el POS busca al escanear,
así que lo que se pega en el producto es exactamente lo que la caja reconoce.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import barcode

from . import logotipo

# 203 puntos por pulgada es la resolución de esta familia de impresoras
# térmicas. Dibujar a esa misma resolución evita que Windows tenga que
# reescalar el mapa de bits, que es lo que ensucia las barras finas.
PUNTOS_POR_PULGADA = 203
MARGEN_MM = 1.5
# Aire sobre el nombre. Más que el margen lateral porque la impresora no corta
# exactamente en el borde de la etiqueta: con 1,5 mm el nombre quedaba pegado
# al filo y se veía descentrado hacia arriba (Oscar, 05/09/2026).
MARGEN_SUPERIOR_MM = 2.2
# Tope duro de ancho para el símbolo. Solo actúa en el caso extremo de un
# código larguísimo; el ancho normal lo decide la zona de silencio.
MARGEN_CODIGO_MM = 0.5
# Aire debajo del precio. Menor que el margen superior a propósito: el precio
# es lo último y no necesita tanto respiro como el nombre.
MARGEN_INFERIOR_MM = 1.0

# Blanco a cada lado del símbolo, medido en módulos. La norma pide 10; sin ese
# blanco muchos lectores ni siquiera intentan leer.
MODULOS_DE_SILENCIO = 10
# Mínimo al que se baja antes de rendirse a la barra de un solo punto.
#
# Por qué existe esta segunda vuelta (05/09/2026): un código de 13 dígitos son
# 123 módulos en Code128. En el rollo de 35 mm que se usaba entonces, exigiendo
# los 10 módulos de silencio, no cabían barras de 2 puntos y había que bajar a
# 1 (0,125 mm) — y ESO la pistola no lo lee; se comprobó en papel con un
# producto real.
#
# Con el rollo de 44,5 mm (08/09/2026) ningún código del catálogo necesita esta
# rebaja: todos entran con la zona de silencio completa. Se deja igual como red
# de seguridad para un código futuro más largo, porque entre un silencio un
# poco corto y unas barras que nadie lee, gana el silencio corto: alrededor del
# símbolo igual queda el blanco de la etiqueta y del papel de atrás.
MODULOS_DE_SILENCIO_MINIMO = 7

# --- Reparto vertical de la etiqueta, en milímetros ---
# Alturas fijas en vez de proporciones: así todas las etiquetas del rollo se
# ven iguales aunque un nombre ocupe dos renglones y otro uno.
ALTO_LOGO_MM = 4.4          # alto del logotipo (la P sale 1,45 veces más alta)
ALTO_BARRAS_MM = 9.5        # alto del símbolo, sin contar el número
HUECO_LOGO_MM = 0.3         # logo -> precio
HUECO_PRECIO_MM = 0.7       # precio -> barras
HUECO_DESCRIPCION_MM = 0.6  # número -> descripción
SEPARACION_LOGO_MM = 1.1    # aire entre la P y la palabra AllPetcr.com

# Fuentes de Windows. Se buscan por ruta porque Pillow no resuelve nombres de
# fuente; si no están (máquina de pruebas, Linux), se cae a la que trae
# python-barcode y, en última instancia, a la de Pillow.
_FUENTES = {
    "normal": [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"],
    "negrita": [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf"],
}


def _mm_a_px(mm: float, ppp: int = PUNTOS_POR_PULGADA) -> int:
    return int(round(mm / 25.4 * ppp))


def _fuente(estilo: str, tamano: int):
    from PIL import ImageFont

    for ruta in _FUENTES[estilo]:
        if Path(ruta).exists():
            return ImageFont.truetype(ruta, tamano)
    respaldo = Path(barcode.__file__).parent / "fonts" / "DejaVuSansMono.ttf"
    if respaldo.exists():
        return ImageFont.truetype(str(respaldo), tamano)
    return ImageFont.load_default()


def _envolver(texto: str, fuente, ancho_px: int, max_renglones: int) -> list[str]:
    """Parte el nombre en renglones que quepan, midiendo con la fuente real."""
    from PIL import Image, ImageDraw

    medidor = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def ancho(t: str) -> float:
        return medidor.textlength(t, font=fuente)

    renglones: list[str] = []
    actual = ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if ancho(prueba) <= ancho_px or not actual:
            actual = prueba
        else:
            renglones.append(actual)
            actual = palabra
            if len(renglones) == max_renglones:
                actual = ""
                # Se marca el corte: un nombre truncado en seco parece el
                # nombre completo y confunde a quien busca el producto.
                renglones[-1] = renglones[-1] + "…"
                break
    if actual and len(renglones) < max_renglones:
        renglones.append(actual)
    # El último renglón se recorta con puntos suspensivos si aún se pasa: más
    # vale un nombre truncado que una etiqueta con el texto desbordado.
    if renglones and ancho(renglones[-1]) > ancho_px:
        recorte = renglones[-1]
        while recorte and ancho(recorte + "…") > ancho_px:
            recorte = recorte[:-1]
        renglones[-1] = recorte + "…"
    return renglones


def _simbologia(codigo: str):
    """Elige el lenguaje de barras más compacto que represente ESE código.

    Un EAN-13 legítimo son 95 módulos; el mismo número en Code128 son 123. En
    el rollo de 44,5 mm esos 28 módulos de diferencia son barras de 0,375 mm
    en vez de 0,25 mm: las dos se leen, pero cuanto más gruesa, más tolera la
    etiqueta arrugada o mal pegada. Así que cuando el código es un EAN de
    verdad se usa EAN.

    Comprobar el dígito verificador no es un lujo: si se dibujara como EAN un
    número que no lo es, la librería le corregiría el último dígito y la
    etiqueta terminaría con un código DISTINTO al que tiene el ERP — el lector
    leería un producto que no existe. Ante la duda, Code128, que representa
    cualquier texto tal cual.
    """
    if codigo.isdigit():
        for nombre, largo in (("ean13", 13), ("ean8", 8)):
            if len(codigo) == largo:
                try:
                    if barcode.get(nombre, codigo[:-1]).get_fullcode() == codigo:
                        return nombre, codigo[:-1]
                except Exception:
                    pass  # no era un EAN válido: sigue con Code128
    return "code128", codigo


def _puntos_por_barra(modulos: int, puntos_disponibles: int) -> int:
    """Ancho de barra en puntos ENTEROS de la impresora.

    Entero y no fraccionario porque cada barra tiene que caer justo sobre los
    puntos del cabezal. Si no, la impresora redondea unas para arriba y otras
    para abajo: se ve bien de lejos y el lector lo rechaza.

    Se busca el ancho más grande que quepa respetando la zona de silencio, y
    si con la zona completa solo alcanza para un punto, se prueba con la
    reducida antes de resignarse (ver MODULOS_DE_SILENCIO_MINIMO).
    """
    for silencio in (MODULOS_DE_SILENCIO, MODULOS_DE_SILENCIO_MINIMO):
        puntos = puntos_disponibles // (modulos + 2 * silencio)
        if puntos >= 2:
            return puntos
    return max(1, puntos_disponibles // (modulos + 2 * MODULOS_DE_SILENCIO))


def imagen_codigo_barras(codigo: str, ancho_mm: float, alto_px: int):
    """Solo las barras, recortadas al pixel, sin texto.

    `ancho_mm` es el ancho COMPLETO de la etiqueta: el blanco que queda a los
    lados del símbolo ES la zona de silencio, y es blanco de la etiqueta, así
    que no hace falta reservarlo aparte.

    El texto legible lo dibuja `imagen_etiqueta`: python-barcode lo coloca por
    su cuenta y termina montado encima de las barras.
    """
    from barcode.writer import ImageWriter
    from PIL import ImageOps

    codigo = str(codigo)
    nombre, dato = _simbologia(codigo)
    modulos = len(barcode.get(nombre, dato).build()[0])

    punto_mm = 25.4 / PUNTOS_POR_PULGADA
    puntos_por_barra = _puntos_por_barra(modulos, _mm_a_px(ancho_mm))
    # El +0,000001 mm no es superstición: sin él, `puntos * punto_mm` vuelve a
    # píxeles como 0,9999 por el redondeo binario, y python-barcode dibuja un
    # rectángulo de ancho negativo y revienta. Un micrómetro de más no cambia
    # nada en papel y deja la cuenta del lado seguro.
    ancho_barra = puntos_por_barra * punto_mm + 1e-6

    escritor = ImageWriter()
    escritor.dpi = PUNTOS_POR_PULGADA
    imagen = barcode.get(nombre, dato, writer=escritor).render({
        "module_width": ancho_barra,
        "module_height": alto_px / PUNTOS_POR_PULGADA * 25.4,
        "quiet_zone": 0.0,        # el blanco lo pone la etiqueta
        "write_text": False,
        "background": "white",
        "foreground": "black",
    })
    # Recorte al contenido: el escritor deja márgenes propios que descuadran
    # cualquier cuenta de posición hecha desde afuera.
    caja = ImageOps.invert(imagen.convert("L")).getbbox()
    if caja:
        imagen = imagen.crop(caja)
    return imagen


def imagen_etiqueta(producto, ancho_mm: float = 44.5, alto_mm: float = 31.8,
                    con_precio: bool = True):
    """Devuelve la etiqueta lista para imprimir (imagen de Pillow).

    De arriba abajo: logo, precio en grande, barras, el número del código
    —para poder teclearlo si el lector falla— y la descripción corta.

    Los cuatro primeros bloques van anclados arriba con separaciones fijas y la
    descripción se centra en lo que sobra hasta el borde de abajo. Es lo que
    hace que dos etiquetas seguidas se vean de la misma familia aunque una
    tenga nombre de un renglón y la otra de dos.
    """
    from PIL import Image, ImageDraw

    ancho_px = _mm_a_px(ancho_mm)
    alto_px = _mm_a_px(alto_mm)
    margen_px = _mm_a_px(MARGEN_MM)
    util_px = ancho_px - 2 * margen_px

    lienzo = Image.new("L", (ancho_px, alto_px), 255)
    pincel = ImageDraw.Draw(lienzo)

    def centrar_texto(texto, fuente, y):
        ancho_texto = pincel.textlength(texto, font=fuente)
        pincel.text(((ancho_px - ancho_texto) / 2, y), texto, font=fuente, fill=0)

    def centrar_imagen(imagen, y):
        lienzo.paste(imagen, ((ancho_px - imagen.width) // 2, y))

    y = _mm_a_px(MARGEN_SUPERIOR_MM)
    tope = alto_px - _mm_a_px(MARGEN_INFERIOR_MM)

    # --- 1. Logo: la P y la palabra, alineadas por abajo ---
    alto_logo = _mm_a_px(ALTO_LOGO_MM)
    bloque = logotipo.bloque(alto_logo, _mm_a_px(SEPARACION_LOGO_MM), util_px)
    if bloque is not None:
        centrar_imagen(bloque, y)
        y += bloque.height
    else:
        # Sin los archivos del logo, el nombre de la tienda en letra: la
        # etiqueta sigue sirviendo aunque no se vea la marca.
        fuente_respaldo = _fuente("negrita", alto_logo)
        centrar_texto("AllPetcr.com", fuente_respaldo, y)
        y += int(fuente_respaldo.size * 1.05)
    y += _mm_a_px(HUECO_LOGO_MM)

    # --- 2. Precio, en el lugar donde el fabricante pone la referencia ---
    # Es lo que el cliente lee de lejos, en la góndola: el elemento que más
    # tamaño merece de toda la etiqueta.
    if con_precio:
        fuente_precio = _fuente("negrita", _mm_a_px(6.2))
        entero = int(Decimal(producto.precio_venta).quantize(Decimal("1")))
        texto_precio = f"₡{entero:,}".replace(",", ".")
        # Un precio de siete cifras (₡1.250.000) con la letra grande no cabe a
        # lo ancho. Se achica lo justo para que entre, en vez de salirse.
        while (fuente_precio.size > _mm_a_px(3)
               and pincel.textlength(texto_precio, font=fuente_precio) > util_px):
            fuente_precio = _fuente("negrita", fuente_precio.size - 2)
        centrar_texto(texto_precio, fuente_precio, y)
        y += int(fuente_precio.size * 1.02) + _mm_a_px(HUECO_PRECIO_MM)

    # --- 3. Barras de alto fijo, con el número pegado debajo ---
    barras = imagen_codigo_barras(
        str(producto.codigo_barras), ancho_mm, _mm_a_px(ALTO_BARRAS_MM))
    # Red de seguridad: si el trazado quedó más ancho que la etiqueta (código
    # larguísimo), se reduce en vez de desbordar.
    limite = ancho_px - 2 * _mm_a_px(MARGEN_CODIGO_MM)
    if barras.width > limite:
        barras = barras.resize(
            (limite, max(1, int(barras.height * limite / barras.width))), Image.LANCZOS
        )
    centrar_imagen(barras, y)
    y += barras.height

    fuente_codigo = _fuente("normal", _mm_a_px(2.3))
    centrar_texto(str(producto.codigo_barras), fuente_codigo, y)
    y += int(fuente_codigo.size * 1.15) + _mm_a_px(HUECO_DESCRIPCION_MM)

    # --- 4. Descripción corta, centrada en el espacio que sobra ---
    fuente_desc = _fuente("normal", _mm_a_px(2.1))
    alto_renglon = int(fuente_desc.size * 1.14)
    caben = max(1, (tope - y) // alto_renglon)
    renglones = _envolver(producto.nombre, fuente_desc, util_px, min(2, caben))
    y += max(0, ((tope - y) - alto_renglon * len(renglones)) // 2)
    for renglon in renglones:
        centrar_texto(renglon, fuente_desc, y)
        y += alto_renglon

    return lienzo.convert("RGB")
