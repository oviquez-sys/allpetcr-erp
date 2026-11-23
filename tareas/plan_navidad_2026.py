"""Plan de mercadeo de 4 semanas (Navidad 2026), tal como quedó el 23/11/2026.

Lo carga una sola vez la migración `0002_plan_navidad_2026`. Es una foto de
ese día: si el plan cambia, se corrige desde el admin (Tareas del día), no
editando este archivo, porque la migración ya corrió en el servidor.

El plan completo, con guiones y textos, está en el documento de `ENLACE`.
Quién hace cada tarea es la propuesta del plan («Equipo: quién hace qué»):
se puede cambiar en cada tarea desde la pantalla.
"""

CLAVE = "navidad-2026"
NOMBRE = "Plan de mercadeo · Navidad 2026"
INICIO = "2026-11-23"
FIN = "2026-12-24"
HITO = "Sorteo"
HITO_FECHA = "2026-12-24"
ENLACE = "https://claude.ai/artifact/69qFpm2ZZwvVoA1wB9WeF8"

# Rutina de lunes a sábado (0 = lunes … 5 = sábado), solo durante el plan.
RUTINAS = [
    {"clave": "responder", "orden": 10, "hora": "9 a.m.", "titulo": "Responder mensajes y comentarios", "detalle": "15 minutos. Oscar: Instagram. Francisco: WhatsApp y Facebook. Nadie espera más de una hora; respuestas listas en el texto 10.", "responsable": "AMB", "dias": "012345", "minimo": True, "con_historias": False},
    {"clave": "historias-am", "orden": 20, "hora": "9:30 a.m.", "titulo": "Subir 2 historias de la mañana", "detalle": "El sorteo, con sticker de enlace y cuenta regresiva, y «Pedí en línea», con sticker de enlace a allpetcr.com.", "responsable": "OSC", "dias": "012345", "minimo": True, "con_historias": True},
    {"clave": "grabar", "orden": 30, "hora": "Todo el día", "titulo": "Grabar 3 momentos de 10 segundos", "detalle": "Mascotas, entregas y mercadería que llega. Siempre con permiso.", "responsable": "AMB", "dias": "012345", "minimo": False, "con_historias": False},
    {"clave": "caja", "orden": 40, "hora": "Todo el día", "titulo": "En caja: preguntar, pedir la reseña e invitar al sorteo", "detalle": "«¿Cómo nos conociste?» (anotarlo en la hoja de conteo), el QR de reseñas a todo cliente contento (texto 1) y la invitación al sorteo. Nunca premios a cambio de reseñas.", "responsable": "AMB", "dias": "012345", "minimo": True, "con_historias": False},
    {"clave": "post1h", "orden": 50, "hora": "Al publicar", "titulo": "Primera hora después de publicar", "detalle": "Responder todos los comentarios y mandar el enlace de la publicación a 5 contactos.", "responsable": "AMB", "dias": "012345", "minimo": False, "con_historias": False},
    {"clave": "cierre4", "orden": 60, "hora": "4 p.m.", "titulo": "Cierre de pedidos del día", "detalle": "Juntar las entregas en una sola salida y anotar los kilómetros y minutos de cada una.", "responsable": "FRA", "dias": "012345", "minimo": False, "con_historias": False},
    {"clave": "historias-pm", "orden": 70, "hora": "Tarde", "titulo": "Subir 2 historias con lo grabado", "detalle": "", "responsable": "OSC", "dias": "012345", "minimo": False, "con_historias": False},
    {"clave": "anotar", "orden": 80, "hora": "7 p.m.", "titulo": "Anotar el día en el tablero de números", "detalle": "5 minutos: clientes, ventas, pedidos en línea, reseñas y «¿cómo nos conociste?». Está en la pestaña Tablero de números del plan.", "responsable": "OSC", "dias": "012345", "minimo": True, "con_historias": False},
]

