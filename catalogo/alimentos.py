"""Vocabulario controlado de las fichas de alimento (26/09/2026).

Por qué un vocabulario cerrado y no texto libre
-----------------------------------------------
Las etiquetas de una ficha (etapa, tamaño de raza, necesidad, beneficio) van a
alimentar filtros y un comparador. Si una ficha dice "urinaria", otra "salud
urinaria" y otra "tracto urinario", el filtro encuentra un tercio. Por eso
cada etiqueta es una CLAVE de esta lista, y el texto que ve el cliente sale
de acá — nunca de la ficha. `FichaAlimento.clean()` rechaza claves que no
estén en la lista.

Agregar una etiqueta nueva es agregar una línea acá (y su ícono en el sitio,
allpetcr-web/components/ficha/IconoBeneficio.tsx). Cambiarle el texto a una
existente cambia todas las fichas a la vez, que es justo lo que se quiere.
"""

ESPECIES = {"perro": "Perro", "gato": "Gato"}

TIPOS = {
    "seco": "Alimento seco",
    "humedo": "Alimento húmedo",
    "snack": "Snack o premio",
}

ETAPAS = {
    "cachorro": "Cachorro",
    "gatito": "Gatito",
    "adulto": "Adulto",
    "senior": "Senior",
    "todas": "Todas las etapas",
}

TAMANOS_RAZA = {
    "pequena": "Raza pequeña",
    "mediana": "Raza mediana",
    "grande": "Raza grande",
    "todas": "Todas las razas",
}

# Necesidades o condiciones para las que el FABRICANTE declara el alimento.
# Nunca se deduce: "tiene salmón" no es "piel sensible".
NECESIDADES = {
    "esterilizado": "Esterilizado",
    "control_peso": "Control de peso",
    "digestion_sensible": "Digestión sensible",
    "piel_sensible": "Piel sensible",
    "urinaria": "Salud urinaria",
    "actividad_alta": "Actividad alta",
    "libre_granos": "Libre de granos",
    "ingredientes_limitados": "Ingredientes limitados",
    "hipoalergenico": "Hipoalergénico",
    "articulaciones": "Articulaciones",
}

# Beneficios que el fabricante declara explícitamente. `texto` corto en la
# ficha lo pone quien carga; la etiqueta visible sale de acá.
BENEFICIOS = {
    "digestion": "Digestión saludable",
    "prebioticos_probioticos": "Prebióticos y probióticos",
    "piel_pelaje": "Piel y pelaje",
    "omega": "Omega 3 y 6",
    "inmunidad": "Sistema inmunológico",
    "articulaciones": "Articulaciones",
    "control_peso": "Control de peso",
    "urinaria": "Salud urinaria",
    "alta_proteina": "Alta proteína",
    "desarrollo": "Crecimiento y desarrollo",
    "dha": "DHA",
    "corazon": "Salud del corazón",
    "dental": "Salud dental",
    "masa_muscular": "Masa muscular",
    "energia": "Energía y vitalidad",
    "vision": "Visión",
    "bolas_pelo": "Control de bolas de pelo",
    "hidratacion": "Hidratación",
    "sabor": "Alta palatabilidad",
    "antioxidantes": "Antioxidantes",
}

# Nutrientes del análisis garantizado. La clave permite comparar dos fichas
# aunque un fabricante escriba "Crude Protein" y otro "Proteína bruta".
NUTRIENTES = {
    "proteina": "Proteína cruda",
    "grasa": "Grasa cruda",
    "fibra": "Fibra cruda",
    "humedad": "Humedad",
    "cenizas": "Cenizas",
    "calcio": "Calcio",
    "fosforo": "Fósforo",
    "sodio": "Sodio",
    "potasio": "Potasio",
    "magnesio": "Magnesio",
    "hierro": "Hierro",
    "zinc": "Zinc",
    "selenio": "Selenio",
    "vitamina_a": "Vitamina A",
    "vitamina_d3": "Vitamina D3",
    "vitamina_e": "Vitamina E",
    "omega3": "Ácidos grasos omega 3",
    "omega6": "Ácidos grasos omega 6",
    "dha": "DHA",
    "epa": "EPA",
    "taurina": "Taurina",
    "l_carnitina": "L-carnitina",
    "glucosamina": "Glucosamina",
    "condroitina": "Condroitina",
    "acido_linoleico": "Ácido linoleico",
    "microorganismos": "Microorganismos totales",
    "otro": "Otro",
}

# Cómo lo declara el fabricante: se muestra tal cual, nunca se pierde.
CALIFICADORES = {"min": "mín.", "max": "máx.", "": ""}

ESTADOS = {
    "sin_investigar": "Sin investigar",
    "parcial": "Parcial",
    "verificado": "Verificado",
    "revisar": "Requiere revisión",
}

TIPOS_FUENTE = {
    "fabricante": "Sitio oficial del fabricante",
    "distribuidor_cr": "Distribuidor oficial en Costa Rica",
    "ficha_tecnica": "Ficha técnica oficial",
    "empaque": "Empaque del producto",
}

LISTAS = {
    "etapas": ETAPAS,
    "tamanos_raza": TAMANOS_RAZA,
    "necesidades": NECESIDADES,
}
