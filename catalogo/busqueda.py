"""Ayuda compartida para los buscadores de producto por palabras sueltas.

Nace el 28/09/2026 de un problema concreto: al cargar una compra, el nombre
del producto se arma pegando marca + nombre de factura + presentación
("Balance Ad Cat Chicken" + "10 kg" -> "Balance Ad Cat Chicken 10 kg", ver
`claude/compra-belina-26-09.md`), y la presentación siempre lleva un espacio
entre el número y la unidad. Oscar, al escribir rápido, escribe "10kg" sin
espacio -- y "10kg" no es una subcadena de "10 kg", así que no encontraba
nada aunque el producto exista.

`formas_de_palabra` da, para una palabra buscada, todas las formas contra las
que vale la pena comparar: la palabra tal cual, y si es un número pegado a
una unidad de peso conocida, también esa misma palabra con un espacio antes
de la unidad. Así "10kg" también encuentra "10 kg".

La dirección contraria (escribir "10 kg" con espacio y que encuentre un
"10kg" sin espacio en el texto) no necesita ayuda extra: como cada palabra
buscada ya se exige por separado (ver `buscar_producto` en
`core/chat_tools.py` y `precios` en `catalogo/views.py`), "10" y "kg" son
cada una subcadena de "10kg" y las dos coinciden solas.
"""
import re

# Mismas unidades que catalogo.models.Producto.UnidadPeso, salvo "un"
# (unidad): esa no se escribe pegada a un número dentro de un nombre
# ("5un" no es una forma real de escribir "5 unidades"), así que incluirla
# no ayudaría y sí podría disparar de más.
UNIDADES_DE_PESO = ("kg", "g", "lb", "oz", "ml", "l")

_PATRON_NUMERO_UNIDAD = re.compile(
    r"^(\d+(?:[.,]\d+)?)(" + "|".join(UNIDADES_DE_PESO) + r")$",
    re.IGNORECASE,
)


def formas_de_palabra(palabra):
    """Lista de formas de texto contra las que comparar esta palabra.

    Para casi toda palabra es ella misma, sola. Para "10kg", "2.5lb", etc.
    (número pegado a una unidad de peso conocida) también incluye la forma
    con espacio ("10 kg", "2.5 lb"), que es como el ERP arma el nombre a
    partir de la presentación.
    """
    coincidencia = _PATRON_NUMERO_UNIDAD.match(palabra)
    if not coincidencia:
        return [palabra]
    numero, unidad = coincidencia.groups()
    return [palabra, f"{numero} {unidad}"]