SEMANAS = [
    {"clave": "s1", "nombre": "Semana 1", "titulo": "AllPet también es tienda en línea", "inicio": "2026-11-23", "fin": "2026-11-29", "objetivo": "Que Heredia sepa que puede pedir en allpetcr.com o por WhatsApp y recibirlo hoy.", "meta": "2 pedidos en línea · 6 reseñas · 270 seguidores · 60 inscritos nuevos (de unos 45 a 105)", "anuncios": "Anuncio 1 (sorteo) hasta el sábado 28 · anuncio 2 (entrega hoy) desde el jueves 26", "nota": "Todas las descripciones cierran con «📲 Pedí en allpetcr.com o al WhatsApp 8856-2992 · Antes de las 4 p.m., te llega hoy en Heredia»."},
    {"clave": "s2", "nombre": "Semana 2", "titulo": "Te lo llevamos hoy, y las personas detrás de la tienda", "inicio": "2026-11-30", "fin": "2026-12-06", "objetivo": "Convertir la curiosidad en pedidos y mostrar quiénes son ustedes.", "meta": "4 pedidos en línea · 12 reseñas · 330 seguidores · 1 colaboración cerrada", "anuncios": "Anuncio 2 hasta el martes 1 · anuncio 3 (regalos, ₡8.000) desde el jueves 3", "nota": ""},
    {"clave": "s3", "nombre": "Semana 3", "titulo": "Aguinaldo y regalos", "inicio": "2026-12-07", "fin": "2026-12-13", "objetivo": "Capturar las compras de regalos con el aguinaldo.", "meta": "6 pedidos en línea · 20 reseñas · 400 seguidores · 1 colaboración publicada", "anuncios": "Anuncio 3 hasta el miércoles 9 · anuncio 4 (cierre, ₡10.000) desde el jueves 10", "nota": ""},
    {"clave": "s4", "nombre": "Semana 4", "titulo": "Última hora", "inicio": "2026-12-14", "fin": "2026-12-20", "objetivo": "Crear urgencia: últimos días para regalos, entregas y sorteo.", "meta": "6 pedidos en línea · 27 reseñas · 470 seguidores", "anuncios": "Anuncio 4 hasta el domingo 20", "nota": ""},
    {"clave": "s5", "nombre": "Cierre", "titulo": "Sorteo en vivo", "inicio": "2026-12-21", "fin": "2026-12-24", "objetivo": "La última ola de inscripciones y un sorteo transparente que deje confianza y seguidores.", "meta": "Al 24 de diciembre: 20 pedidos en línea en el período · 30 reseñas · 500 seguidores · 300 inscritos nuevos", "anuncios": "", "nota": ""},
]

