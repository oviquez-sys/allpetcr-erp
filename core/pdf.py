"""Convierte el HTML del recibo en un PDF, sin tocar el diseño.

Por qué un navegador de verdad y no una librería de PDF (02/09/2026)
--------------------------------------------------------------------
El recibo (`templates/ventas/factura.html`) está armado con CSS moderno:
flexbox, variables de color, tipografía fina. Las librerías que generan PDF
desde HTML —WeasyPrint, xhtml2pdf— soportan eso a medias o nada, y el
resultado sería un recibo distinto del que Oscar aprobó.

Chromium dibuja el HTML exactamente igual que el navegador donde se diseñó, y
después lo imprime a PDF. El diseño no se rehace ni se adapta: se usa tal
cual. Es más pesado de instalar (unos 150 MB una sola vez) y esa es toda la
desventaja.

Además resuelve dos cosas que el correo con HTML nunca iba a resolver:
  - Outlook de escritorio dibuja los correos con el motor de Word, que no
    entiende flexbox. En PDF eso deja de importar.
  - El logo se incrusta dentro del archivo y siempre se ve, en vez de ser un
    enlace a `/static/` que la computadora del cliente no puede abrir.

Si Chromium no está instalado, `html_a_pdf` devuelve None en vez de reventar:
el correo se manda igual, con el HTML como cuerpo, que es como funcionaba
hasta hoy. Un recibo feo llega; un recibo que no sale, no.
"""
import base64
import logging
from pathlib import Path

from django.contrib.staticfiles import finders

logger = logging.getLogger(__name__)

# Sin margen de papel: el recibo ya trae su propio espaciado interno y la hoja
# se dimensiona al contenido, asi que un margen extra solo agrega bordes
# blancos que no estaban en el diseno.
MARGENES = {"top": "0", "right": "0", "bottom": "0", "left": "0"}


def logo_data_uri(ruta_estatica="img/allpetcr-logo.png"):
    """El logo como texto embebible, para que viaje DENTRO del documento.

    En el navegador el logo se pide a `/static/...` y funciona porque el ERP
    está corriendo. Dentro de un PDF —o de un correo— esa dirección no existe
    para quien lo recibe, y en su lugar aparece el texto alternativo. Ese era
    el cuadrito roto que salía en Outlook.
    """
    ruta = finders.find(ruta_estatica)
    if not ruta:
        logger.warning("No se encontró el logo en %s: el recibo saldrá sin él.", ruta_estatica)
        return ""
    datos = Path(ruta).read_bytes()
    return "data:image/png;base64," + base64.b64encode(datos).decode("ascii")


# Ancho en pixeles con el que se dibuja el recibo antes de imprimirlo.
#
# El recibo esta disenado a 1040 px (`.lienzo{max-width:1040px}`) y tiene un
# corte responsive en `@media (max-width:860px)` que apila las dos columnas
# una debajo de otra, para que se vea bien en un celular.
#
# Ahi estaba el problema (02/09/2026): al pedir el PDF en tamano Carta,
# Chromium redibuja la pagina al ancho del papel —unos 816 px— que es MENOS
# que 860. O sea que se activaba la version de celular: el panel del resumen
# se bajaba debajo de la tabla y el recibo se estiraba a dos hojas.
#
# Dibujandolo a 1100 px se respeta el diseno de escritorio, el mismo que
# Oscar aprobo en el navegador, y entra en una sola pagina.
ANCHO_DISENO = 1100


def html_a_pdf(html, ancho_px=ANCHO_DISENO):
    """El HTML dibujado por Chromium e impreso a PDF. None si no se pudo.

    Devolver None y no lanzar es deliberado: quien llama decide si sigue sin
    PDF o aborta. En el envío de recibos se sigue, porque que el cliente
    reciba algo importa más que el formato.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "Playwright no está instalado: el recibo se manda sin PDF adjunto. "
            "Se instala con INSTALAR_PDF.bat."
        )
        return None

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            try:
                pagina = navegador.new_page(viewport={"width": ancho_px, "height": 1400})
                # `wait_until="load"` y no "networkidle": el HTML ya viene con
                # todo adentro (el logo como data URI), así que no hay nada que
                # esperar de la red y "networkidle" solo agregaría segundos.
                pagina.set_content(html, wait_until="load")

                # Medir CON los estilos de impresion puestos (02/09/2026).
                #
                # Este era el error: se media el alto con los estilos de
                # PANTALLA y despues `pdf()` aplicaba los de IMPRESION, que en
                # este recibo cambian el tamano de letra, quitan el relleno del
                # lienzo y esconden los botones. La hoja quedaba cortada a una
                # medida que ya no correspondia y lo que sobraba se iba a una
                # segunda pagina.
                #
                # `emulate_media` pone los estilos de impresion ANTES de medir,
                # asi el alto es el que va a tener el documento de verdad.
                pagina.emulate_media(media="print")

                # El recibo trae `@page{size:A4; margin:14mm}` en sus estilos de
                # impresion, pensado para imprimirlo en papel desde el
                # navegador. Para el PDF que se manda por correo la hoja se
                # dimensiona al contenido, asi que ese tamano fijo se anula.
                # No cambia como se ve el recibo: solo la geometria del papel.
                pagina.add_style_tag(content="""
                    @page { size: auto; margin: 0; }
                    html, body { height: auto !important; }
                    .hoja, .lienzo { break-inside: avoid; page-break-inside: avoid; }
                """)

                # Una sola pagina, del alto que haga falta, en vez de partir el
                # recibo en hojas Carta. Un recibo no es un informe: cortarlo a
                # la mitad para que la segunda hoja lleve solo el pie se ve
                # descuidado, y en pantalla —que es donde el cliente lo va a
                # abrir— no hay ninguna razon para paginarlo.
                #
                # Los 2 px de mas son colchon: si el alto calculado se queda
                # corto por un decimal de redondeo, esa fraccion de pixel abre
                # una segunda pagina en blanco.
                alto = pagina.evaluate(
                    "Math.ceil(Math.max("
                    "  document.documentElement.scrollHeight,"
                    "  document.body ? document.body.scrollHeight : 0"
                    ")) + 2"
                )
                return pagina.pdf(
                    width=f"{ancho_px}px",
                    height=f"{alto}px",
                    print_background=True,  # sin esto el PDF sale en blanco y negro
                    margin=MARGENES,
                )
            finally:
                navegador.close()
    except Exception:  # noqa: BLE001
        # Cualquier fallo de Chromium (no instalado, sin permisos, sin memoria)
        # queda en el log completo y el correo sigue su camino sin adjunto.
        logger.exception("Falló la generación del PDF; el recibo se manda sin adjunto.")
        return None
