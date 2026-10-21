"""Palabras de búsqueda de cada producto: lo que la gente escribe (20/10/2026).

Pedido de Oscar: que el buscador del ERP y del sitio sean "inteligentes":
"comida perro cachorro" tiene que mostrar todos los alimentos para cachorro
de perro, aunque ninguno diga "comida" en el nombre y la mitad diga "Puppy".

Cómo se resuelve
----------------
Toda la inteligencia vive ACÁ, en un solo lugar: a cada producto se le arma
un texto extra (`etiquetas`) con las palabras que la gente usaría para
encontrarlo, en español y en inglés, sacadas de:
- su categoría y la categoría madre ("Alimento seco" → comida, alimento,
  concentrado, croqueta…),
- la mascota (Perro → perro, dog, canino, perrito),
- su ficha técnica, si tiene (etapa, tamaño de raza, proteína, necesidades),
- palabras de su nombre que tienen equivalente ("Puppy" → cachorro,
  "Chicken" → pollo, "Small Breed" → raza pequeña…).

Los buscadores (POS, Recibir mercadería, Etiquetas, el chat y el sitio)
solo tienen que buscar cada palabra escrita en el nombre O en estas
etiquetas. Así no hay cinco listas de sinónimos que se desactualizan por
separado. Agregar un sinónimo es agregar una palabra a un grupo de abajo.

Regla: las etiquetas describen lo que el producto ES (categoría, mascota,
etapa…), nunca beneficios que su ficha no declara.
"""
import re
import unicodedata

# Grupos de equivalencias. Si cualquiera de las palabras de un grupo aparece
# en el producto (nombre, categoría, mascota o ficha), se le agregan TODAS.
GRUPOS = {
    "comida": ["comida", "alimento", "concentrado", "croqueta", "croquetas", "food", "pienso"],
    "humedo": ["humedo", "humeda", "humedos", "hum", "lata", "latas", "sobre", "pate", "wet", "en salsa", "loaf", "stew"],
    "snack": ["snack", "premio", "golosina", "treat", "treats", "galleta", "chuchería"],
    "perro": ["perro", "perra", "perrito", "dog", "canino", "canine"],
    "gato": ["gato", "gata", "gatos", "cat", "felino", "feline"],
    "cachorro": ["cachorro", "puppy", "junior"],
    "gatito": ["gatito", "kitten"],
    "adulto": ["adulto", "adult", "ad"],
    "senior": ["senior", "mayor", "viejito", "anciano", "edad avanzada"],
    "pequena": ["raza pequena", "pequeno", "pequena", "mini", "toy", "small", "small breed", "small bites", "rp",
                "talla s", "talla xs", "extra small", "chico"],
    "mediana": ["raza mediana", "mediano", "mediana", "medium", "talla m"],
    "grande": ["raza grande", "grande", "large", "large breed", "talla l", "talla xl"],
    "pollo": ["pollo", "chicken"],
    "cordero": ["cordero", "lamb"],
    "res": ["res", "carne", "beef"],
    "pescado": ["pescado", "fish", "seafood", "ocean", "pescados"],
    "salmon": ["salmon"],
    "atun": ["atun", "tuna"],
    "sardina": ["sardina", "sardine"],
    "pato": ["pato", "duck"],
    "pavo": ["pavo", "turkey"],
    "cerdo": ["cerdo", "pork", "iberico"],
    "esterilizado": ["esterilizado", "esterilizada", "castrado", "castrada", "sterilized", "neutered"],
    "peso": ["control de peso", "light", "weight", "weight control", "dieta", "obesidad"],
    "sin_granos": ["sin granos", "libre de granos", "grain free", "grainfree", "gf", "gr fr", "granos"],
    "piel": ["piel", "pelaje", "skin", "coat", "skin and coat"],
    "digestion": ["digestion", "estomago"],
    "urinario": ["urinario", "urinaria", "urinary"],
    "hipoalergenico": ["hipoalergenico", "alergia", "hypoallergenic"],
    "articulaciones": ["articulaciones", "hip and joint", "joint", "cadera"],
    "arena": ["arena", "sanitario", "litter"],
    "juguete": ["juguete", "juguetes"],
    "collar": ["collar", "collares"],
    "correa": ["correa", "correas", "leash", "trailla"],
    "arnes": ["arnes", "pechera", "harness"],
    "cama": ["cama", "camas", "colchoneta", "bed"],
    "comedero": ["comedero", "plato", "tazon", "bebedero", "bowl"],
    "shampoo": ["shampoo", "champu", "jabon", "bano"],
    "ropa": ["ropa", "camisa", "buzo", "sueter", "disfraz"],
    "transportador": ["transportador", "kennel", "jaula", "bolso"],
    "rascador": ["rascador", "scratcher"],
}

