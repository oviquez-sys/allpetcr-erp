"""Divisiones del negocio (26/09/2026): Alimentos para perro, Alimentos para
gato y Accesorios.

Oscar pidió ver alimentos como una línea de negocio aparte, separada por
especie. No es otra categoría: el árbol ya tiene "Alimento" (seco, húmedo) y
"Snacks y premios", y la especie ya vive en `Producto.mascota`. Meter
"Perro"/"Gato" como subcategorías duplicaría ese dato y obligaría a elegir
entre "seco" y "perro" para un mismo producto (un producto vive en UNA
categoría — ver el árbol de categorías). La división se DERIVA de los dos
datos que ya existen, en un solo lugar: esta función.
"""
from django.db.models import Case, CharField, Q, Value, When

RAICES_ALIMENTO = ("Alimento", "Snacks y premios")

ALIMENTO_PERRO = "Alimentos para perro"
ALIMENTO_GATO = "Alimentos para gato"
ALIMENTO_OTRO = "Alimentos (otras mascotas)"
ACCESORIOS = "Accesorios y otros"
ORDEN = [ALIMENTO_PERRO, ALIMENTO_GATO, ALIMENTO_OTRO, ACCESORIOS]


def division(raiz, mascota):
    """División de un producto a partir de su categoría raíz y su mascota.

    "Perro y gato" cuenta como perro: en alimento casi no existe, y partirlo
    en dos filas inventaría un reparto que nadie midió."""
    if raiz not in RAICES_ALIMENTO:
        return ACCESORIOS
    if mascota in ("Perro", "Perro y gato"):
        return ALIMENTO_PERRO
    if mascota == "Gato":
        return ALIMENTO_GATO
    return ALIMENTO_OTRO


def anotar_division(prefijo=""):
    """La misma regla como expresión de base de datos, para agrupar consultas.
    `prefijo` es la ruta hasta el producto, ej. "producto__"."""
    raiz_es_alimento = (Q(**{f"{prefijo}categoria__padre__nombre__in": RAICES_ALIMENTO})
                        | Q(**{f"{prefijo}categoria__padre__isnull": True,
                               f"{prefijo}categoria__nombre__in": RAICES_ALIMENTO}))
    mascota = f"{prefijo}mascota"
    return Case(
        When(raiz_es_alimento & Q(**{f"{mascota}__in": ("Perro", "Perro y gato")}), then=Value(ALIMENTO_PERRO)),
        When(raiz_es_alimento & Q(**{mascota: "Gato"}), then=Value(ALIMENTO_GATO)),
        When(raiz_es_alimento, then=Value(ALIMENTO_OTRO)),
        default=Value(ACCESORIOS), output_field=CharField(),
    )
