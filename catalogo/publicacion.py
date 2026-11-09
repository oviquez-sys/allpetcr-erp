"""Publicaciones para Instagram, Facebook y estados de WhatsApp (09/11/2026).

Pedido de Oscar («PROMPT MAESTRO», prototipo aprobado el 09/11/2026 con
Gosbi Exclusive Grain Free Adult Medium Fish): una pieza minimalista, foto
original grande, logo pequeño, y el precio como segundo protagonista.

Un solo tamaño, 1080 × 1350 (4:5), para TODAS las redes: Instagram,
Facebook y estados de WhatsApp. Oscar, 09/11/2026: «no considero necesario
crear la de los estados; la idea es usar la misma para todas las redes».
(Hubo una versión 9:16 para estados; se quitó ese mismo día.)

Dos variantes, según el producto:
- CON ficha técnica publicable (verificada o parcial): marca y fórmula,
  ingredientes principales en el orden declarado, proteína y grasa, «sin
  cereales» si el fabricante lo declara, y hasta dos beneficios verificados.
- SIN ficha (alimentos que esperan su ficha, juguetes, accesorios…): solo la
  foto, el nombre, el peso o presentación y el precio. Oscar: «igual
  publicalo, solo que sin la información». Nunca se rellena con datos de
  otra fórmula.

Reemplaza a la vieja «tarjeta con precio» 1080 × 1080 en el paquete del
catálogo (carpeta Para_estados_y_publicaciones): Oscar, 09/11/2026, «cumplen
la misma función y esto es mucho mejor».

Reglas que no se negocian:
- Logo y foto son los originales (nada recreado ni generado).
- Ningún dato se inventa: lo que la ficha no trae, no sale.
- Sin descuentos inventados: si hay tachado es porque hay una promoción
  vigente de verdad, con su fecha de fin (Ley 7472).
- Colores del logo (Oscar eligió esos sobre los del prompt): #092E5E y
  #CC9539, los mismos de `redes.NAVY` y `redes.DORADO`.
- Cada pieza lleva «Precio al <fecha>»: las imágenes se reenvían durante
  semanas y un precio sin fecha parece vigente para siempre.

Solo LEE datos del ERP: generar una publicación no cambia precios,
inventario ni fichas.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from . import alimentos
from .por_kilo import contenido

ESTADOS_PUBLICABLES = ("parcial", "verificado")    # mismos que publica la API

FONDO = (251, 250, 247)          # blanco cálido
TINTA = (31, 42, 55)
GRIS = (107, 118, 132)
LINEA = (231, 227, 218)
SITIO = "allpetcr.com"
LUGAR = "Heredia"

FEED = (1080, 1350)

MAX_INGREDIENTES = 4
MAX_BENEFICIOS = 2

# Palabras de España que en Costa Rica se dicen distinto (las fichas de Gosbi
# vienen de gosbi.com/es). Es traducción, no cambio de dato.
REGIONALISMOS = [
    (r"\bpatatas\b", "papas"), (r"\bpatata\b", "papa"),
    (r"\bboniatos\b", "camotes"), (r"\bboniato\b", "camote"),
    (r"\bguisantes\b", "arvejas"), (r"\bguisante\b", "arveja"),
]

# Fichas de marcas de EE. UU. (NutriSource, PureVita, Tuffy's, Loving Pets…)
# traen la lista en inglés, tal como la publica el fabricante. La ficha NO se
# cambia (la web la muestra original); solo la publicación sale en español.
# Traducción de cada ingrediente COMPLETO, nunca palabra por palabra, para
# no inventar («brewers rice» no es «arroz de cerveceros» sino el arroz
# partido que se usa en alimento). `test_publicacion` revisa que ningún
# ingrediente de las fichas del repositorio salga en inglés: una ficha nueva
# con uno que no esté acá hace fallar la prueba y se agrega aquí.
TRADUCCION = {
    "chicken": "Pollo", "deboned chicken": "Pollo deshuesado", "fresh chicken": "Pollo fresco",
    "chicken meal": "Harina de pollo", "chicken broth": "Caldo de pollo", "chicken liver": "Hígado de pollo",
    "chicken fat": "Grasa de pollo", "chicken by-product meal": "Harina de subproductos de pollo",
    "turkey": "Pavo", "deboned turkey": "Pavo deshuesado", "turkey meal": "Harina de pavo",
    "turkey broth": "Caldo de pavo", "turkey liver": "Hígado de pavo",
    "duck": "Pato", "deboned duck": "Pato deshuesado", "duck meal": "Harina de pato", "duck broth": "Caldo de pato",
    "natural duck flavor": "Saborizante natural de pato",
    "lamb": "Cordero", "deboned lamb": "Cordero deshuesado", "lamb meal": "Harina de cordero",
    "lamb broth": "Caldo de cordero", "lamb liver": "Hígado de cordero",
    "beef": "Res", "beef meal": "Harina de res", "beef broth": "Caldo de res", "beef liver": "Hígado de res",
    "beef lung": "Pulmón de res",
    "pork": "Cerdo", "pork broth": "Caldo de cerdo", "pork liver": "Hígado de cerdo",
    "rabbit": "Conejo", "venison": "Venado", "bison": "Bisonte",
    "salmon": "Salmón", "deboned salmon": "Salmón deshuesado", "salmon meal": "Harina de salmón",
    "salmon oil": "Aceite de salmón", "trout": "Trucha", "whitefish": "Pescado blanco",
    "whitefish meal": "Harina de pescado blanco", "fish meal": "Harina de pescado",
    "menhaden fish meal": "Harina de pescado menhaden", "menhaden fishmeal": "Harina de pescado menhaden",
    "herring meal": "Harina de arenque", "tuna": "Atún", "fish broth": "Caldo de pescado",
    "dried egg product": "Huevo deshidratado", "eggs": "Huevo", "water": "Agua",
    "brown rice": "Arroz integral", "brown rice flour": "Harina de arroz integral", "rice": "Arroz",
    "white rice": "Arroz blanco", "brewers rice": "Arroz partido", "ground rice": "Arroz molido",
    "barley": "Cebada", "pearled barley": "Cebada perlada", "oatmeal": "Avena molida", "oats": "Avena",
    "sorghum": "Sorgo", "ground whole grain corn": "Maíz integral molido", "corn": "Maíz",
    "corn gluten meal": "Gluten de maíz", "wheat flour": "Harina de trigo",
    "peas": "Arvejas", "pea flour": "Harina de arveja", "pea fiber": "Fibra de arveja",
    "pea protein": "Proteína de arveja", "pea starch": "Almidón de arveja",
    "chickpeas": "Garbanzos", "garbanzo beans": "Garbanzos", "chickpea flour": "Harina de garbanzo",
    "lentils": "Lentejas", "green lentils": "Lentejas verdes", "red lentils": "Lentejas rojas",
    "potatoes": "Papas", "dried potatoes": "Papa deshidratada", "potato flour": "Harina de papa",
    "potato starch": "Almidón de papa", "sweet potatoes": "Camote", "sweet potato": "Camote",
    "tapioca starch": "Almidón de tapioca", "carrots": "Zanahorias", "pumpkin": "Calabaza",
    "ground flaxseed": "Linaza molida", "flaxseed": "Linaza", "sunflower meal": "Harina de girasol",
    "cane molasses": "Melaza de caña", "vegetable glycerin": "Glicerina vegetal",
    "coconut glycerin": "Glicerina de coco", "glycerin": "Glicerina",
    "brewers dried yeast": "Levadura de cerveza deshidratada", "dried yeast": "Levadura deshidratada",
    "natural flavor": "Saborizante natural",
}

# Palabras que delatan un ingrediente que se quedó en inglés (las usa la prueba).
PALABRAS_INGLES = {
    "chicken", "turkey", "duck", "lamb", "beef", "pork", "rabbit", "salmon", "trout", "fish", "whitefish",
    "meal", "broth", "liver", "fat", "lung", "rice", "brown", "barley", "oatmeal", "oats", "sorghum", "corn",
    "wheat", "flour", "peas", "pea", "chickpeas", "chickpea", "beans", "lentils", "green", "red", "potatoes",
    "potato", "sweet", "starch", "carrots", "pumpkin", "flaxseed", "ground", "sunflower", "molasses",
    "glycerin", "vegetable", "coconut", "brewers", "dried", "yeast", "deboned", "fresh", "flavor",
    "water", "egg", "eggs", "and", "with",
}


# ---------------------------------------------------------------------------
# Datos (lo único que sabe del ERP)
# ---------------------------------------------------------------------------
@dataclass
class Datos:
    marca: str
    titulo: str
    sub: str
    peso: str                         # «Bolsa de 3 kg» (texto completo)
    precio: Decimal | None            # None = sin precio
    envase: str = ""                  # «Bolsa de» (rótulo chico sobre la cantidad)
    cantidad: str = ""                # «3 kg» (uno de los tres protagonistas)
    precio_antes: Decimal | None = None
    oferta_pct: int | None = None
    oferta_hasta: date | None = None
    fecha: date | None = None
    ingredientes: list = field(default_factory=list)
    nutricion: list = field(default_factory=list)     # [(etiqueta, valor)]
    beneficios: list = field(default_factory=list)    # textos
    con_ficha: bool = False


def ficha_publicable(producto):
    f = getattr(producto, "ficha_alimento", None)
    return f if f is not None and f.estado in ESTADOS_PUBLICABLES else None


def _regional(texto):
    for patron, por in REGIONALISMOS:
        texto = re.sub(patron, por, texto, flags=re.IGNORECASE)
    return texto


def _partir_nivel_cero(texto):
    """Separa por comas que no están dentro de paréntesis."""
    partes, nivel, actual = [], 0, ""
    for ch in texto:
        if ch in "([":
            nivel += 1
        elif ch in ")]":
            nivel = max(0, nivel - 1)
        if ch == "," and nivel == 0:
            partes.append(actual)
            actual = ""
        else:
            actual += ch
    partes.append(actual)
    return [p.strip() for p in partes if p.strip()]


def ingredientes_principales(texto, n=MAX_INGREDIENTES):
    """Los primeros `n` ingredientes EN EL ORDEN DECLARADO, sin el detalle
    entre paréntesis pero con su porcentaje si lo declara.

    «Pescado (47 %) (Micromesistius…), almidón de patata (19 %), lentejas»
    → ["Pescado 47 %", "Almidón de papa 19 %", "Lentejas"]"""
    salida = []
    for parte in _partir_nivel_cero(texto or ""):
        # El porcentaje propio va en el primer paréntesis que es SOLO un %.
        pct = None
        for grupo in re.findall(r"\(([^()]*)\)", parte):
            m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%\s*", grupo)
            if m:
                pct = m.group(1).replace(".", ",")
                break
        nombre = parte
        while "(" in nombre:                        # quita paréntesis anidados
            nuevo = re.sub(r"\([^()]*\)", "", nombre)
            if nuevo == nombre:
                nombre = nombre.split("(")[0]
                break
            nombre = nuevo
        nombre = re.sub(r"\s+", " ", nombre).strip(" .:;+")
        nombre = re.split(r"\s\+\s|\+", nombre)[0].strip()
        if not nombre:
            continue
        nombre = nombre.replace("*", "").strip()      # el * remite a una nota que no sale
        nombre = TRADUCCION.get(nombre.lower(), nombre)
        nombre = _regional(nombre)
        nombre = nombre[0].upper() + nombre[1:]
        salida.append(f"{nombre} {pct} %" if pct else nombre)
        if len(salida) == n:
            break
    return salida


def _numero(valor):
    """«6.9» → «6,9»; «27.0» → «27»."""
    try:
        d = Decimal(str(valor))
    except Exception:  # noqa: BLE001 — valor raro: se muestra tal cual
        return str(valor)
    d = d.normalize()
    texto = f"{d:f}"
    return texto.replace(".", ",")


def nutricion(ficha):
    filas = []
    por_clave = {a.get("clave"): a for a in (ficha.analisis or [])}
    for clave, corto in (("proteina", "Proteína"), ("grasa", "Grasa")):
        a = por_clave.get(clave)
        if not a or a.get("valor") in (None, ""):
            continue
        etiqueta = a.get("etiqueta") or corto
        cal = alimentos.CALIFICADORES.get(a.get("calificador") or "", "")
        if cal:
            etiqueta = f"{etiqueta} ({cal})"
        filas.append((etiqueta, f"{_numero(a['valor'])} {a.get('unidad') or ''}".strip()))
    if "libre_granos" in (ficha.necesidades or []):
        filas.append(("Cereales", "Sin"))
    return filas


def beneficios(ficha, claves=None):
    """Textos de beneficios verificados de la ficha. `claves` elige cuáles
    (en el orden de la ficha); None = los primeros dos."""
    todos = [b for b in (ficha.beneficios or []) if (b.get("texto") or "").strip()]
    if claves is not None:
        todos = [b for b in todos if b.get("clave") in claves]
    return [b["texto"].strip() for b in todos[:MAX_BENEFICIOS]]


def _para_quien(ficha):
    """«Perro adulto · raza mediana»."""
    partes = []
    especie = alimentos.ESPECIES.get(ficha.especie, "")
    etapas = [e for e in (ficha.etapas or []) if e in alimentos.ETAPAS]
    if especie:
        if etapas and "todas" not in etapas:
            especie += " " + " y ".join(alimentos.ETAPAS[e].lower() for e in etapas)
        partes.append(especie)
        if "todas" in etapas:
            partes.append("todas las etapas")
    tam = [t for t in (ficha.tamanos_raza or []) if t in alimentos.TAMANOS_RAZA]
    if "todas" in tam:
        partes.append("todas las razas")
    elif tam:
        partes.append("raza " + " y ".join(alimentos.TAMANOS_RAZA[t].lower().replace("raza ", "") for t in tam))
    return " · ".join(partes)


def _titulo_ficha(ficha):
    """La línea va arriba en pequeño; el título es lo que queda del nombre."""
    nombre, linea = (ficha.nombre or "").strip(), (ficha.linea or "").strip()
    if linea and nombre.lower().startswith(linea.lower()) and len(nombre) > len(linea) + 2:
        return nombre[len(linea):].strip(" -·")
    return nombre


def partes_peso(producto, ficha=None):
    """(«Bolsa de», «3 kg»): el envase va chico y la cantidad en grande.
    Sin peso conocido, la presentación tal cual y sin envase."""
    cantidad = ""
    if producto.peso_valor and producto.peso_unidad:
        cantidad = f"{_numero(producto.peso_valor)} {producto.peso_unidad}"
    elif (producto.presentacion or "").strip():
        cantidad = producto.presentacion.strip()
    envase = ""
    if cantidad and ficha is not None and ficha.tipo == "seco" and \
            contenido(producto.peso_valor, producto.peso_unidad, producto.presentacion):
        envase = "Bolsa de"
    return envase, cantidad


def peso(producto, ficha=None):
    """«Bolsa de 3 kg» (alimento seco), «85 g», o la presentación tal cual."""
    envase, cantidad = partes_peso(producto, ficha)
    return f"{envase} {cantidad}".strip()


def datos(producto, *, precio, oferta=None, fecha=None, con_precio=True, claves_beneficio=None):
    """Lo que va en la pieza. `precio` es el que se cobra hoy (con la
    promoción si hay); `oferta` es el dict de `promociones.oferta_de`."""
    ficha = ficha_publicable(producto)
    envase, cantidad = partes_peso(producto, ficha)
    d = Datos(marca="", titulo=producto.nombre, sub="", peso=f"{envase} {cantidad}".strip(),
              precio=Decimal(precio) if con_precio else None, fecha=fecha, envase=envase, cantidad=cantidad)
    if con_precio and oferta:
        d.precio_antes = oferta["precio_antes"]
        d.oferta_pct = oferta["pct"]
        d.oferta_hasta = oferta["hasta"]
    if ficha is None:
        marca = (producto.marca or "").strip()
        # «BALANCE» arriba de «Balance Castrado» sobra.
        d.marca = "" if marca and producto.nombre.lower().startswith(marca.lower()) else marca
        d.sub = (producto.mascota or "").strip()
        return d
    d.con_ficha = True
    d.marca = " · ".join(x for x in (ficha.marca, ficha.linea) if x)
    d.titulo = _titulo_ficha(ficha) or producto.nombre
    d.sub = _para_quien(ficha)
    d.ingredientes = ingredientes_principales(ficha.ingredientes)
    d.nutricion = nutricion(ficha)
    d.beneficios = beneficios(ficha, claves_beneficio)
    return d


def huella(producto, *, precio, oferta=None):
    """Resumen de los datos del ERP que salen en la pieza. Si cambia entre la
    vista previa y la descarga, la vista previa quedó desactualizada."""
    ficha = getattr(producto, "ficha_alimento", None)
    partes = {
        "nombre": producto.nombre, "marca": producto.marca, "presentacion": producto.presentacion,
        "peso": [str(producto.peso_valor or ""), producto.peso_unidad], "mascota": producto.mascota,
        "imagen": str(producto.imagen or ""), "precio": str(precio),
        "oferta": [str(oferta["precio_antes"]), oferta["pct"], str(oferta["hasta"])] if oferta else None,
        "ficha": [ficha.pk, ficha.estado, ficha.actualizado_en.isoformat() if ficha.actualizado_en else ""]
        if ficha is not None else None,
    }
    return hashlib.sha1(json.dumps(partes, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Dibujo
# ---------------------------------------------------------------------------
def _redes():
    from . import redes
    return redes


def _ancho_espaciado(d, texto, fuente, espacio):
    return sum(d.textlength(c, font=fuente) for c in texto) + espacio * max(0, len(texto) - 1)


def _partir_espaciado(d, texto, fuente, espacio, ancho, max_lineas=2):
    """Como _envolver, pero midiendo con el espaciado entre letras."""
    filas, actual = [], ""
    for p in texto.upper().split():
        prueba = f"{actual} {p}".strip()
        if _ancho_espaciado(d, prueba, fuente, espacio) <= ancho or not actual:
            actual = prueba
        else:
            filas.append(actual)
            actual = p
    if actual:
        filas.append(actual)
    if len(filas) > max_lineas:
        filas = filas[:max_lineas]
        filas[-1] += " …"
    return filas


def _texto_espaciado(d, xy, texto, fuente, fill, espacio, anchor_centro=False, ancho_max=None):
    """Mayúsculas con espaciado entre letras (Pillow no lo trae)."""
    texto = texto.upper()

    def ancho(t):
        return _ancho_espaciado(d, t, fuente, espacio)

    if ancho_max:
        while texto and ancho(texto) > ancho_max:
            texto = texto[:-2].rstrip() + "…"
    x, y = xy
    if anchor_centro:
        x -= ancho(texto) / 2
    for c in texto:
        d.text((x, y), c, font=fuente, fill=fill)
        x += d.textlength(c, font=fuente) + espacio
    return ancho(texto)


def _foto_fundida(foto, ancho, alto):
    """La foto encajada y «multiplicada» sobre el blanco cálido: así el fondo
    blanco de la foto no queda como un recuadro sobre el crema."""
    from PIL import Image, ImageChops
    im = _redes()._encajar(foto, ancho, alto).convert("RGB")
    return ImageChops.multiply(im, Image.new("RGB", im.size, FONDO))


def _vigencia(d):
    return f"−{d.oferta_pct} % · hasta el {d.oferta_hasta:%d/%m} o hasta agotar existencias"


def _pie_precio(d):
    partes = ["IVA incluido"]
    if d.fecha:
        partes.append(f"Precio al {d.fecha.day}/{d.fecha.month}/{d.fecha.year}")
    return " · ".join(partes)


class _Bloques:
    """Mide y dibuja texto en una columna; sirve para saber si cabe ANTES de
    dibujar (y si no cabe, quitar un ingrediente o un beneficio)."""

    def __init__(self, draw, ancho):
        self.d, self.ancho, self.ops, self.alto = draw, ancho, [], 0

    def espacio(self, h):
        self.alto += h

    def lineas(self, texto, fuente, fill, interlinea, max_lineas=3, centrado=False):
        r = _redes()
        filas = r._envolver(self.d, texto, fuente, self.ancho, max_lineas)
        for f in filas:
            self.ops.append(("t", self.alto, f, fuente, fill, centrado))
            self.alto += interlinea
        return len(filas)

    def espaciado(self, texto, fuente, fill, espacio, alto, centrado=False, max_lineas=1):
        filas = _partir_espaciado(self.d, texto, fuente, espacio, self.ancho, max_lineas) if max_lineas > 1 else [texto]
        for i, f in enumerate(filas):
            self.ops.append(("e", self.alto, f, fuente, fill, centrado, espacio))
            self.alto += alto if i == len(filas) - 1 else int(fuente.size * 1.45)

    def nutricion(self, filas, f_et, f_val, alto, centrado=False):
        self.ops.append(("n", self.alto, filas, f_et, f_val, centrado))
        self.alto += alto

    def dibujar(self, x, y0):
        d = self.d
        for op in self.ops:
            tipo, y = op[0], y0 + op[1]
            if tipo == "t":
                _, _, texto, fuente, fill, centrado = op
                if centrado:
                    d.text((x + self.ancho / 2, y), texto, font=fuente, fill=fill, anchor="ma")
                else:
                    d.text((x, y), texto, font=fuente, fill=fill)
            elif tipo == "e":
                _, _, texto, fuente, fill, centrado, espacio = op
                if centrado:
                    _texto_espaciado(d, (x + self.ancho / 2, y), texto, fuente, fill, espacio, True, self.ancho)
                else:
                    _texto_espaciado(d, (x, y), texto, fuente, fill, espacio, False, self.ancho)
            elif tipo == "n":
                _, _, filas, f_et, f_val, centrado = op
                anchos = [max(d.textlength(e, font=f_et), d.textlength(v, font=f_val)) for e, v in filas]
                sep = 34
                total = sum(anchos) + sep * (len(anchos) - 1)
                cx = x + (self.ancho - total) / 2 if centrado else x
                for (e, v), w in zip(filas, anchos):
                    d.text((cx, y), e, font=f_et, fill=GRIS)
                    d.text((cx, y + 24), v, font=f_val, fill=TINTA)
                    cx += w + sep


def _info(d, ancho, datos_, t, n_ing, n_ben, centrado=False):
    """Arma los bloques de marca, título, ingredientes, nutrición y beneficios
    con `n_ing` ingredientes y `n_ben` beneficios. `t` = tamaños."""
    r = _redes()
    b = _Bloques(d, ancho)
    if datos_.marca:
        b.espaciado(datos_.marca, r._fuente("Medium", t["marca"]), GRIS, 3, t["marca"] + 14, centrado, 2)
    b.lineas(datos_.titulo, r._fuente("Bold", t["titulo"]), TINTA, int(t["titulo"] * 1.1), t["lineas_titulo"], centrado)
    if datos_.sub:
        b.espacio(8)
        b.lineas(datos_.sub, r._fuente("Regular", t["sub"]), GRIS, int(t["sub"] * 1.4), 2, centrado)

    def titulo_sec(texto):
        b.espacio(t["sep"])
        b.espaciado(texto, r._fuente("Medium", t["h2"]), r.DORADO, 3, t["h2"] + 14, centrado)

    ing = datos_.ingredientes[:n_ing]
    if ing and t.get("ing_en_linea"):
        # En el estado (una sola columna centrada) uno por renglón no cabe:
        # van seguidos, en el mismo orden, separados por «·».
        titulo_sec("Ingredientes principales")
        b.lineas(" · ".join(ing), r._fuente("Regular", t["texto"]), t.get("color_info", TINTA),
                 int(t["texto"] * 1.45), 3, centrado)
    elif ing:
        titulo_sec("Ingredientes principales")
        f = r._fuente("Regular", t["texto"])
        for i, x in enumerate(ing):
            fuente = r._fuente("Medium", t["texto"]) if i == 0 else f
            b.lineas(x, fuente, t.get("color_info", TINTA), int(t["texto"] * 1.5), 2, centrado)
    if datos_.nutricion:
        titulo_sec("Información nutricional")
        b.nutricion(datos_.nutricion, r._fuente("Regular", t["h2"]), r._fuente("Bold", t["valor"]),
                    24 + int(t["valor"] * 1.25), centrado)
    ben = datos_.beneficios[:n_ben]
    if ben:
        titulo_sec("Beneficios" if len(ben) > 1 else "Beneficio destacado")
        f = r._fuente(t.get("peso_beneficio", "Medium"), t["beneficio"])
        for x in ben:
            b.lineas(x, f, t.get("color_info", TINTA), int(t["beneficio"] * 1.35), 3, centrado)
            b.espacio(6)
    return b


def _info_que_quepa(d, ancho, datos_, t, alto_max, centrado=False):
    """Prueba con todo y va quitando (primero ingredientes, luego un
    beneficio, luego la sección de ingredientes entera) hasta que quepa."""
    intentos = []
    for n_ben in (MAX_BENEFICIOS, 1):
        for n_ing in (MAX_INGREDIENTES, 3, 2):
            intentos.append((n_ing, n_ben))
    intentos.append((0, 1))
    intentos.append((0, 0))
    b = None
    for n_ing, n_ben in intentos:
        b = _info(d, ancho, datos_, t, n_ing, n_ben, centrado)
        if b.alto <= alto_max:
            return b, True
    return b, False


def _precio_derecha(d, x_der, y_base, datos_, tam):
    r = _redes()
    texto = r._crc(datos_.precio)
    w = r._ancho_precio(d, texto, "Bold", tam)
    color = r.OFERTA if datos_.oferta_pct else r.NAVY
    r._dibujar_precio(d, x_der - w, y_base, texto, "Bold", tam, color)
    if datos_.precio_antes:
        antes = r._crc(datos_.precio_antes)
        wa = r._ancho_precio(d, antes, "Regular", 38)
        ya = y_base - int(tam * 0.78) - 14
        r._dibujar_precio(d, x_der - wa, ya, antes, "Regular", 38, GRIS)
        d.line([x_der - wa, ya - 13, x_der, ya - 13], fill=GRIS, width=3)
    return w


# Tres protagonistas (Oscar, 09/11/2026: «que resalten el producto, la
# cantidad y el precio»): la foto y el nombre grandes arriba; abajo, la
# cantidad y el precio lado a lado, los dos en grande. Ingredientes,
# nutrición y beneficios quedan como apoyo: más chicos y en gris oscuro.
INFO = (75, 85, 99)                      # gris oscuro de la información de apoyo
TAM_PRECIO = 132
TAM_CANTIDAD = 104


def _banda(d, x0, x1, y_base, datos_, tam_precio=TAM_PRECIO, tam_cantidad=TAM_CANTIDAD):
    """Cantidad (izquierda) y precio (derecha) sobre la misma línea base.
    Devuelve (y de arriba de la banda, cupo). La cantidad se achica si no
    cabe al lado del precio; el precio nunca se achica."""
    r = _redes()
    ancho_precio = 0
    alto = 0
    if datos_.precio is not None:
        ancho_precio = _precio_derecha(d, x1, y_base, datos_, tam_precio)
        alto = int(tam_precio * 0.76) + (62 if datos_.precio_antes else 0)
    cupo = True
    if datos_.cantidad:
        libre = (x1 - x0) - ancho_precio - (40 if ancho_precio else 0)
        tam = tam_cantidad
        while tam > 44 and d.textlength(datos_.cantidad, font=r._fuente("Bold", tam)) > libre:
            tam -= 4
        fuente = r._fuente("Bold", tam)
        texto = datos_.cantidad
        if d.textlength(texto, font=fuente) > libre:
            texto = r._envolver(d, texto, fuente, libre, 1)[0]
            cupo = False if not texto.strip("…") else cupo
        d.text((x0, y_base), texto, font=fuente, fill=TINTA, anchor="ls")
        alto_c = int(tam * 0.76)
        if datos_.envase:
            _texto_espaciado(d, (x0, y_base - alto_c - 40), datos_.envase, r._fuente("Medium", 20), r.DORADO, 3)
            alto_c += 44
        alto = max(alto, alto_c)
    return y_base - alto, cupo


def _bajo_banda(d, x0, x1, y, datos_, centrado=False, extra=""):
    """Vigencia de la promoción y «IVA incluido · Precio al …», en chico."""
    r = _redes()
    lineas = []
    if datos_.precio is not None and datos_.oferta_pct:
        lineas.append((_vigencia(datos_), r._fuente("Medium", 19), r.OFERTA))
    pie = _pie_precio(datos_) if datos_.precio is not None else ""
    pie = " · ".join(x for x in (pie, extra) if x)
    if pie:
        lineas.append((pie, r._fuente("Regular", 17), GRIS))
    for texto, fuente, color in lineas:
        for fila in r._envolver(d, texto, fuente, x1 - x0, 2):
            if centrado:
                d.text(((x0 + x1) / 2, y), fila, font=fuente, fill=color, anchor="ms")
            else:
                d.text((x0, y), fila, font=fuente, fill=color, anchor="ls")
            y += 27
    return y - 27                       # línea base del último renglón dibujado


def _titulo_bloques(d, ancho, datos_, t, centrado=False):
    """Marca chica + nombre grande + para quién (variante sin ficha)."""
    r = _redes()
    b = _Bloques(d, ancho)
    if datos_.marca:
        b.espaciado(datos_.marca, r._fuente("Medium", t["marca"]), GRIS, 3, t["marca"] + 14, centrado, 2)
    b.lineas(datos_.titulo, r._fuente("Bold", t["titulo"]), TINTA, int(t["titulo"] * 1.1), 2, centrado)
    if datos_.sub:
        b.espacio(6)
        b.lineas(datos_.sub, r._fuente("Regular", t["sub"]), GRIS, int(t["sub"] * 1.4), 1, centrado)
    return b


def feed(datos_, foto):
    """1080 × 1350. Devuelve (imagen, cupo) — cupo=False si algo no cupo
    ni siquiera recortando (no debería pasar; lo vigila una prueba)."""
    from PIL import Image, ImageDraw
    r = _redes()
    W, H = FEED
    im = Image.new("RGB", FEED, FONDO)
    d = ImageDraw.Draw(im)
    logo = r._logo("logo_horizontal.png", 220)
    im.paste(logo, (72, 60), logo)

    # Abajo: cantidad y precio. Se dibujan primero para saber cuánto alto queda.
    y_base = 1172 if (datos_.precio is not None and datos_.oferta_pct) else 1198
    tope, cupo = _banda(d, 72, W - 72, y_base, datos_)
    # +58: debajo de la «g» de «kg», que baja ~26 px de la línea base.
    y = _bajo_banda(d, 72, W - 72, y_base + 58, datos_)
    cupo = cupo and y <= H - 46 - 30         # que no toque el pie
    limite = tope - 44

    if datos_.con_ficha:
        t = dict(marca=18, titulo=56, lineas_titulo=3, sub=22, sep=30, h2=13, texto=19, valor=27,
                 beneficio=19, ing_en_linea=True, color_info=INFO, peso_beneficio="Regular")
        b, cupo_info = _info_que_quepa(d, 430, datos_, t, limite - 150)
        cupo = cupo and cupo_info
        b.dibujar(590, 150)
        alto_foto = limite - 140
        f = _foto_fundida(foto, 520, alto_foto)
        im.paste(f, (40 + (520 - f.width) // 2, 140 + (alto_foto - f.height) // 2))
    else:
        b = _titulo_bloques(d, W - 144, datos_, dict(marca=18, titulo=58, sub=23))
        y_txt = limite - b.alto
        alto_foto = y_txt - 40 - 140
        f = _foto_fundida(foto, 940, alto_foto)
        im.paste(f, ((W - f.width) // 2, 140 + (alto_foto - f.height) // 2))
        b.dibujar(72, y_txt)
        cupo = cupo and alto_foto > 500

    # Pie
    fp, fb = r._fuente("Regular", 18), r._fuente("Medium", 18)
    yb = H - 46
    d.text((72, yb), SITIO, font=fb, fill=TINTA, anchor="ls")
    d.text((72 + d.textlength(SITIO, font=fb), yb), f" · {LUGAR}", font=fp, fill=GRIS, anchor="ls")
    wa = d.textlength(r.WHATSAPP, font=fb)
    d.text((W - 72 - wa, yb), r.WHATSAPP, font=fb, fill=TINTA, anchor="ls")
    d.text((W - 72 - wa - d.textlength("WhatsApp ", font=fp), yb), "WhatsApp ", font=fp, fill=GRIS, anchor="ls")
    return im, cupo


def dibujar(datos_, foto):
    return feed(datos_, foto)


def como_dict(datos_):
    return asdict(datos_)
