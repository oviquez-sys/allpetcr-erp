"""Generación de etiquetas con código de barras (Code128) para imprimir.

Cada etiqueta lleva nombre, código de barras escaneable y precio. Se arma
como página HTML con el código de barras en SVG embebido (sin depender de
internet), lista para imprimir desde el navegador (Ctrl+P) en hojas de
etiquetas adhesivas.
"""
import re
from io import BytesIO

import barcode
from barcode.writer import SVGWriter

# Quita el encabezado XML/DOCTYPE para poder embeber el <svg> dentro del HTML.
_XML_HEADER = re.compile(r"<\?xml.*?\?>\s*<!DOCTYPE.*?>\s*", re.DOTALL)


def svg_barcode(codigo: str) -> str:
    """Devuelve el SVG (como texto) de un código de barras Code128."""
    if not codigo:
        return ""
    buf = BytesIO()
    barcode.get("code128", str(codigo), writer=SVGWriter()).write(
        buf,
        options={
            "module_width": 0.28,   # ancho de barra (mm)
            "module_height": 12.0,  # alto de barras (mm)
            "font_size": 8,
            "text_distance": 3.0,
            "quiet_zone": 2.0,
        },
    )
    svg = buf.getvalue().decode("utf-8")
    return _XML_HEADER.sub("", svg).strip()