# Cada día: su contexto y sus tareas puntuales (las de rutina salen de RUTINAS).
DIAS = [
    {
        "fecha": "2026-11-23", "etiqueta": "Día de arreglos", "historias": "«¿Sabías que podés pedir en línea?» + sorteo",
        "claude": "Revisa el perfil de Google y deja lista la descripción.", "nota": "Si no alcanza hoy, terminen el martes: lo que quede sin marcar aparece mañana en «Quedaron pendientes».",
        "tienda_cerrada": False, "sin_rutinas": ["post1h"],
        "tareas": [
            {"clave": "1123-gmaps", "orden": 10, "hora": "", "titulo": "Google Maps: dirección, descripción y atributos", "detalle": "Referencia «25 m al norte, en diagonal a FarmaValue Heredia»; descripción del texto 2; estacionamiento, entrega a domicilio y retiro en tienda; enlace a allpetcr.com.", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-fotos", "orden": 20, "hora": "", "titulo": "Google Maps: subir 10 fotos", "detalle": "Fachada con parqueo, pasillos, el árbol, la caja y ustedes dos.", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-qr", "orden": 30, "hora": "", "titulo": "QR de reseñas para la caja", "detalle": "En Google Maps tocá «Pedir reseñas», copiá el enlace, convertilo en QR e imprimilo con el texto 1.", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-igbio", "orden": 40, "hora": "", "titulo": "Instagram: enlace de la biografía y destacadas", "detalle": "Enlace: https://www.allpetcr.com/navidad?o=ig-bio · Destacadas: «Sorteo», «Pedí en línea» y «Cómo llegar».", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-aviso", "orden": 50, "hora": "", "titulo": "Aviso de entrega hoy en la web y en la caja", "detalle": "«Pedí antes de las 4 p.m. y te llega hoy en Heredia». Barra de la web y cartel con QR: texto 16.", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-whatsapp", "orden": 60, "hora": "", "titulo": "WhatsApp Business: catálogo y mensajes automáticos", "detalle": "Catálogo con los 20 productos más vendidos y su precio; respuestas rápidas (texto 5); bienvenida y ausencia (texto 6).", "responsable": "FRA", "tipo": "ARR"},
            {"clave": "1123-tiktok", "orden": 70, "hora": "", "titulo": "Abrir TikTok @allpetcr", "detalle": "Con la biografía del texto 7.", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-metricool", "orden": 80, "hora": "", "titulo": "Terminar de conectar Metricool", "detalle": "Los pasos están en la pestaña IA y automatización del plan.", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-fbadmin", "orden": 90, "hora": "", "titulo": "Facebook: agregar un segundo administrador", "detalle": "Oscar u otra persona de confianza, por si se restringe la cuenta de Francisco.", "responsable": "FRA", "tipo": "ARR"},
            {"clave": "1123-inscritos", "orden": 100, "hora": "", "titulo": "Anotar cuántos inscritos hay hoy y de qué origen", "detalle": "Hoy son unos 45. Falta ver de dónde vinieron: ig-anuncio, ig-bio, whatsapp…", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-conteo", "orden": 110, "hora": "", "titulo": "Hoja de conteo «¿Cómo nos conociste?» en la caja", "detalle": "Está en la pestaña Tablero de números del plan.", "responsable": "OSC", "tipo": "ARR"},
            {"clave": "1123-contactos", "orden": 120, "hora": "", "titulo": "Mandar el texto 3 a sus contactos", "detalle": "Para que comenten el sorteo y lo compartan.", "responsable": "AMB", "tipo": "CRE"},
            {"clave": "1123-clienteD1", "orden": 130, "hora": "", "titulo": "Conseguir un cliente para el reel D1 del miércoles", "detalle": "Que acepte salir recibiendo su pedido. Si nadie acepta, graben la preparación y la salida del carro sin mostrar a nadie.", "responsable": "FRA", "tipo": "SEM"},
        ],
    },
    {
        "fecha": "2026-11-24", "etiqueta": "", "historias": "Detrás de cámaras",
        "claude": "Texto en pantalla y descripción del reel C.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1124-grabar", "orden": 10, "hora": "8 a.m.", "titulo": "Grabar en bloque los videos de la semana", "detalle": "De 8 a 9 a.m., antes de abrir. Reels: C, D1 y P. Guiones en la pestaña Guiones y formatos.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1124-roles", "orden": 20, "hora": "", "titulo": "Confirmar quién hace qué", "detalle": "Revisen la sección Equipo del plan y díganle a Claude si cambia algo.", "responsable": "AMB", "tipo": "DEC"},
            {"clave": "1124-pub", "orden": 30, "hora": "6 p.m.", "titulo": "Publicar el reel «Así pedís en allpetcr.com en 30 segundos»", "detalle": "Guion C. Cierre de la descripción: «📲 Pedí en allpetcr.com o al WhatsApp 8856-2992 · Antes de las 4 p.m., te llega hoy en Heredia». Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-11-25", "etiqueta": "", "historias": "Francisco saliendo a entregar",
        "claude": "Radar de la semana: tendencias y competencia.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1125-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar el reel «¿Se te acabó el alimento? Te lo llevamos hoy»", "detalle": "Guion D1, con el cierre de la semana. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
            {"clave": "1125-grupos", "orden": 20, "hora": "", "titulo": "Compartir en 3 grupos de Facebook", "detalle": "Texto 4. Lean las reglas de cada grupo; no más de 3 por semana.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1125-editar", "orden": 30, "hora": "", "titulo": "Editar y programar lo que sale esta semana", "detalle": "1 hora, en Metricool o en Instagram: el carrusel N (jueves), Black Friday (viernes), el reel P (sábado) y el carrusel F1 (domingo, 6 p.m.).", "responsable": "OSC", "tipo": "SEM"},
        ],
    },
    {
        "fecha": "2026-11-26", "etiqueta": "", "historias": "Enlace a la web + encuesta «¿Ya pediste en línea?»",
        "claude": "La configuración del anuncio 2, lista para copiar.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1126-anuncio2", "orden": 10, "hora": "", "titulo": "Lanzar el anuncio 2 con el reel D1", "detalle": "₡6.000 del 26 nov al 1 dic · objetivo «Mensajes» por WhatsApp · público Heredia 4 km, 25 a 54 años · desde instagram.com en la computadora.", "responsable": "OSC", "tipo": "ANU"},
            {"clave": "1126-google", "orden": 20, "hora": "", "titulo": "Novedad en Google", "detalle": "Texto 15a: en el perfil, «Agregar novedad» con una foto y el botón a https://www.allpetcr.com/?o=google", "responsable": "OSC", "tipo": "CRE"},
            {"clave": "1126-pub", "orden": 30, "hora": "6 p.m.", "titulo": "Publicar el carrusel «3 formas de comprar en AllPet»", "detalle": "Guion N, con el cierre de la semana. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-11-27", "etiqueta": "Black Friday", "historias": "La oferta + cuenta regresiva (historia del texto 8)",
        "claude": "Diseña la imagen de Black Friday.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1127-manada", "orden": 10, "hora": "", "titulo": "Mensaje a La manada", "detalle": "Texto 11a. Solo a quienes aceptaron recibir promociones.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1127-contactos", "orden": 20, "hora": "", "titulo": "Mensaje a contactos", "detalle": "Texto 3, por WhatsApp.", "responsable": "AMB", "tipo": "CRE"},
            {"clave": "1127-pub", "orden": 30, "hora": "6 p.m.", "titulo": "Publicar «Black Friday en línea»", "detalle": "Guion L y descripción del texto 8: desde ₡20.000, entrega gratis en Heredia y doble puntaje en el sorteo. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-11-28", "etiqueta": "Black Friday", "historias": "Clientes del día; sigue el Black Friday",
        "claude": "Lee los resultados del anuncio 1.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1128-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar el reel «Las 5 etapas de quedarte sin alimento»", "detalle": "Guion P, con el cierre de la semana. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
            {"clave": "1128-anuncio1", "orden": 20, "hora": "", "titulo": "Termina el anuncio 1: anotar resultados", "detalle": "Visitas, costo por visita y cuántos inscritos llegaron con origen ig-anuncio.", "responsable": "OSC", "tipo": "ANU"},
        ],
    },
    {
        "fecha": "2026-11-29", "etiqueta": "", "historias": "",
        "claude": "Llena el tablero y propone la semana 2.", "nota": "",
        "tienda_cerrada": True, "sin_rutinas": [],
        "tareas": [
            {"clave": "1129-pub", "orden": 10, "hora": "6 p.m.", "titulo": "Revisar que salió el carrusel «5 regalos para tu perro por menos de ₡10.000»", "detalle": "Guion F1 · programada a las 6 p.m. En la primera hora, responder todos los comentarios.", "responsable": "OSC", "tipo": "PUB"},
            {"clave": "1129-cierre", "orden": 20, "hora": "", "titulo": "Cierre de semana con Claude (30 min)", "detalle": "Tablero de números al día, qué funcionó y qué cambia en la semana 2.", "responsable": "AMB", "tipo": "SEM"},
        ],
    },
    {
        "fecha": "2026-11-30", "etiqueta": "", "historias": "Sorteo: faltan 24 días",
        "claude": "Propone las cuentas para colaborar y el mensaje.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1130-semana", "orden": 10, "hora": "", "titulo": "Revisar la propuesta de la semana y conseguir lo de los videos", "detalle": "30 minutos: mascotas, clientes y productos para grabar mañana.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1130-producto", "orden": 20, "hora": "", "titulo": "Decidir cuánto producto dar en colaboraciones", "detalle": "Recomendación de Claude: hasta ₡30.000 en producto para 2 o 3 colaboraciones.", "responsable": "AMB", "tipo": "DEC"},
            {"clave": "1130-colab", "orden": 30, "hora": "", "titulo": "Escribirles a 5 cuentas de mascotas de Heredia para colaborar", "detalle": "Texto 12, por mensaje directo. Claude propone las cuentas.", "responsable": "OSC", "tipo": "CRE"},
            {"clave": "1130-pub", "orden": 40, "hora": "12 m.", "titulo": "Publicar el reel «Así es por dentro la tienda del centro de Heredia»", "detalle": "Guion B. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-01", "etiqueta": "", "historias": "Detrás de cámaras",
        "claude": "Guion del reel O con las horas reales del día.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1201-grabar", "orden": 10, "hora": "8 a.m.", "titulo": "Grabar en bloque los videos de la semana", "detalle": "De 8 a 9 a.m., antes de abrir. Reels: O, G1, H, Q y A. Guiones en la pestaña Guiones y formatos.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1201-anuncio2", "orden": 20, "hora": "", "titulo": "Termina el anuncio 2: anotar resultados", "detalle": "Conversaciones de WhatsApp, costo por conversación y cuántas terminaron en pedido.", "responsable": "OSC", "tipo": "ANU"},
            {"clave": "1201-pub", "orden": 30, "hora": "6 p.m.", "titulo": "Publicar el reel «Un día en AllPet, con horas»", "detalle": "Guion O. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-02", "etiqueta": "", "historias": "Encuesta: «¿Tu perro le tiene miedo a la pólvora?»",
        "claude": "Radar de la semana.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1202-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar el reel de pólvora 1: «3 cosas para preparar a tu perro»", "detalle": "Guion G1. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
            {"clave": "1202-grupos", "orden": 20, "hora": "", "titulo": "Compartir en 3 grupos de Facebook", "detalle": "Texto 4. Lean las reglas de cada grupo; no más de 3 por semana.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1202-editar", "orden": 30, "hora": "", "titulo": "Editar y programar lo que sale esta semana", "detalle": "1 hora, en Metricool o en Instagram: H (jueves), Q (viernes), A (sábado) y el carrusel S (domingo, 6 p.m.).", "responsable": "OSC", "tipo": "SEM"},
        ],
    },
    {
        "fecha": "2026-12-03", "etiqueta": "", "historias": "Caja de preguntas: «¿Qué querés que traigamos?»",
        "claude": "Elige con los datos la pieza del anuncio 3.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1203-anuncio3", "orden": 10, "hora": "", "titulo": "Lanzar el anuncio 3", "detalle": "₡8.000 del 3 al 9 dic · «Visitas al sitio web» con https://www.allpetcr.com/catalogo?o=ig-anuncio3 · el radio que salió más barato · la pieza F1 o B, según los datos.", "responsable": "OSC", "tipo": "ANU"},
            {"clave": "1203-manada", "orden": 20, "hora": "", "titulo": "Mensaje a La manada", "detalle": "Texto 11b. Solo a quienes aceptaron recibir promociones.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1203-google", "orden": 30, "hora": "", "titulo": "Novedad en Google", "detalle": "Texto 15b: en el perfil, «Agregar novedad» con una foto y el botón a https://www.allpetcr.com/?o=google", "responsable": "OSC", "tipo": "CRE"},
            {"clave": "1203-pub", "orden": 40, "hora": "6 p.m.", "titulo": "Publicar el reel «Siento que no hicimos mucho este año…»", "detalle": "Guion H. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-04", "etiqueta": "", "historias": "Cuenta regresiva: faltan 20 días",
        "claude": "Redacta los mensajes personalizados de «Repetí tu pedido».", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1204-repeti", "orden": 10, "hora": "", "titulo": "«Repetí tu pedido» a clientes", "detalle": "Texto 9, por WhatsApp, solo a clientes que aceptaron mensajes.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1204-pub", "orden": 20, "hora": "6 p.m.", "titulo": "Publicar el reel «Querido Santa»", "detalle": "Guion Q. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-05", "etiqueta": "", "historias": "Mascotas en el árbol durante el día",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1205-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar el reel «Su primera foto navideña»", "detalle": "Guion A. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
            {"clave": "1205-fotos", "orden": 20, "hora": "", "titulo": "Compartir en historias las fotos que suban los clientes", "detalle": "Las que los etiqueten desde el árbol.", "responsable": "OSC", "tipo": "CRE"},
        ],
    },
    {
        "fecha": "2026-12-06", "etiqueta": "", "historias": "",
        "claude": "Tablero y propuesta de la semana 3.", "nota": "",
        "tienda_cerrada": True, "sin_rutinas": [],
        "tareas": [
            {"clave": "1206-pub", "orden": 10, "hora": "6 p.m.", "titulo": "Revisar que salió el carrusel «Cada día, cada semana, cada mes»", "detalle": "Guion S · programada a las 6 p.m. En la primera hora, responder todos los comentarios.", "responsable": "OSC", "tipo": "PUB"},
            {"clave": "1206-cierre", "orden": 20, "hora": "", "titulo": "Cierre de semana con Claude (30 min)", "detalle": "Tablero de números al día, qué funcionó y qué cambia en la semana 3.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1206-decidir", "orden": 30, "hora": "", "titulo": "Decidir: empaque de regalo gratis y abrir el domingo 13", "detalle": "Recomendación de Claude: empaque sí, si cuesta poco por regalo; abrir el 13 de prueba y decidir el 20 con lo que pase.", "responsable": "AMB", "tipo": "DEC"},
        ],
    },
    {
        "fecha": "2026-12-07", "etiqueta": "", "historias": "Sorteo: faltan 17 días",
        "claude": "Guion del reel R con productos y precios reales.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1207-semana", "orden": 10, "hora": "", "titulo": "Revisar la propuesta de la semana y conseguir lo de los videos", "detalle": "30 minutos: mascotas, clientes y productos para grabar mañana.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1207-colab", "orden": 20, "hora": "", "titulo": "Publicar la colaboración 1, si está lista", "detalle": "Publicación en colaboración, para que salga en las dos cuentas.", "responsable": "OSC", "tipo": "CRE"},
            {"clave": "1207-pub", "orden": 30, "hora": "12 m.", "titulo": "Publicar el reel «Regalo de ₡5.000, ₡10.000 y ₡20.000»", "detalle": "Guion R. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-08", "etiqueta": "", "historias": "Detrás de cámaras",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1208-grabar", "orden": 10, "hora": "8 a.m.", "titulo": "Grabar en bloque los videos de la semana", "detalle": "De 8 a 9 a.m., antes de abrir. Reels: G2, I1, D2, T y K. Guiones en la pestaña Guiones y formatos.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1208-canasta", "orden": 20, "hora": "", "titulo": "Armar la canasta real del sorteo", "detalle": "Los 15 productos, lista para el reel de mañana.", "responsable": "AMB", "tipo": "SOR"},
            {"clave": "1208-pub", "orden": 30, "hora": "6 p.m.", "titulo": "Publicar el reel de pólvora 2: «La noche de pólvora»", "detalle": "Guion G2. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-09", "etiqueta": "", "historias": "Un producto de la canasta por historia",
        "claude": "Radar de la semana.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1209-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar el reel «Armamos la canasta del sorteo»", "detalle": "Guion I1. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
            {"clave": "1209-grupos", "orden": 20, "hora": "", "titulo": "Compartir en 3 grupos de Facebook", "detalle": "Texto 4. Lean las reglas de cada grupo; no más de 3 por semana.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1209-editar", "orden": 30, "hora": "", "titulo": "Editar y programar lo que sale esta semana", "detalle": "1 hora, en Metricool o en Instagram: D2 (jueves), T (viernes), K (sábado) y el carrusel F3 (domingo, 6 p.m.).", "responsable": "OSC", "tipo": "SEM"},
            {"clave": "1209-anuncio3", "orden": 40, "hora": "", "titulo": "Termina el anuncio 3: anotar resultados", "detalle": "Visitas, costo por visita y pedidos o inscritos con origen ig-anuncio3.", "responsable": "OSC", "tipo": "ANU"},
        ],
    },
    {
        "fecha": "2026-12-10", "etiqueta": "", "historias": "Enlace a la web",
        "claude": "La configuración del anuncio 4.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1210-anuncio4", "orden": 10, "hora": "", "titulo": "Lanzar el anuncio 4", "detalle": "₡10.000 del 10 al 20 dic · «Visitas al sitio web» con https://www.allpetcr.com/navidad?o=ig-anuncio4 · el reel R o D2, con el sorteo de cierre.", "responsable": "OSC", "tipo": "ANU"},
            {"clave": "1210-manada", "orden": 20, "hora": "", "titulo": "Mensaje a La manada", "detalle": "Texto 11c. Solo a quienes aceptaron recibir promociones.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1210-google", "orden": 30, "hora": "", "titulo": "Novedad en Google", "detalle": "Texto 15c: en el perfil, «Agregar novedad» con una foto y el botón a https://www.allpetcr.com/?o=google", "responsable": "OSC", "tipo": "CRE"},
            {"clave": "1210-pub", "orden": 40, "hora": "6 p.m.", "titulo": "Publicar el reel «Pediste antes de las 4, llegó hoy»", "detalle": "Guion D2: una entrega real. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-11", "etiqueta": "", "historias": "Cuenta regresiva: faltan 13 días",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1211-contactos", "orden": 10, "hora": "", "titulo": "Mensaje a contactos", "detalle": "Texto 3, por WhatsApp.", "responsable": "AMB", "tipo": "CRE"},
            {"clave": "1211-pub", "orden": 20, "hora": "6 p.m.", "titulo": "Publicar el reel «Ranking de juguetes según [mascota]»", "detalle": "Guion T, con una mascota de la tienda o de un cliente. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-12", "etiqueta": "", "historias": "Clientes del día",
        "claude": "Preguntas para el en vivo.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1212-envivo", "orden": 10, "hora": "11 a.m.", "titulo": "Opcional: en vivo de 10 minutos con 5 regalos", "detalle": "Claude les deja las preguntas.", "responsable": "OSC", "tipo": "PUB"},
            {"clave": "1212-pub", "orden": 20, "hora": "12 m.", "titulo": "Publicar el reel «¿Por qué venís a AllPet?»", "detalle": "Guion K. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-13", "etiqueta": "", "historias": "",
        "claude": "Tablero y propuesta de la semana 4.", "nota": "",
        "tienda_cerrada": True, "sin_rutinas": [],
        "tareas": [
            {"clave": "1213-pub", "orden": 10, "hora": "6 p.m.", "titulo": "Revisar que salió el carrusel «Regalos para quien ama a su mascota»", "detalle": "Guion F3 · programada a las 6 p.m. En la primera hora, responder todos los comentarios.", "responsable": "OSC", "tipo": "PUB"},
            {"clave": "1213-cierre", "orden": 20, "hora": "", "titulo": "Cierre de semana con Claude (30 min)", "detalle": "Tablero de números al día, qué funcionó y qué cambia en la semana 4.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1213-decidir", "orden": 30, "hora": "", "titulo": "Decidir: abrir el domingo 20, último día de entregas y horario del 24", "detalle": "Recomendación de Claude para las entregas: hasta el 23 de diciembre a las 4 p.m.", "responsable": "AMB", "tipo": "DEC"},
        ],
    },
    {
        "fecha": "2026-12-14", "etiqueta": "", "historias": "Sorteo: faltan 10 días",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1214-semana", "orden": 10, "hora": "", "titulo": "Revisar la propuesta de la semana y conseguir lo de los videos", "detalle": "30 minutos: mascotas, clientes y productos para grabar mañana.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1214-colab", "orden": 20, "hora": "", "titulo": "Publicar la colaboración 2", "detalle": "Publicación en colaboración con la segunda cuenta.", "responsable": "OSC", "tipo": "CRE"},
            {"clave": "1214-pub", "orden": 30, "hora": "12 m.", "titulo": "Publicar el carrusel «Regalos de última hora por presupuesto»", "detalle": "Guion F4. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-15", "etiqueta": "", "historias": "Detrás de cámaras",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1215-grabar", "orden": 10, "hora": "8 a.m.", "titulo": "Grabar en bloque los videos de la semana", "detalle": "De 8 a 9 a.m., antes de abrir. Reels: G3, U, D3, B2 y E. Guiones en la pestaña Guiones y formatos.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1215-pub", "orden": 20, "hora": "6 p.m.", "titulo": "Publicar el reel de pólvora 3: «El kit para el 24 y el 31»", "detalle": "Guion G3. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-16", "etiqueta": "", "historias": "",
        "claude": "Radar de la semana.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1216-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar el reel «Yo vs. yo»", "detalle": "Guion U. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
            {"clave": "1216-grupos", "orden": 20, "hora": "", "titulo": "Compartir en 3 grupos de Facebook", "detalle": "Texto 4. Lean las reglas de cada grupo; no más de 3 por semana.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1216-editar", "orden": 30, "hora": "", "titulo": "Editar y programar lo que sale esta semana", "detalle": "1 hora, en Metricool o en Instagram: D3 (jueves), B2 (viernes), E (sábado) y la publicación I2 (domingo, 6 p.m.).", "responsable": "OSC", "tipo": "SEM"},
        ],
    },
    {
        "fecha": "2026-12-17", "etiqueta": "", "historias": "Enlace a la web",
        "claude": "Lee cómo va el anuncio 4.", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1217-manada", "orden": 10, "hora": "", "titulo": "Mensaje a La manada", "detalle": "Texto 11d. Solo a quienes aceptaron recibir promociones.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1217-google", "orden": 20, "hora": "", "titulo": "Novedad en Google", "detalle": "Texto 15d: en el perfil, «Agregar novedad» con una foto y el botón a https://www.allpetcr.com/?o=google", "responsable": "OSC", "tipo": "CRE"},
            {"clave": "1217-pub", "orden": 30, "hora": "6 p.m.", "titulo": "Publicar el reel «Último día de entregas antes de Navidad»", "detalle": "Guion D3. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-18", "etiqueta": "", "historias": "Cuenta regresiva: faltan 6 días",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1218-contactos", "orden": 10, "hora": "", "titulo": "Mensaje a contactos y clientes", "detalle": "Texto 3, por WhatsApp.", "responsable": "AMB", "tipo": "CRE"},
            {"clave": "1218-pub", "orden": 20, "hora": "6 p.m.", "titulo": "Publicar el reel «Envolvemos tu regalo» o «Último fin de semana para tus regalos»", "detalle": "Guion B2. «Envolvemos tu regalo» solo si decidieron dar empaque gratis. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-19", "etiqueta": "", "historias": "Historias durante todo el día",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1219-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar el reel «Aquí la mascota escoge»", "detalle": "Guion E. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-20", "etiqueta": "", "historias": "",
        "claude": "Tablero y plan del cierre.", "nota": "",
        "tienda_cerrada": True, "sin_rutinas": [],
        "tareas": [
            {"clave": "1220-pub", "orden": 10, "hora": "6 p.m.", "titulo": "Revisar que salió «Faltan 4 días para el sorteo»", "detalle": "Guion I2 · programada a las 6 p.m. En la primera hora, responder todos los comentarios.", "responsable": "OSC", "tipo": "PUB"},
            {"clave": "1220-cierre", "orden": 20, "hora": "", "titulo": "Cierre de semana con Claude (30 min)", "detalle": "Tablero de números al día, qué funcionó y qué cambia en el cierre.", "responsable": "AMB", "tipo": "SEM"},
            {"clave": "1220-exportar", "orden": 30, "hora": "", "titulo": "Exportar de prueba la lista de inscritos", "detalle": "Para el sorteo del 24: que salga completa y se pueda numerar.", "responsable": "OSC", "tipo": "SOR"},
            {"clave": "1220-anuncio4", "orden": 40, "hora": "", "titulo": "Termina el anuncio 4: anotar resultados", "detalle": "Visitas, costo por visita e inscritos o pedidos con origen ig-anuncio4.", "responsable": "OSC", "tipo": "ANU"},
        ],
    },
    {
        "fecha": "2026-12-21", "etiqueta": "", "historias": "Cuenta regresiva",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1221-mensajes", "orden": 10, "hora": "", "titulo": "Mensaje a contactos y a La manada", "detalle": "Texto 3 a contactos; a La manada, solo a quienes aceptaron promociones.", "responsable": "AMB", "tipo": "CRE"},
            {"clave": "1221-pub", "orden": 20, "hora": "12 m.", "titulo": "Publicar «Últimos 3 días para inscribirte»", "detalle": "Guion I3 y texto 13. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-22", "etiqueta": "", "historias": "Enlace a la web",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1222-pedidos", "orden": 10, "hora": "", "titulo": "Confirmar los pedidos pendientes", "detalle": "Que cada pedido tenga su entrega antes del 23 a las 4 p.m.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1222-pub", "orden": 20, "hora": "6 p.m.", "titulo": "Publicar el reel «Mañana es el último día de entregas»", "detalle": "Guion D4. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
        ],
    },
    {
        "fecha": "2026-12-23", "etiqueta": "Último día de entregas", "historias": "Sticker «Recordarme» para el en vivo",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": [],
        "tareas": [
            {"clave": "1223-pub", "orden": 10, "hora": "12 m.", "titulo": "Publicar «Mañana sorteamos en vivo a las 10 a.m.»", "detalle": "Con el sticker «Recordarme» en las historias. Oscar: Instagram y TikTok · Francisco: Facebook.", "responsable": "AMB", "tipo": "PUB"},
            {"clave": "1223-entregas", "orden": 20, "hora": "4 p.m.", "titulo": "Últimas entregas antes de Navidad", "detalle": "Todo lo pedido sale antes de las 4 p.m.", "responsable": "FRA", "tipo": "CRE"},
            {"clave": "1223-lista", "orden": 30, "hora": "11:59 p.m.", "titulo": "Cerrar inscripciones y exportar la lista numerada", "detalle": "A las 11:59 p.m. Cada número extra (comentario, foto en el árbol, datos de la mascota, compra de más de ₡20.000) es una línea más para esa persona.", "responsable": "OSC", "tipo": "SOR"},
        ],
    },
    {
        "fecha": "2026-12-24", "etiqueta": "Sorteo en vivo", "historias": "Agradecimiento",
        "claude": "", "nota": "",
        "tienda_cerrada": False, "sin_rutinas": ["cierre4"],
        "tareas": [
            {"clave": "1224-sorteo", "orden": 10, "hora": "10 a.m.", "titulo": "Sorteo en vivo desde la tienda", "detalle": "En vivo de Instagram con la canasta a la vista: mostrar la lista, buscar en Google «número aleatorio» del 1 al total y decir el nombre como dicen las bases.", "responsable": "AMB", "tipo": "SOR"},
            {"clave": "1224-ganador", "orden": 20, "hora": "", "titulo": "Publicar al ganador y guardar el en vivo en el perfil", "detalle": "Texto 14.", "responsable": "OSC", "tipo": "PUB"},
            {"clave": "1224-contactar", "orden": 30, "hora": "", "titulo": "Contactar al ganador", "detalle": "Ese mismo día, por WhatsApp o correo, para coordinar la entrega y que escoja perro o gato.", "responsable": "FRA", "tipo": "SOR"},
        ],
    },
]
