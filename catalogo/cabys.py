"""Código CABYS de cada producto, asignado por categoría (21/09/2026).

QUÉ ES Y POR QUÉ HACE FALTA
---------------------------
El CABYS es el Catálogo de Bienes y Servicios de Hacienda: 13 dígitos que
dicen QUÉ se vendió. En régimen tradicional cada línea de la factura
electrónica lo lleva, y Hacienda la rechaza si el código no existe. De ahí
sale también la tarifa del IVA.

DE DÓNDE SALEN ESTOS CÓDIGOS
----------------------------
Cada código de `CODIGOS` se consultó uno por uno el 21/09/2026 en la API
oficial de Hacienda (api.hacienda.go.cr/fe/cabys?codigo=...), y la
descripción que se guarda es la oficial, copiada tal cual. Todos llevan
13 %, igual que la tarifa que ya usa el ERP: asignarlos no cambia ni un
colón de ningún precio ni del IVA.

POR QUÉ POR CATEGORÍA Y NO PRODUCTO POR PRODUCTO
-------------------------------------------------
El CABYS clasifica por lo que ES el bien (comida, talabartería, artículo de
plástico…), y el árbol de categorías del ERP ya agrupa casi igual. Donde una
misma categoría mezcla bienes distintos —en "Higiene y aseo" hay champú y
hay cepillos— se decide por palabras del nombre (`_REGLAS`).

Cambió la regla del 28/08 ("nadie lo adivina"): Oscar pidió el 21/09 que se
cargaran ya. Lo que se mantiene de aquella regla es lo importante:
- Solo se usan códigos verificados en Hacienda, nunca uno inventado.
- Un CABYS que alguien ya puso a mano NO se toca (salvo `--reemplazar`).
- Cada código lleva su nivel de CONFIANZA, y el Excel que genera
  `asignar_cabys` es para que el contador revise los de confianza media o
  baja. Él tiene la última palabra; si corrige uno, se cambia en el admin
  del producto y este comando ya no lo pisa.
"""
import unicodedata
from dataclasses import dataclass

ALTA, MEDIA, BAJA = "alta", "media", "baja"

# Código → descripción oficial de Hacienda (copiada tal cual, 21/09/2026).
CODIGOS = {
    "2331100000200": "Comida para perros y gatos, presentada para venta al por menor",
    "2331100000100": "Comida preparada para perros y gatos, envasada herméticamente",
    "2331901000100": "Alimentos preparados para peces de acuario",
    "3856000009900": "Juguetes, n.c.p.",
    "2921001000000": ("Artículos de talabartería y guarnicionería para toda clase de animales, "
                      "de cualquier material (bozales, arneses, orejeras, correas, sillas de "
                      "montar, mantas para caballos, entre otros)"),
    "3466100990400": "Collar para animales con insecticida",
    "2921099000000": "Prendas y accesorios de vestir, para mascotas, n.c.p.",
    "3694000999900": "Artículos de plástico, de uso doméstico y de tocador, n.c.p.",
    "4291201019900": "Artículos y sus partes, de uso doméstico, de acero inoxidable, n.c.p.",
    "3722199990000": "Artículos de uso doméstico y tocador, de cerámica n.c.p.",
    "2718000009900": "Cojines, pufs y artículos similares, con resortes o relleno",
    "3532307009900": "Productos de higiene para animales, n.c.p.",
    "3532307000100": "Jabón para animales",
    "3532307000200": "Champú para animales",
    "3532307000300": "Acondicionador para animales",
    "3532307000400": "Talco para animales",
    "3532307000500": "Perfume para animales",
    "3532307000600": "Productos de higiene dental para animales",
    "3899302029900": "Cepillos con mango, n.c.p.",
    "3699099999900": "Artículos plásticos, n.c.p.",
    "3564099000000": "Medicamentos, de uso veterinario, n.c.p.",
    "3564008000000": "Parasiticidas externos e internos, de uso veterinario",
    "1540002009900": "Bentonita n.c.p.",
    "3814001999900": "Muebles de otros materiales, n.c.p.",
    "2922002990000": "Bolsas de mano o carteras, de otros materiales, n.c.p.",
    "4323001010000": "Bombas de aire",
}


@dataclass(frozen=True)
class Propuesta:
    codigo: str
    confianza: str
    motivo: str

    @property
    def descripcion(self):
        return CODIGOS[self.codigo]


def _normal(texto):
    """minúsculas y sin tildes: 'Champú' y 'CHAMPU' tienen que dar igual."""
    texto = unicodedata.normalize("NFKD", texto or "").lower()
    return "".join(c for c in texto if not unicodedata.combining(c))


