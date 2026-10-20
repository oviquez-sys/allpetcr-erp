"""Buscar alimentos por necesidad, según la ficha técnica (20/10/2026).

Pedido de Oscar: preguntarle al asistente del ERP "¿qué alimento le sirve a
un gato con bolas de pelo?" y que le dé opciones basadas en la ficha técnica.

Regla que no se negocia (la misma de FichaAlimento): solo cuenta lo que el
FABRICANTE declara. "Tiene salmón" no es "piel sensible", y "tiene fibra" no
es "control de bolas de pelo". Por eso cada resultado dice POR QUÉ salió
(`coincide_por`): una necesidad declarada, un beneficio declarado, o una
palabra que aparece en el texto oficial. El asistente arma la respuesta con
eso; si nada coincide, tiene que decirlo, no rellenar.

Además de las fichas se revisan los productos sin ficha (pastas de malta,
suplementos) por nombre y descripción, porque ahí también puede estar la
respuesta, y también se dice que salió por texto.
"""
import re
import unicodedata
from decimal import Decimal

from . import alimentos
from .por_kilo import precio_por_kilo

# Palabras de la gente → claves del vocabulario. Se comparan sin tildes y en
# minúscula, por "contiene". Cada entrada: (palabras, necesidades, beneficios,
# palabras para buscar en el texto oficial y en productos sin ficha).
SINONIMOS = [
    (["bola de pelo", "bolas de pelo", "bola pelo", "hairball", "tricobezoar", "vomita pelo"],
     [], ["bolas_pelo"], ["bola de pelo", "bolas de pelo", "bolas pelo", "hairball"]),
    (["esteriliz", "castrad", "operad", "neutered"], ["esterilizado"], [], ["esteriliz", "castrad"]),
    (["peso", "obes", "gordo", "gorda", "sobrepeso", "light", "dieta"], ["control_peso"], ["control_peso"], ["peso", "light"]),
    (["digest", "estomago", "diarrea", "vomit", "intestin", "heces", "gases"],
     ["digestion_sensible"], ["digestion", "prebioticos_probioticos"], ["digest", "sensible"]),
    (["piel", "picazon", "pica", "rasca", "pelaje", "caida de pelo", "dermat", "brillo"],
     ["piel_sensible"], ["piel_pelaje", "omega"], ["piel", "pelaje"]),
    (["urinari", "rinon", "orina", "calculo", "cristal", "vejiga"], ["urinaria"], ["urinaria"], ["urinari", "orina"]),
    (["alergi", "hipoalerg", "intoleran"], ["hipoalergenico", "ingredientes_limitados"], [], ["hipoalerg", "alerg"]),
    (["sin grano", "libre de grano", "grain free", "granos"], ["libre_granos"], [], ["grain free", "sin granos", "libre de granos"]),
    (["articula", "cadera", "artritis", "artrosis", "hueso", "displasia", "movilidad"],
     ["articulaciones"], ["articulaciones"], ["articula", "glucosamina", "condroitina"]),
    (["activ", "deport", "trabajo", "energia", "atleta"], ["actividad_alta"], ["energia"], ["activ", "energ"]),
    (["dental", "diente", "sarro", "aliento", "encia"], [], ["dental"], ["dental", "sarro"]),
    (["musculo", "muscular"], [], ["masa_muscular"], ["muscul"]),
    (["inmun", "defensa"], [], ["inmunidad"], ["inmun"]),
    (["corazon", "cardi"], [], ["corazon"], ["corazon", "taurina"]),
    (["hidrata", "toma poca agua", "bebe poca agua"], [], ["hidratacion"], ["hidrata"]),
    (["vista", "vision", "ojo"], [], ["vision"], ["vision"]),
    (["proteina", "carnivor"], [], ["alta_proteina"], ["proteina"]),
    (["exigente", "no come", "mañoso", "manoso", "sabor", "palatab"], [], ["sabor"], ["palatab", "sabor"]),
]

# Solo para productos SIN ficha: la pasta de malta es el producto típico para
# bolas de pelo, y su nombre no dice "bola". En el texto de las fichas no se
# usa ("malta" saldría en "maltodextrina").
PALABRAS_SOLO_PRODUCTOS = {"bolas_pelo": ["malta"]}

