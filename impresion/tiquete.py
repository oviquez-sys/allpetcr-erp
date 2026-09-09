"""Arma el tiquete de venta en ESC/POS para la térmica de 80 mm.

Por qué ESC/POS y no una imagen ni el navegador: la impresora entiende este
lenguaje de forma nativa, así que el tiquete sale en menos de un segundo, con
letra nítida y cortando el papel sola. Imprimir por el navegador obliga al
cajero a pasar por el diálogo de impresión en cada venta, y una imagen tarda
varios segundos con el cliente esperando.

El ancho en caracteres es configurable (`ANCHO_TIQUETE`) porque no todas las
térmicas de 80 mm traen las mismas columnas: 48 es lo habitual, algunas son
42. Si el tiquete sale con renglones partidos, se baja ese número.
"""
from __future__ import annotations

from decimal import Decimal

from . import logotipo

# --- Comandos ESC/POS ---
INICIALIZAR = b"\x1b\x40"
CODIGOS_CP850 = b"\x1b\x74\x02"      # tabla de caracteres con acentos y ¢
IZQUIERDA = b"\x1b\x61\x00"
CENTRO = b"\x1b\x61\x01"
DERECHA = b"\x1b\x61\x02"
NEGRITA_ON = b"\x1b\x45\x01"
NEGRITA_OFF = b"\x1b\x45\x00"
DOBLE = b"\x1d\x21\x11"              # doble ancho y doble alto
NORMAL = b"\x1d\x21\x00"
SALTO = b"\n"
# Corte parcial dejando avanzar el papel: deja el tiquete listo para arrancar
# sin que se corte el último renglón.
CORTAR = b"\x1d\x56\x42\x00"
# Imagen de trama: GS v 0 m xL xH yL yH [datos]. m=0 es tamaño normal.
IMAGEN_DE_TRAMA = b"\x1d\x76\x30\x00"