# Reglas por palabra del NOMBRE, dentro de cada raíz. La primera que calza
# gana, así que las más específicas van primero ("collar antipulgas" antes
# que "antipulgas"). Las palabras ya van sin tilde.
_REGLAS = {
    "Paseo": [
        (("antipulga", "insecticida", "antigarrapata"), "3466100990400", ALTA, "collar con insecticida"),
    ],
    "Comederos y bebederos": [
        (("acero", "inoxidable", "metal"), "4291201019900", MEDIA, "comedero de acero"),
        (("ceramica", "porcelana"), "3722199990000", MEDIA, "comedero de cerámica"),
    ],
    "Higiene y aseo": [
        (("champu", "shampoo"), "3532307000200", ALTA, "champú"),
        (("acondicionador",), "3532307000300", ALTA, "acondicionador"),
        (("jabon",), "3532307000100", ALTA, "jabón"),
        (("talco",), "3532307000400", ALTA, "talco"),
        (("perfume", "colonia", "fragancia"), "3532307000500", ALTA, "perfume"),
        (("dental", "dientes", "pasta de"), "3532307000600", ALTA, "higiene dental"),
        (("cepillo", "peine", "carda", "rastrillo", "deslanador", "quitapelo"),
         "3899302029900", MEDIA, "cepillo o peine"),
        (("bolsa",), "3699099999900", BAJA, "bolsas plásticas"),
    ],
    "Salud y cuidado": [
        (("collar",), "3466100990400", MEDIA, "collar (revisar si trae insecticida)"),
        (("pulga", "garrapata", "desparasit", "parasit", "antipulga"),
         "3564008000000", ALTA, "antiparasitario"),
    ],
    "Arena y sanitarios": [
        (("arena", "bentonita", "aglomerante", "silica"), "1540002009900", MEDIA, "arena sanitaria"),
    ],
    "Transporte": [
        (("bolso", "mochila", "bolsa"), "2922002990000", BAJA, "bolso transportador"),
    ],
    "Acuario": [
        (("alimento", "comida", "hojuela", "escama", "pellet"), "2331901000100", ALTA, "alimento para peces"),
        (("bomba", "oxigenador", "aireador"), "4323001010000", MEDIA, "bomba de aire"),
    ],
    "Alimento": [
        (("humedo", "lata", "sobre", "pouch", "pate"), "2331100000100", ALTA, "alimento húmedo"),
    ],
}

# Lo que se asigna cuando ninguna regla calzó: el código de la raíz.
_POR_RAIZ = {
    "Alimento": ("2331100000200", ALTA, "alimento para perro/gato"),
    "Snacks y premios": ("2331100000200", ALTA, "premio para perro/gato"),
    "Juguetes": ("3856000009900", MEDIA, "juguete"),
    "Paseo": ("2921001000000", ALTA, "collar, correa o arnés"),
    "Ropa y accesorios": ("2921099000000", ALTA, "ropa o accesorio de vestir"),
    "Comederos y bebederos": ("3694000999900", MEDIA, "comedero plástico"),
    "Descanso": ("2718000009900", MEDIA, "cama o cojín con relleno"),
    "Higiene y aseo": ("3532307009900", MEDIA, "producto de higiene"),
    "Salud y cuidado": ("3564099000000", BAJA, "producto de salud (revisar)"),
    "Arena y sanitarios": ("3694000999900", MEDIA, "arenero o accesorio plástico"),
    "Rascadores y muebles": ("3814001999900", BAJA, "rascador o mueble"),
    "Transporte": ("3694000999900", BAJA, "transportadora plástica"),
    "Acuario": ("3699099999900", BAJA, "accesorio de acuario"),
}

# Subcategorías cuyo nombre ya decide (van antes que las palabras del producto).
_POR_SUBCATEGORIA = {
    "Alimento húmedo": ("2331100000100", ALTA, "alimento húmedo"),
    "Alimento seco": ("2331100000200", ALTA, "alimento seco"),
}


def raiz_de(categoria):
    """Nombre de la categoría raíz (el árbol tiene dos niveles)."""
    if categoria is None:
        return None
    return categoria.padre.nombre if categoria.padre_id else categoria.nombre


def proponer(producto):
    """Propuesta de CABYS para un producto, o None si no hay cómo decidir
    (sin categoría, o una raíz que no está en la tabla)."""
    cat = producto.categoria
    if cat is None:
        return None
    if cat.nombre in _POR_SUBCATEGORIA:
        return Propuesta(*_POR_SUBCATEGORIA[cat.nombre])
    raiz = raiz_de(cat)
    # La subcategoría ayuda ("Antipulgas", "Champús"), la raíz no: si el
    # producto cuelga directo de "Arena y sanitarios", la palabra "arena" de
    # la raíz mandaría también los areneros plásticos a bentonita.
    subcategoria = cat.nombre if cat.padre_id else ""
    texto = _normal(f"{producto.nombre} {subcategoria}")
    for palabras, codigo, confianza, motivo in _REGLAS.get(raiz, []):
        if any(p in texto for p in palabras):
            return Propuesta(codigo, confianza, motivo)
    if raiz in _POR_RAIZ:
        return Propuesta(*_POR_RAIZ[raiz])
    return None