ETAPA_SINONIMOS = {
    "cachorro": ["cachorr", "puppy"], "gatito": ["gatit", "kitten"],
    "adulto": ["adult"], "senior": ["senior", "viej", "mayor", "anciano"],
}
TAMANO_SINONIMOS = {
    "pequena": ["pequen", "toy", "mini", "small"], "mediana": ["median"], "grande": ["grande", "large", "gigante"],
}


def _plano(texto):
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower()).strip()


def _contiene(palabra, texto):
    """`palabra` al inicio de una palabra de `texto` ("pica" no cae en "típica")."""
    return re.search(r"(?<![a-z0-9])" + re.escape(palabra), texto) is not None


def interpretar(necesidad):
    """Texto libre → (necesidades, beneficios, palabras de texto) del vocabulario."""
    t = _plano(necesidad)
    nec, ben, palabras = set(), set(), set()
    for frases, n, b, p in SINONIMOS:
        if any(_contiene(_plano(f), t) for f in frases):
            nec.update(n)
            ben.update(b)
            palabras.update(_plano(x) for x in p)
    # Una etiqueta del vocabulario escrita tal cual ("Salud urinaria") también vale.
    for clave, etiqueta in alimentos.NECESIDADES.items():
        if _plano(etiqueta) in t:
            nec.add(clave)
    for clave, etiqueta in alimentos.BENEFICIOS.items():
        if _plano(etiqueta) in t:
            ben.add(clave)
    if not (nec or ben or palabras) and len(t) >= 4:
        # Algo que el vocabulario no conoce ("ansiedad"): se busca la palabra
        # tal cual en el texto oficial.
        palabras.update(w for w in t.split() if len(w) >= 4)
    return nec, ben, palabras


def _clave_de(texto, sinonimos):
    t = _plano(texto)
    for clave, formas in sinonimos.items():
        if clave == t or any(_contiene(f, t) for f in formas):
            return clave
    return ""


def _analisis_corto(ficha):
    salida = {}
    for fila in ficha.analisis or []:
        clave = fila.get("clave")
        if clave in ("proteina", "grasa", "fibra", "humedad") and clave not in salida:
            cal = alimentos.CALIFICADORES.get(fila.get("calificador") or "", "")
            salida[clave] = f"{cal} {fila.get('valor', '')} {fila.get('unidad', '')}".strip()
    return salida


def _presentacion(p):
    kilo = precio_por_kilo(p.precio_venta, p.peso_valor, p.peso_unidad, p.presentacion)
    return {
        "sku": p.sku, "nombre": p.nombre, "presentacion": p.presentacion,
        "precio_venta": float(p.precio_venta), "existencia": float(p.stock_actual),
        "precio_por_kilo": kilo[0] if kilo and kilo[1] == "kg" else None,
    }