def bytes_logo(ancho_puntos: int = 384, ancho_papel: int = 576) -> bytes:
    """El logotipo como imagen de trama ESC/POS. Vacío si no se puede armar.

    Por qué mandar la trama en cada tiquete y no usar el «logo NV» de la
    impresora (`FS p`): el logo NV hay que grabarlo en la memoria flash del
    aparato con la herramienta del fabricante, y el día que se cambie de
    impresora —o que alguien la resetee— el recibo sale sin logo y nadie sabe
    por qué. La trama son unos 5 KB por USB: instantáneo, y el logo vive en el
    repositorio junto con el resto del sistema.

    El logo se rellena con blanco hasta el ancho del papel en vez de usar
    `ESC a 1` para centrarlo, porque no todos los firmwares respetan la
    alineación cuando lo que sigue es una imagen. Rellenando, queda centrado
    sin depender de eso.

    Devuelve `b""` si faltan los PNG o si Pillow no está instalado: un recibo
    sin logo se entrega igual; una venta que no se puede cobrar, no.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - depende del entorno
        return b""

    # El ancho en bytes tiene que ser entero, así que el papel se redondea
    # hacia abajo al múltiplo de 8 más cercano.
    ancho_papel -= ancho_papel % 8
    ancho_puntos = min(ancho_puntos, ancho_papel)
    imagen = logotipo.bloque_de_ancho(ancho_puntos)
    if imagen is None:
        return b""

    lienzo = Image.new("L", (ancho_papel, imagen.height), 255)
    lienzo.paste(imagen, ((ancho_papel - imagen.width) // 2, 0))

    # En modo "1" cada fila viene empaquetada de 8 en 8 con el bit más
    # significativo a la izquierda, que es justo lo que espera GS v 0. Se
    # invierte antes porque ahí el bit encendido significa «imprimir», y en la
    # imagen el negro es el valor bajo.
    trama = lienzo.point(lambda v: 255 if v < 128 else 0, mode="1")
    datos = trama.tobytes()

    ancho_bytes = ancho_papel // 8
    alto = lienzo.height
    cabecera = bytes([ancho_bytes % 256, ancho_bytes // 256, alto % 256, alto // 256])
    return IMAGEN_DE_TRAMA + cabecera + datos


def _texto(cadena: str) -> bytes:
    """Pasa el texto a la tabla de caracteres de la impresora.

    El símbolo del colón (₡) no existe en ninguna tabla de las térmicas; se
    sustituye por ¢, que sí está en CP850 y es lo que usa el comercio. Si
    algún carácter raro no se puede representar, se reemplaza en vez de
    reventar la venta."""
    cadena = cadena.replace("₡", "¢")
    try:
        return cadena.encode("cp850", errors="replace")
    except LookupError:  # pragma: no cover - Python siempre trae cp850
        return cadena.encode("ascii", errors="replace")


def _monto(valor) -> str:
    """Formato de dinero de Costa Rica: punto para miles, sin decimales.

    Sin decimales a propósito: los precios de la tienda son enteros y una
    columna más corta deja más espacio para el nombre del producto."""
    entero = int(Decimal(valor).quantize(Decimal("1")))
    return f"¢{entero:,}".replace(",", ".")


def _dos_columnas(izquierda: str, derecha: str, ancho: int) -> str:
    """Renglón con la etiqueta a la izquierda y el monto pegado a la derecha."""
    espacio = ancho - len(derecha)
    if espacio < 1:
        return derecha[:ancho]
    return f"{izquierda[:espacio - 1]:<{espacio}}{derecha}"


def _envolver(texto: str, ancho: int) -> list[str]:
    """Corta un nombre largo en varios renglones sin partir palabras."""
    palabras = texto.split()
    renglones: list[str] = []
    actual = ""
    for palabra in palabras:
        if not actual:
            actual = palabra[:ancho]
        elif len(actual) + 1 + len(palabra) <= ancho:
            actual = f"{actual} {palabra}"
        else:
            renglones.append(actual)
            actual = palabra[:ancho]
    if actual:
        renglones.append(actual)
    return renglones or [""]


def bytes_tiquete(factura, ancho: int = 48, pie: str = "", logo: bytes = b"") -> bytes:
    """Devuelve el tiquete completo listo para mandar a la impresora.

    `logo` es la imagen de trama que devuelve `bytes_logo`. Se recibe armada en
    vez de armarla aquí para que este módulo siga sin depender de settings ni
    de Pillow: así el tiquete se puede probar entero sin nada instalado.
    """
    partes: list[bytes] = [INICIALIZAR, CODIGOS_CP850, CENTRO]

    empresa = factura.empresa
    if logo:
        # Con logo, el nombre legal va debajo en letra normal: sigue haciendo
        # falta en el comprobante, pero el que manda arriba es el logo.
        partes += [logo, SALTO, NEGRITA_ON, _texto(empresa.nombre), NEGRITA_OFF, SALTO]
    else:
        partes += [NEGRITA_ON, DOBLE, _texto(empresa.nombre), NORMAL, NEGRITA_OFF, SALTO]
    if getattr(empresa, "identificacion", ""):
        partes += [_texto(f"Cedula: {empresa.identificacion}"), SALTO]
    partes += [_texto(factura.sucursal.nombre), SALTO]
    partes += [_texto(f"{factura.creado_en:%d/%m/%Y %I:%M %p}"), SALTO]
    partes += [NEGRITA_ON, _texto(factura.numero), NEGRITA_OFF,
               _texto(f"  {factura.get_medio_pago_display()}"), SALTO]
    if factura.cliente_id:
        partes += [_texto(str(factura.cliente)), SALTO]
    if factura.estado == "ANU":
        partes += [SALTO, NEGRITA_ON, DOBLE, _texto("* ANULADA *"), NORMAL, NEGRITA_OFF, SALTO]
        if factura.motivo_anulacion:
            partes += [_texto(factura.motivo_anulacion[:ancho]), SALTO]

    partes += [IZQUIERDA, _texto("-" * ancho), SALTO]

    for linea in factura.lineas.all():
        nombre = linea.producto.nombre
        if linea.es_regalia:
            nombre = f"{nombre} (REGALO)"
        for renglon in _envolver(nombre, ancho):
            partes += [_texto(renglon), SALTO]
        if linea.es_regalia:
            detalle = _dos_columnas(f"  {linea.cantidad:g} x REGALO", _monto(0), ancho)
        else:
            detalle = _dos_columnas(
                f"  {linea.cantidad:g} x {_monto(linea.precio_unitario)}",
                _monto(linea.total), ancho,
            )
        partes += [_texto(detalle), SALTO]
        if not linea.es_regalia and linea.descuento_pct > 0:
            partes += [_texto(_dos_columnas(
                f"    descuento {linea.descuento_pct:g}%",
                f"-{_monto(linea.descuento_monto)}", ancho)), SALTO]

    partes += [_texto("-" * ancho), SALTO]
    if factura.impuesto > 0:
        partes += [_texto(_dos_columnas("Subtotal", _monto(factura.subtotal), ancho)), SALTO]
        partes += [_texto(_dos_columnas("IVA", _monto(factura.impuesto), ancho)), SALTO]
    if factura.descuento > 0:
        partes += [_texto(_dos_columnas("Descuentos", f"-{_monto(factura.descuento)}", ancho)), SALTO]
    partes += [NEGRITA_ON, DOBLE,
               _texto(_dos_columnas("TOTAL", _monto(factura.total), ancho // 2)),
               NORMAL, NEGRITA_OFF, SALTO, SALTO]

    partes += [CENTRO, _texto("Gracias por su compra"), SALTO]
    partes += [_texto("www.allpetcr.com"), SALTO, SALTO]
    if pie:
        for renglon in _envolver(pie, ancho):
            partes += [_texto(renglon), SALTO]
    partes += [SALTO, SALTO, CORTAR]
    return b"".join(partes)