# Palabras de la consulta que no aportan ("comida PARA perro DE raza…").
# Los buscadores las ignoran; se exponen para que todos usen las mismas.
# Un salmón es pescado, pero un atún no es salmón: estos grupos traen el
# grupo general sin traer a los hermanos.
IMPLICA = {"salmon": ["pescado"], "atun": ["pescado"], "sardina": ["pescado"]}

VACIAS = {"para", "de", "del", "con", "el", "la", "los", "las", "y", "en", "un", "una", "unos", "unas",
          "mi", "su", "al", "que", "por", "o", "a"}

_SIN_PALABRAS_SUELTAS = {"res", "big", "toy", "cat", "dog", "pate", "mini"}  # solo como palabra completa


def plano(texto):
    """Sin tildes, minúscula, espacios simples ("Raza Pequeña" → "raza pequena")."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _patron(frase):
    frase = plano(frase)
    fin = r"(?![a-z0-9])" if (" " in frase or frase in _SIN_PALABRAS_SUELTAS or len(frase) <= 3) else ""
    return r"(?<![a-z0-9])" + re.escape(frase) + fin


# Un patrón por grupo, armado una sola vez: el POS arma las etiquetas de
# ~600 productos en cada carga y probar palabra por palabra tardaba ~0,5 s.
_REGEX_GRUPO = {clave: re.compile("|".join(_patron(p) for p in palabras)) for clave, palabras in GRUPOS.items()}


def _grupos_en(texto):
    texto = plano(texto)
    return {clave for clave, rx in _REGEX_GRUPO.items() if rx.search(texto)}


# Ficha técnica → grupos (por clave del vocabulario de catalogo/alimentos.py).
_FICHA_ETAPA = {"cachorro": ["cachorro"], "gatito": ["gatito"], "adulto": ["adulto"], "senior": ["senior"],
                "todas": ["cachorro", "gatito", "adulto", "senior"]}
_FICHA_TAMANO = {"pequena": ["pequena"], "mediana": ["mediana"], "grande": ["grande"],
                 "todas": ["pequena", "mediana", "grande"]}
_FICHA_TIPO = {"seco": ["comida"], "humedo": ["comida", "humedo"], "snack": ["snack"]}
_FICHA_NECESIDAD = {"esterilizado": ["esterilizado"], "control_peso": ["peso"], "libre_granos": ["sin_granos"],
                    "piel_sensible": ["piel"], "digestion_sensible": ["digestion"], "urinaria": ["urinario"],
                    "hipoalergenico": ["hipoalergenico"], "articulaciones": ["articulaciones"]}


def etiquetas(producto):
    """Texto extra de búsqueda de un producto (objeto con categoria, ficha)."""
    cat = getattr(producto, "categoria", None)
    padre = getattr(cat, "padre", None) if cat else None
    ficha = getattr(producto, "ficha_alimento", None) if getattr(producto, "ficha_alimento_id", None) else None
    base = " ".join([
        producto.nombre or "", producto.presentacion or "", getattr(producto, "marca", "") or "",
        cat.nombre if cat else "", padre.nombre if padre else "", producto.mascota or "",
    ])
    grupos = _grupos_en(base)
    # "Alimento", "Alimento seco/húmedo" y "Snacks" son comida aunque el nombre no lo diga.
    raiz = plano(padre.nombre if padre else (cat.nombre if cat else ""))
    if raiz.startswith("alimento"):
        grupos.add("comida")
    if "perro y gato" in plano(producto.mascota):
        grupos.update({"perro", "gato"})
    extra = []
    if ficha is not None:
        grupos.update({"perro"} if ficha.especie == "perro" else {"gato"} if ficha.especie == "gato" else set())
        for clave in ficha.etapas or []:
            grupos.update(_FICHA_ETAPA.get(clave, []))
        for clave in ficha.tamanos_raza or []:
            grupos.update(_FICHA_TAMANO.get(clave, []))
        grupos.update(_FICHA_TIPO.get(ficha.tipo, []))
        for clave in ficha.necesidades or []:
            grupos.update(_FICHA_NECESIDAD.get(clave, []))
        grupos.update(_grupos_en(ficha.proteina_principal or ""))
        extra += [ficha.marca, ficha.linea, ficha.proteina_principal, ficha.sabor]
    # "cachorro" no es "gatito": si el producto es de gato, el grupo cachorro
    # (que trae "puppy") no aplica, y viceversa.
    for clave in list(grupos):
        grupos.update(IMPLICA.get(clave, []))
    if "gato" in grupos and "perro" not in grupos:
        grupos.discard("cachorro")
    if "perro" in grupos and "gato" not in grupos:
        grupos.discard("gatito")
    palabras = []
    for clave in sorted(grupos):
        palabras += GRUPOS[clave]
    palabras += [x for x in extra if x]
    if cat:
        palabras.append(cat.nombre)
    if padre:
        palabras.append(padre.nombre)
    vistas, salida = set(), []
    for p in palabras:
        p = plano(p)
        if p and p not in vistas:
            vistas.add(p)
            salida.append(p)
    return " ".join(salida)


def etiquetas_por_id(queryset):
    """{id: etiquetas} para una lista de productos, en una sola consulta."""
    return {p.pk: etiquetas(p) for p in queryset.select_related("categoria__padre", "ficha_alimento")}


def _variantes(palabra):
    """La palabra y su singular simple ("cachorros" → "cachorro")."""
    salida = [palabra]
    if len(palabra) > 4 and palabra.endswith("es") and not palabra.endswith("ses"):
        salida.append(palabra[:-2])
    if len(palabra) > 3 and palabra.endswith("s"):
        salida.append(palabra[:-1])
    return salida


_PESO = re.compile(r"(\d)\s+(kg|g|lb|oz|ml|l)\b")


def _sin_espacio_en_pesos(texto):
    """"10 kg" y "10kg" se comparan igual (mismo criterio del buscador del navegador)."""
    return _PESO.sub(r"\1\2", texto)


def palabras_de_consulta(texto):
    return [w for w in _sin_espacio_en_pesos(plano(texto)).split() if w not in VACIAS]


def coincide(consulta, *campos):
    """True si CADA palabra útil de la consulta aparece, al inicio de una
    palabra, en algún campo (incluidas las etiquetas). Misma regla que
    static/js/buscador.js y allpetcr-web/lib/busqueda.ts."""
    palabras = palabras_de_consulta(consulta)
    if not palabras:
        return True
    texto = _sin_espacio_en_pesos(plano(" ".join(c or "" for c in campos)))
    return all(
        any(re.search(r"(?<![a-z0-9])" + re.escape(v), texto) for v in _variantes(w))
        for w in palabras
    )


def filtrar(queryset, consulta, limite=None):
    """Productos del queryset que coinciden con la consulta, en Python.

    Para el buscador de Precios y el chat (antes eran filtros de base con
    `icontains`, que no sabían de sinónimos). Primero lo que coincide exacto
    por SKU o código de barras (escanear sigue siendo instantáneo); después
    el resto, con el mismo criterio que el navegador."""
    consulta = (consulta or "").strip()
    productos = list(queryset.select_related("categoria__padre", "ficha_alimento"))
    exactos = [p for p in productos if consulta and (p.sku.lower() == consulta.lower() or p.codigo_barras == consulta)]
    if exactos:
        return exactos[:limite] if limite else exactos
    salida = [p for p in productos
              if coincide(consulta, p.nombre, p.sku, p.codigo_barras, p.presentacion, p.descripcion,
                          getattr(p, "marca", ""), etiquetas(p))]
    return salida[:limite] if limite else salida