def buscar(empresa, *, especie="", necesidad="", etapa="", tamano_raza="", tipo="", texto="",
           solo_en_existencia=True, limite=6):
    """Opciones de alimento para una necesidad, con lo que dice su ficha."""
    from .models import FichaAlimento, Producto

    especie = _clave_de(especie, {"perro": ["perr", "dog", "can"], "gato": ["gat", "cat", "felin"]})
    etapa = _clave_de(etapa, ETAPA_SINONIMOS) if etapa else ""
    tamano = _clave_de(tamano_raza, TAMANO_SINONIMOS) if tamano_raza else ""
    tipo = _clave_de(tipo, {"seco": ["seco", "croqueta", "kibble"], "humedo": ["humed", "lata", "sobre", "pate"],
                             "snack": ["snack", "premio", "golosina"]}) if tipo else ""
    nec, ben, palabras = interpretar(necesidad)
    palabras_texto = {_plano(w) for w in str(texto or "").split() if len(w) >= 3}
    limite = max(1, min(int(limite or 6), 12))

    productos_qs = Producto.objects.filter(empresa=empresa, activo=True)
    if solo_en_existencia:
        productos_qs = productos_qs.filter(stock_actual__gt=0)
    por_ficha = {}
    for p in productos_qs.filter(ficha_alimento__isnull=False).order_by("precio_venta"):
        por_ficha.setdefault(p.ficha_alimento_id, []).append(p)

    fichas = FichaAlimento.objects.filter(pk__in=por_ficha) if solo_en_existencia else \
        FichaAlimento.objects.filter(productos__empresa=empresa).distinct()
    if especie:
        fichas = fichas.filter(especie=especie)
    if tipo:
        fichas = fichas.filter(tipo=tipo)

    filtrar_por_necesidad = bool(nec or ben or palabras or palabras_texto)
    resultados = []
    revisadas = 0
    for f in fichas:
        if etapa and f.etapas and etapa not in f.etapas and "todas" not in f.etapas:
            continue
        if tamano and f.tamanos_raza and tamano not in f.tamanos_raza and "todas" not in f.tamanos_raza:
            continue
        revisadas += 1
        motivos, puntos = [], 0
        for clave in nec & set(f.necesidades or []):
            motivos.append(f"necesidad declarada: {alimentos.NECESIDADES[clave]}")
            puntos += 3
        claves_ben = {b.get("clave") for b in f.beneficios or [] if isinstance(b, dict)}
        for clave in ben & claves_ben:
            motivos.append(f"beneficio declarado: {alimentos.BENEFICIOS[clave]}")
            puntos += 2
        oficial = _plano(" ".join([f.nombre, f.descripcion_corta, f.descripcion,
                                    " ".join(b.get("texto", "") for b in f.beneficios or [] if isinstance(b, dict))]))
        for w in sorted(palabras):
            if _contiene(w, oficial):
                motivos.append(f"el texto oficial menciona «{w}»")
                puntos += 1
        ingredientes = _plano(f.ingredientes + " " + f.aditivos)
        for w in sorted(palabras_texto):
            if f.proteina_principal and _contiene(w, _plano(f.proteina_principal)):
                motivos.append(f"proteína principal: {f.proteina_principal}")
                puntos += 3
            elif _contiene(w, oficial):
                motivos.append(f"la descripción oficial menciona «{w}»")
                puntos += 2
            elif _contiene(w, ingredientes):
                # Con su lugar en la lista: "aceite de salmón" en el lugar 14
                # no es lo mismo que salmón de primer ingrediente.
                partes = [x.strip() for x in (f.ingredientes + ", " + f.aditivos).split(",") if x.strip()]
                lugar, pedazo = next(((i, x) for i, x in enumerate(partes, 1) if _contiene(w, _plano(x))),
                                     (99, w))
                motivos.append(f"ingrediente n.º {lugar} de la lista: «{pedazo}»")
                puntos += 2 if lugar <= 3 else 1
        if filtrar_por_necesidad and not motivos:
            continue
        presentaciones = [_presentacion(p) for p in por_ficha.get(f.pk, [])]
        resultados.append({
            "puntos": puntos,
            "ficha": {
                "nombre": f.nombre, "marca": f.marca, "especie": alimentos.ESPECIES.get(f.especie, f.especie),
                "tipo": alimentos.TIPOS.get(f.tipo, f.tipo),
                "etapas": [alimentos.ETAPAS.get(e, e) for e in f.etapas or []],
                "tamanos_raza": [alimentos.TAMANOS_RAZA.get(t, t) for t in f.tamanos_raza or []],
                "necesidades_declaradas": [alimentos.NECESIDADES.get(n, n) for n in f.necesidades or []],
                "beneficios_declarados": [
                    alimentos.BENEFICIOS.get(b.get("clave"), b.get("clave")) + (f": {b['texto']}" if b.get("texto") else "")
                    for b in f.beneficios or [] if isinstance(b, dict)
                ],
                "proteina_principal": f.proteina_principal,
                "descripcion": (f.descripcion or f.descripcion_corta)[:500],
                "analisis": _analisis_corto(f),
                "kcal_por_kg": float(f.kcal_kg) if f.kcal_kg else None,
                "primeros_ingredientes": f.ingredientes[:300],
                "estado_ficha": alimentos.ESTADOS.get(f.estado, f.estado),
            },
            "coincide_por": motivos,
            "presentaciones": presentaciones,
        })
    resultados.sort(key=lambda r: (-r["puntos"], r["ficha"]["marca"], r["ficha"]["nombre"]))
    resultados = resultados[:limite]

    # Productos SIN ficha (pastas de malta, suplementos): solo por texto, y
    # se dice así.
    otros = []
    buscar_otros = palabras | palabras_texto
    for clave in ben | nec:
        buscar_otros |= set(PALABRAS_SOLO_PRODUCTOS.get(clave, []))
    if buscar_otros:
        for p in productos_qs.filter(ficha_alimento__isnull=True).select_related("categoria")[:2000]:
            texto_p = _plano(f"{p.nombre} {p.descripcion}")
            if especie and p.mascota and especie[:3] not in _plano(p.mascota):
                continue
            hits = [w for w in sorted(buscar_otros) if _contiene(w, texto_p)]
            if hits:
                otros.append({**_presentacion(p), "descripcion": (p.descripcion or "")[:300],
                              "categoria": p.categoria.nombre if p.categoria_id else "",
                              "coincide_por": [f"el nombre o la descripción menciona «{w}»" for w in hits]})
            if len(otros) >= 6:
                break

    sin_ficha = alimentos_sin_ficha(empresa, especie=especie, solo_en_existencia=bool(solo_en_existencia))
    return {
        "interpretacion": {
            "especie": alimentos.ESPECIES.get(especie, "cualquiera"),
            "necesidades_buscadas": [alimentos.NECESIDADES[n] for n in sorted(nec)],
            "beneficios_buscados": [alimentos.BENEFICIOS[b] for b in sorted(ben)],
            "palabras_buscadas": sorted(palabras | palabras_texto),
            "etapa": alimentos.ETAPAS.get(etapa, "cualquiera"),
            "tamano_raza": alimentos.TAMANOS_RAZA.get(tamano, "cualquiera"),
            "solo_en_existencia": bool(solo_en_existencia),
        },
        "fichas_revisadas": revisadas,
        "opciones": resultados,
        "otros_productos": otros,
        # Para que el chat muestre la foto de cada producto mencionado.
        "productos": [pr for r in resultados for pr in r["presentaciones"]][:12] + otros[:4],
        # Lo que no se pudo evaluar: hay que decirlo, no esconderlo.
        "alimentos_sin_ficha": {
            "cantidad": len(sin_ficha),
            "ejemplos": [{"nombre": p.nombre, "sku": p.sku} for p in sin_ficha[:15]],
        },
        "regla": ("Solo vale lo que el fabricante declara en la ficha. Si 'opciones' está vacío, "
                  "ninguna ficha de lo que hay en existencia declara esa necesidad: decilo así."),
    }


