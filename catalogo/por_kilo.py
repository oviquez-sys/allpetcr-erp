"""Precio por kilo (o por litro) de un producto.

Pedido de Oscar (19/10/2026, "experimento"): al consultar un alimento en la
pantalla de ventas, ver cuánto sale el kilo. Sirve para comparar bolsas de
distinto tamaño (la de 15 kg contra tres de 4 kg) y para explicarle al
cliente por qué la grande rinde más.

De dónde sale el contenido, en este orden:
1. `peso_valor` + `peso_unidad` del producto (lo que se escribe en Ajustes
   de inventario).
2. Si eso está vacío, la presentación cuando dice SOLO un peso ("15 kg",
   "500 g"). Es la misma regla estricta que ya usa `cargar_fichas_alimento`:
   "2 x 85 g" o "Bolsa 3 kg + 1 gratis" NO se interpretan, para no mostrar un
   precio por kilo equivocado. Nunca se adivina desde el nombre.

Solo para lo que se compara por peso: alimento, snacks y arena
(`RAICES_POR_KILO`, la categoría raíz) o lo que tenga ficha de alimento. Un
"One Suspensión 30 ml" a ₡300.000 el litro no le sirve a nadie.

El precio es el de venta CON IVA (lo que paga el cliente), redondeado a
colones enteros. Líquidos (l, ml) dan precio por litro; "unidad" no da nada.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

A_KILOS = {"kg": Decimal("1"), "g": Decimal("0.001"),
           "lb": Decimal("0.45359237"), "oz": Decimal("0.028349523125")}
A_LITROS = {"l": Decimal("1"), "ml": Decimal("0.001")}

RAICES_POR_KILO = {"Alimento", "Snacks y premios", "Arena y sanitarios"}

SOLO_PESO = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(kg|g|lb|oz|ml|l)\s*$", re.IGNORECASE)


def contenido(peso_valor, peso_unidad, presentacion=""):
    """(cantidad, "kg" | "l") del empaque, o None si no se sabe."""
    valor, unidad = peso_valor, (peso_unidad or "").lower()
    if not valor or unidad not in A_KILOS and unidad not in A_LITROS:
        m = SOLO_PESO.match(presentacion or "")
        if not m:
            return None
        valor, unidad = Decimal(m.group(1).replace(",", ".")), m.group(2).lower()
    valor = Decimal(str(valor))
    if valor <= 0:
        return None
    if unidad in A_KILOS:
        return valor * A_KILOS[unidad], "kg"
    return valor * A_LITROS[unidad], "l"


def precio_por_kilo(precio, peso_valor, peso_unidad, presentacion=""):
    """(colones enteros, "kg" | "l") o None."""
    c = contenido(peso_valor, peso_unidad, presentacion)
    if c is None or not precio or Decimal(str(precio)) <= 0:
        return None
    cantidad, unidad = c
    return int((Decimal(str(precio)) / cantidad).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), unidad


def aplica(categoria, categoria_padre="", tiene_ficha=False):
    """¿Tiene sentido mostrar precio por kilo en este producto?"""
    return bool(tiene_ficha) or (categoria_padre or categoria or "") in RAICES_POR_KILO
