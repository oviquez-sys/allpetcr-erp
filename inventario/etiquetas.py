"""Selección y generación de etiquetas con código de barras.

Dos consumidores con el mismo criterio:

- la pantalla `inventario:etiquetas`, que las dibuja en HTML para hojas
  adhesivas y para revisar antes de gastar rollo;
- `impresion:etiquetas`, que manda esa misma selección a la impresora de
  etiquetas.

Por eso la selección vive acá y no dentro de la vista: si cada pantalla
filtrara por su cuenta, tarde o temprano una imprimiría algo distinto de lo
que la otra muestra, y eso se descubre con el rollo ya gastado.
"""
import re
from dataclasses import dataclass, field
from io import BytesIO

import barcode
from barcode.writer import SVGWriter

from catalogo.consultas import productos_visibles

# Quita el encabezado XML/DOCTYPE para poder embeber el <svg> dentro del HTML.
_XML_HEADER = re.compile(r"<\?xml.*?\?>\s*<!DOCTYPE.*?>\s*", re.DOTALL)

# Máximo de etiquetas que una sola petición puede generar. Cubre cualquier
# tanda de impresión real; por encima de esto la página deja de ser imprimible
# y el navegador se traba, así que recortar es mejor servicio que cumplir.
TOPE_ETIQUETAS = 500


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


@dataclass
class Seleccion:
    """Qué etiquetas hay que sacar y por qué la lista quedó así."""

    pares: list = field(default_factory=list)   # [(Producto, copias)]
    faltan_codigo: int = 0
    recortado: bool = False
    # Filtros ya normalizados, para que la pantalla los devuelva al formulario
    # con el mismo valor que se usó de verdad (y no el texto crudo que llegó).
    copias: int = 1
    segun_stock: bool = False
    solo_faltantes: bool = False
    agotados: bool = False
    categoria: str = ""

    @property
    def total(self) -> int:
        return sum(copias for _, copias in self.pares)


def _entero(parametros, clave, defecto, minimo, maximo):
    try:
        return max(minimo, min(maximo, int(parametros.get(clave, defecto))))
    except (TypeError, ValueError):
        return defecto


def seleccionar_para_etiquetas(empresa, parametros) -> Seleccion:
    """Aplica los filtros de la pantalla de etiquetas.

    `parametros` es un QueryDict (request.GET en la pantalla, request.POST al
    imprimir): los nombres de los filtros son los mismos en los dos lados.

      categoria=<id>    solo esa familia (por defecto: todas)
      copias=<n>        n etiquetas por producto (por defecto 1)
      segun_stock=1     una etiqueta por unidad en existencia
      solo_faltantes=1  solo productos en o bajo el mínimo
      agotados=1        incluir también los que están sin existencias
    """
    solo_faltantes = bool(parametros.get("solo_faltantes"))
    # `solo_faltantes` levanta el filtro de existencias por su cuenta: un
    # producto en cero es el más faltante de todos, y filtrarlo antes dejaría
    # a "solo faltantes" mostrando justo lo que no falta.
    # Se compara contra "1" igual que `catalogo.consultas.pidio_agotados`, para
    # que el filtro signifique lo mismo en toda la aplicación.
    agotados = parametros.get("agotados") == "1" or solo_faltantes

    productos = (
        productos_visibles(empresa, incluir_agotados=agotados)
        .select_related("categoria")
        .order_by("nombre")
    )
    categoria = parametros.get("categoria")
    if categoria:
        productos = productos.filter(categoria_id=categoria)
    if solo_faltantes:
        productos = [p for p in productos if p.stock_actual <= p.stock_minimo]

    segun_stock = parametros.get("segun_stock") == "1"
    copias = _entero(parametros, "copias", 1, 1, 50)

    seleccion = Seleccion(
        copias=copias, segun_stock=segun_stock, solo_faltantes=solo_faltantes,
        agotados=agotados, categoria=categoria or "",
    )
    emitidas = 0
    for producto in productos:
        # Tope global: sin él, "una etiqueta por unidad en existencia" sobre un
        # producto con stock alto construye una página de cientos de MB que
        # tumba el proceso (medido: stock 99.999 => 207 MB en una sola
        # respuesta). El tope corta ahí y avisa, en vez de reventar.
        if emitidas >= TOPE_ETIQUETAS:
            seleccion.recortado = True
            break
        if not producto.codigo_barras:
            seleccion.faltan_codigo += 1
            continue
        pedidas = max(1, int(producto.stock_actual) if segun_stock else copias)
        n = min(pedidas, TOPE_ETIQUETAS - emitidas)
        if n < pedidas:
            seleccion.recortado = True
        if n <= 0:
            break
        seleccion.pares.append((producto, n))
        emitidas += n
    return seleccion