RAICES_CON_FICHA = {"Alimento", "Snacks y premios"}


def alimentos_sin_ficha(empresa, especie="", solo_en_existencia=False):
    """Alimentos y snacks activos que todavía no tienen ficha técnica.

    Es la lista que evita que el problema quede escondido (20/10/2026): un
    alimento sin ficha se vende igual, pero el asistente no puede
    recomendarlo por necesidad. Se llena sola al registrar uno nuevo en
    Recibir mercadería y se vacía al correr CARGAR_FICHAS_ALIMENTO.bat.
    """
    from django.db.models import Q

    from .models import Producto

    qs = (
        Producto.objects.filter(empresa=empresa, activo=True, ficha_alimento__isnull=True)
        .filter(Q(categoria__nombre__in=RAICES_CON_FICHA) | Q(categoria__padre__nombre__in=RAICES_CON_FICHA))
        .select_related("categoria")
        .order_by("nombre")
    )
    if solo_en_existencia:
        qs = qs.filter(stock_actual__gt=0)
    if especie:
        clave = _clave_de(especie, {"perro": ["perr", "dog", "can"], "gato": ["gat", "cat", "felin"]})
        if clave:
            qs = qs.filter(Q(mascota__icontains=clave) | Q(mascota=""))
    return list(qs)


def fichas_incompletas(empresa):
    """Fichas en estado Parcial o Requiere revisión de productos activos."""
    from .models import FichaAlimento

    return list(
        FichaAlimento.objects.filter(productos__empresa=empresa, productos__activo=True)
        .exclude(estado="verificado").distinct().order_by("marca", "nombre")
    )
