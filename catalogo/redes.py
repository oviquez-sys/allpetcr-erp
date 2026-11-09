"""Catálogo para redes (06/11/2026, pedido de Oscar, diseño aprobado ese día).

Un botón en el ERP arma UN .zip con todo lo necesario para vender por
WhatsApp y Facebook, sacado de los datos del sistema (fotos, nombres, precios
y promociones de hoy):

    AllPetcr_catalogo_<fecha>/
      PDF/Catalogo_completo.pdf             portada + una sección por categoría
      PDF/<Categoría> - <Perro|Gato>.pdf     uno por categoría (más fácil de mandar)
      Para_WhatsApp_y_Facebook/<Categoría>/<SKU> <nombre>.jpg   foto limpia 1080
      Para_estados_y_publicaciones/<Categoría>/<SKU> <nombre>.jpg  1080 × 1350, todas las redes
      catalogo_facebook.csv                  formato de catálogo de Facebook
      lista_whatsapp.xlsx                    para copiar al catálogo de WhatsApp

Decisiones (Oscar dijo «dale» a la propuesta con estas recomendaciones):
- Con precio y con la fecha de los precios en cada página (las páginas se
  reenvían sueltas como foto). Promoción vigente = precio tachado, % y hasta
  cuándo (Ley 7472), igual que en la caja y la web.
- 9 productos por página: la foto queda de ~6 cm impresa.
- Sin foto no entra: un catálogo con huellitas en lugar de productos no vende.
- La foto limpia va SIN texto encima: WhatsApp y Facebook ponen nombre y
  precio al lado.

09/11/2026: las tarjetas 1080 × 1080 de Para_estados_y_publicaciones se
reemplazaron por las publicaciones de catalogo/publicacion.py (Oscar: «cumplen
la misma función y esto es mucho mejor»): una sola de 1080 × 1350 que sirve
para Instagram, Facebook y estados. Los alimentos con ficha llevan ingredientes, nutrición y
beneficios; lo demás, foto, nombre, peso y precio.

Se arma en segundo plano (`PaqueteRedes` + un hilo): con ~750 productos son
unos minutos, y gunicorn corta cualquier página a los 120 s.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.utils import timezone

logger = logging.getLogger(__name__)

RECURSOS = Path(__file__).resolve().parent / "redes_recursos"
NAVY = (9, 46, 94)
DORADO = (204, 149, 57)
CREMA = (250, 248, 244)
OFERTA = (194, 65, 12)
GRIS = (91, 107, 128)
LADO = 1080
WHATSAPP = "8856-2992"
WHATSAPP_URL = "https://wa.me/50688562992"
DIRECCION = "Heredia, 100 m oeste de la entrada principal de la UNA"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


# ---------------------------------------------------------------------------
# Qué productos entran
# ---------------------------------------------------------------------------
@dataclass
class Item:
    producto: object
    raiz: str
    orden: tuple
    precio: Decimal
    oferta: dict | None
    archivo: str = ""
    grupos: list = field(default_factory=list)   # PDFs por categoría donde aparece


def _limpio(texto: str, largo: int = 90) -> str:
    """Nombre de archivo que Windows acepta."""
    texto = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", texto or "").strip()
    return re.sub(r"\s+", " ", texto)[:largo].rstrip(" .")


def _mascotas(p) -> list:
    m = (p.mascota or "").lower()
    if "perro" in m and "gato" in m:
        return ["Perro", "Gato"]
    if "gato" in m:
        return ["Gato"]
    if "perro" in m:
        return ["Perro"]
    return []


def productos(empresa, *, solo_existencia=True, categoria_id=None, solo_ofertas=False):
    """(items, sin_foto): lo que entra, ordenado como la tienda, y cuántos
    quedaron fuera por no tener foto."""
    from .models import Producto
    from .promociones import oferta_de, vigentes

    qs = Producto.objects.filter(empresa=empresa, activo=True, precio_venta__gt=0) \
        .select_related("categoria__padre", "empresa", "ficha_alimento")
    if solo_existencia:
        qs = qs.filter(stock_actual__gt=0)
    if categoria_id:
        qs = qs.filter(categoria_id__in=_ids_rama(categoria_id))
    promos = vigentes(empresa)
    items, sin_foto = [], 0
    for p in qs:
        if not p.imagen:
            sin_foto += 1
            continue
        oferta = oferta_de(p, promos[p.pk]) if p.pk in promos else None
        if solo_ofertas and oferta is None:
            continue
        c = p.categoria
        raiz = (c.padre if c is not None and c.padre_id else c)
        orden = ((raiz.orden if raiz else 999), (raiz.nombre if raiz else "zz"),
                 (c.orden if c and c.padre_id else 0), (c.nombre if c else ""), p.nombre.lower())
        items.append(Item(producto=p, raiz=raiz.nombre if raiz else "Otros", orden=orden,
                          precio=oferta["precio"] if oferta else p.precio_venta, oferta=oferta))
    items.sort(key=lambda i: i.orden)
    usados = set()
    for i in items:
        base = _limpio(f"{i.producto.sku} {i.producto.nombre}")
        nombre, n = base, 2
        while nombre.lower() in usados:
            nombre, n = f"{base} ({n})", n + 1
        usados.add(nombre.lower())
        i.archivo = nombre + ".jpg"
        mascotas = _mascotas(i.producto)
        i.grupos = [f"{i.raiz} - {m}" for m in mascotas] or [i.raiz]
    return items, sin_foto


def _ids_rama(categoria_id):
    from .models import Categoria
    return [categoria_id] + list(Categoria.objects.filter(padre_id=categoria_id).values_list("pk", flat=True))


# ---------------------------------------------------------------------------
# Imágenes
# ---------------------------------------------------------------------------
def _fuente(peso, tam):
    from PIL import ImageFont
    return ImageFont.truetype(str(RECURSOS / f"Poppins-{peso}.ttf"), tam)


def _abrir_foto(producto):
    """La foto original, en RGB sobre blanco, sin el borde blanco que sobre."""
    from PIL import Image, ImageChops
    with default_storage.open(producto.imagen, "rb") as f:
        im = Image.open(io.BytesIO(f.read()))
        im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fondo = Image.new("RGB", im.size, "white")
        fondo.paste(im, mask=im.getchannel("A"))
        im = fondo
    else:
        im = im.convert("RGB")
    # Recortar el blanco de sobra: con margen propio la foto se ve chiquita.
    gris = ImageChops.difference(im, Image.new("RGB", im.size, "white")).convert("L")
    caja = gris.point(lambda v: 255 if v > 18 else 0).getbbox()
    if caja:
        im = im.crop(caja)
    return im


def _encajar(im, ancho, alto):
    from PIL import Image
    r = min(ancho / im.width, alto / im.height)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)


def foto_limpia(foto):
    """A: 1080 × 1080, fondo blanco, el producto centrado al 86 %."""
    from PIL import Image
    lienzo = Image.new("RGB", (LADO, LADO), "white")
    im = _encajar(foto, int(LADO * 0.86), int(LADO * 0.86))
    lienzo.paste(im, ((LADO - im.width) // 2, (LADO - im.height) // 2))
    return lienzo


def _envolver(draw, texto, fuente, ancho, lineas=2):
    palabras, filas, actual = texto.split(), [], ""
    for p in palabras:
        prueba = f"{actual} {p}".strip()
        if draw.textlength(prueba, font=fuente) <= ancho:
            actual = prueba
        else:
            if actual:
                filas.append(actual)
            actual = p
    if actual:
        filas.append(actual)
    if len(filas) > lineas:
        filas = filas[:lineas]
        while filas[-1] and draw.textlength(filas[-1] + "…", font=fuente) > ancho:
            filas[-1] = filas[-1][:-1]
        filas[-1] = filas[-1].rstrip() + "…"
    return filas


def _crc(valor) -> str:
    return "₡" + f"{int(Decimal(valor)):,}".replace(",", ".")


# Poppins no trae el signo del colón (₡): se dibuja con DejaVu y el número con
# Poppins. Sin esto salía un cuadrito (en la imagen) o nada (en el PDF).
def _simbolo(peso, tam):
    from PIL import ImageFont
    nombre = "DejaVuSans-Bold.ttf" if peso == "Bold" else "DejaVuSans.ttf"
    return ImageFont.truetype(str(RECURSOS / nombre), int(tam * 0.92))


def _ancho_precio(d, texto, peso, tam):
    numero = texto.lstrip("₡")
    return d.textlength("₡", font=_simbolo(peso, tam)) + d.textlength(numero, font=_fuente(peso, tam))


def _dibujar_precio(d, x, y_base, texto, peso, tam, fill):
    """Dibuja «₡5.190» con la línea base en y_base; devuelve el ancho."""
    sim, num = _simbolo(peso, tam), _fuente(peso, tam)
    d.text((x, y_base), "₡", font=sim, fill=fill, anchor="ls")
    w = d.textlength("₡", font=sim)
    d.text((x + w, y_base), texto.lstrip("₡"), font=num, fill=fill, anchor="ls")
    return w + d.textlength(texto.lstrip("₡"), font=num)


_logo_cache = {}


def _logo(nombre, ancho):
    from PIL import Image
    clave = (nombre, ancho)
    if clave not in _logo_cache:
        im = Image.open(RECURSOS / nombre).convert("RGBA")
        _logo_cache[clave] = im.resize((ancho, int(im.height * ancho / im.width)), Image.LANCZOS)
    return _logo_cache[clave]


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _registrar_fuentes():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for nombre in ("Poppins-Regular", "Poppins-Medium", "Poppins-Bold", "DejaVuSans", "DejaVuSans-Bold"):
        if nombre not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(nombre, str(RECURSOS / f"{nombre}.ttf")))


def _precio_pdf(c, x, y, texto, fuente, tam):
    """«₡5.190» en el PDF: el signo con DejaVu (Poppins no lo trae). Devuelve el ancho."""
    sim = "DejaVuSans-Bold" if fuente.endswith("Bold") else "DejaVuSans"
    c.setFont(sim, tam * 0.92)
    c.drawString(x, y, "₡")
    w = c.stringWidth("₡", sim, tam * 0.92)
    numero = texto.lstrip("₡")
    c.setFont(fuente, tam)
    c.drawString(x + w, y, numero)
    return w + c.stringWidth(numero, fuente, tam)


def _qr(c, texto, x, y, lado):
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    w = QrCodeWidget(texto)
    b = w.getBounds()
    d = Drawing(lado, lado, transform=[lado / (b[2] - b[0]), 0, 0, lado / (b[3] - b[1]), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def _hex(rgb):
    from reportlab.lib.colors import Color
    return Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)


def pdf(ruta, secciones, *, fecha, con_precio=True, portada=True):
    """`secciones` = [(titulo, subtitulo, [(item, ruta_foto_pdf)])]."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    _registrar_fuentes()
    W, H = letter
    c = canvas.Canvas(str(ruta), pagesize=letter)
    c.setTitle("Catálogo AllPetcr.com")
    c.setAuthor("AllPetcr.com")
    navy, dorado, crema, gris = _hex(NAVY), _hex(DORADO), _hex(CREMA), _hex(GRIS)
    pagina = 0
    mes = f"{MESES[fecha.month - 1].capitalize()} {fecha.year}"

    if portada:
        pagina += 1
        c.setFillColor(navy)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        logo = ImageReader(str(RECURSOS / "logo_vertical_blanco.png"))
        lw = 230
        lh = lw * 815 / 964
        c.drawImage(logo, (W - lw) / 2, H - 120 - lh, lw, lh, mask="auto")
        y = H - 120 - lh - 34
        c.setFillColor(dorado)
        c.rect(W / 2 - 40, y, 80, 3, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Poppins-Bold", 38)
        c.drawCentredString(W / 2, y - 52, "Catálogo")
        c.setFillColorRGB(0.91, 0.83, 0.66)
        c.setFont("Poppins-Regular", 17)
        c.drawCentredString(W / 2, y - 78, mes)
        c.setFillColorRGB(0.81, 0.85, 0.9)
        c.setFont("Poppins-Regular", 11.5)
        c.drawCentredString(W / 2, y - 112, "Alimento, snacks, juguetes y accesorios para perros y gatos.")
        c.drawCentredString(W / 2, y - 128, "Tienda en Heredia · pedidos por WhatsApp y en allpetcr.com.")
        for i, (texto, enlace, rotulo) in enumerate([(f"Pedí por WhatsApp", WHATSAPP_URL, WHATSAPP),
                                                     ("Mirá todo en", settings.SITIO_WEB_URL, "allpetcr.com")]):
            cx = W / 2 + (-95 if i == 0 else 95)
            c.setFillColorRGB(1, 1, 1)
            c.roundRect(cx - 40, 120, 80, 80, 6, stroke=0, fill=1)
            _qr(c, enlace, cx - 36, 124, 72)
            c.setFillColorRGB(0.81, 0.85, 0.9)
            c.setFont("Poppins-Regular", 10)
            c.drawCentredString(cx, 102, texto)
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Poppins-Bold", 14)
            c.drawCentredString(cx, 84, rotulo)
        c.showPage()

    margen, cab_alto, pie_alto = 32, 64, 56
    cols, filas = 3, 3
    gap = 10
    celda_w = (W - 2 * margen - (cols - 1) * gap) / cols
    celda_h = (H - margen - cab_alto - pie_alto - 16 - (filas - 1) * gap) / filas
    vigencia = f"Precios con IVA, válidos al {fecha:%d/%m/%Y} o hasta agotar existencias."

    def pie():
        c.setFillColor(crema)
        c.rect(0, 0, W, pie_alto - 8, stroke=0, fill=1)
        c.setFillColor(navy)
        c.setFont("Poppins-Bold", 8.5)
        c.drawString(margen, 30, f"Pedí por WhatsApp {WHATSAPP}")
        x = margen + c.stringWidth(f"Pedí por WhatsApp {WHATSAPP}", "Poppins-Bold", 8.5)
        c.setFillColor(gris)
        c.setFont("Poppins-Regular", 8.5)
        c.drawString(x, 30, f" · allpetcr.com · {DIRECCION}")
        if con_precio:
            c.drawString(margen, 17, vigencia)
        c.drawRightString(W - margen - 46, 17, f"Pág. {pagina}")
        _qr(c, WHATSAPP_URL, W - margen - 38, 8, 36)

    for titulo, subtitulo, lista in secciones:
        for inicio in range(0, len(lista), cols * filas):
            pagina += 1
            tope = H - margen
            c.setFillColor(navy)
            c.setFont("Poppins-Bold", 22)
            c.drawString(margen, tope - 24, titulo)
            c.setFillColor(gris)
            c.setFont("Poppins-Regular", 9.5)
            c.drawString(margen, tope - 40, subtitulo)
            logo = ImageReader(str(RECURSOS / "logo_horizontal.png"))
            c.drawImage(logo, W - margen - 130, tope - 36, 130, 130 * 210 / 1200, mask="auto")
            c.setFillColor(navy)
            c.rect(margen, tope - 52, W - 2 * margen, 2, stroke=0, fill=1)
            for k, (item, ruta_foto) in enumerate(lista[inicio:inicio + cols * filas]):
                fila, col = divmod(k, cols)
                x = margen + col * (celda_w + gap)
                y = tope - cab_alto - 6 - (fila + 1) * celda_h - fila * gap
                c.setStrokeColorRGB(0.9, 0.88, 0.84)
                c.setFillColorRGB(1, 1, 1)
                c.roundRect(x, y, celda_w, celda_h, 8, stroke=1, fill=1)
                foto_lado = celda_h - 78
                c.drawImage(ImageReader(str(ruta_foto)), x + (celda_w - foto_lado) / 2, y + 72, foto_lado, foto_lado,
                            preserveAspectRatio=True, anchor="c")
                p = item.producto
                c.setFillColor(navy)
                c.setFont("Poppins-Medium", 8.6)
                lineas = _envolver_pdf(c, p.nombre, "Poppins-Medium", 8.6, celda_w - 16, 2)
                for j, linea in enumerate(lineas):
                    c.drawString(x + 8, y + 58 - j * 11, linea)
                if con_precio:
                    if item.oferta:
                        c.setFillColor(_hex(OFERTA))
                        px = x + 12 + _precio_pdf(c, x + 8, y + 20, _crc(item.precio), "Poppins-Bold", 13)
                        c.setFillColor(gris)
                        aw = _precio_pdf(c, px, y + 20, _crc(item.oferta["precio_antes"]), "Poppins-Regular", 8)
                        c.setStrokeColor(gris)
                        c.line(px, y + 23, px + aw, y + 23)
                        c.setFillColor(_hex(OFERTA))
                        c.roundRect(x + celda_w - 44, y + celda_h - 24, 36, 16, 4, stroke=0, fill=1)
                        c.setFillColorRGB(1, 1, 1)
                        c.setFont("Poppins-Bold", 8.5)
                        c.drawCentredString(x + celda_w - 26, y + celda_h - 19, f"−{item.oferta['pct']}%")
                    else:
                        _precio_pdf(c, x + 8, y + 20, _crc(item.precio), "Poppins-Bold", 13)
                c.setFillColor(gris)
                c.setFont("Poppins-Regular", 7)
                c.drawRightString(x + celda_w - 8, y + 21, p.mascota or "")
                c.setFillColorRGB(0.6, 0.65, 0.71)
                c.setFont("Poppins-Regular", 6)
                c.drawString(x + 8, y + 8, p.sku)
            pie()
            c.showPage()
    c.save()


def _envolver_pdf(c, texto, fuente, tam, ancho, lineas):
    palabras, filas, actual = (texto or "").split(), [], ""
    for p in palabras:
        prueba = f"{actual} {p}".strip()
        if c.stringWidth(prueba, fuente, tam) <= ancho:
            actual = prueba
        else:
            if actual:
                filas.append(actual)
            actual = p
    if actual:
        filas.append(actual)
    if len(filas) > lineas:
        filas = filas[:lineas]
        while filas[-1] and c.stringWidth(filas[-1] + "…", fuente, tam) > ancho:
            filas[-1] = filas[-1][:-1]
        filas[-1] = filas[-1].rstrip() + "…"
    return filas


# ---------------------------------------------------------------------------
# Facebook y WhatsApp
# ---------------------------------------------------------------------------
def _enlace(producto):
    return f"{settings.SITIO_WEB_URL.rstrip('/')}/producto/{producto.sku}"


def csv_facebook(items) -> bytes:
    """Columnas del catálogo de Facebook (Administrador de ventas). El precio
    va con su moneda («5190.00 CRC») y la oferta en sale_price con su fecha."""
    from core.imagenes import url_imagen_producto
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow(["id", "title", "description", "availability", "condition", "price", "sale_price",
                "sale_price_effective_date", "link", "image_link", "brand", "product_type"])
    hoy = timezone.localdate()
    for i in items:
        p = i.producto
        precio_normal = i.oferta["precio_antes"] if i.oferta else p.precio_venta
        imagen = url_imagen_producto(p.imagen)
        if imagen.startswith("/"):
            imagen = settings.SITIO_WEB_URL.rstrip("/") + imagen
        w.writerow([
            p.sku, p.nombre[:150], (p.descripcion or p.nombre)[:5000],
            "in stock" if p.stock_actual > 0 else "out of stock", "new",
            f"{Decimal(precio_normal):.2f} CRC",
            f"{Decimal(i.oferta['precio']):.2f} CRC" if i.oferta else "",
            f"{hoy:%Y-%m-%d}T00:00-06:00/{i.oferta['hasta']:%Y-%m-%d}T23:59-06:00" if i.oferta else "",
            _enlace(p), imagen, p.marca or "AllPetcr.com", i.raiz,
        ])
    return salida.getvalue().encode("utf-8-sig")


def xlsx_whatsapp(items) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Para WhatsApp"
    ws.append(["Categoría", "Nombre", "Precio (₡)", "Precio normal (₡)", "Descripción", "Código", "Enlace web",
               "Foto (carpeta Para_WhatsApp_y_Facebook)"])
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="092E5E")
    for i in items:
        p = i.producto
        ws.append([i.raiz, p.nombre, int(i.precio), int(i.oferta["precio_antes"]) if i.oferta else None,
                   p.descripcion or "", p.sku, _enlace(p), f"{_limpio(i.raiz, 60)}/{i.archivo}"])
    for col, ancho in zip("ABCDEFGH", (20, 45, 12, 16, 60, 14, 42, 60)):
        ws.column_dimensions[col].width = ancho
    ws.freeze_panes = "A2"
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------
def generar(paquete, progreso=None):
    """Arma el .zip del `paquete` (PaqueteRedes) y lo guarda en el almacén.
    `progreso(hechos, total)` se llama cada tanto. Devuelve la ruta guardada."""
    from . import publicacion
    f = paquete.filtros or {}
    con_precio = f.get("con_precio", True)
    items, sin_foto = productos(paquete.empresa, solo_existencia=f.get("solo_existencia", True),
                                categoria_id=f.get("categoria_id"), solo_ofertas=f.get("solo_ofertas", False))
    fecha = timezone.localdate()
    carpeta = f"AllPetcr_catalogo_{fecha:%Y-%m-%d}"
    total = len(items)
    if progreso:
        progreso(0, total)
    fallaron = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ruta_zip = tmp / f"{carpeta}.zip"
        fotos_pdf = {}
        with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for n, i in enumerate(items, 1):
                try:
                    foto = _abrir_foto(i.producto)
                except Exception as e:  # noqa: BLE001 — una foto rota no tumba el catálogo
                    logger.warning("Catálogo: no se pudo abrir la foto de %s: %s", i.producto.sku, e)
                    fallaron.append(i.producto.sku)
                    continue
                sub = _limpio(i.raiz, 60)
                datos = publicacion.datos(i.producto, precio=i.precio, oferta=i.oferta, fecha=fecha,
                                          con_precio=con_precio)
                for prefijo, imagen in (("Para_WhatsApp_y_Facebook", foto_limpia(foto)),
                                        ("Para_estados_y_publicaciones", publicacion.feed(datos, foto)[0])):
                    b = io.BytesIO()
                    imagen.save(b, "JPEG", quality=88, optimize=True)
                    z.writestr(zipfile.ZipInfo(f"{carpeta}/{prefijo}/{sub}/{i.archivo}",
                                               date_time=timezone.localtime().timetuple()[:6]),
                               b.getvalue(), compress_type=zipfile.ZIP_STORED)
                chica = _encajar(foto_limpia(foto), 440, 440)
                destino = tmp / f"pdf_{n}.jpg"
                chica.save(destino, "JPEG", quality=78)
                fotos_pdf[id(i)] = destino
                if progreso and (n % 10 == 0 or n == total):
                    progreso(n, total)
            listos = [i for i in items if id(i) in fotos_pdf]
            # PDF completo: una sección por categoría raíz.
            por_raiz, por_grupo = {}, {}
            for i in listos:
                por_raiz.setdefault(i.raiz, []).append((i, fotos_pdf[id(i)]))
                for g in i.grupos:
                    por_grupo.setdefault(g, []).append((i, fotos_pdf[id(i)]))
            if listos:
                secciones = [(r, f"{len(l)} producto{'s' if len(l) != 1 else ''}", l) for r, l in por_raiz.items()]
                completo = tmp / "Catalogo_completo.pdf"
                pdf(completo, secciones, fecha=fecha, con_precio=con_precio)
                z.write(completo, f"{carpeta}/PDF/Catalogo_completo.pdf")
                for k, (g, l) in enumerate(por_grupo.items()):
                    if progreso:
                        progreso(total, total)      # señal de vida: los PDF tardan
                    ruta = tmp / f"grupo_{k}.pdf"
                    raiz, _, mascota = g.partition(" - ")
                    sub = f"Para {mascota.lower()}s · {len(l)} productos" if mascota else f"{len(l)} productos"
                    pdf(ruta, [(raiz, sub, l)], fecha=fecha, con_precio=con_precio)
                    z.write(ruta, f"{carpeta}/PDF/{_limpio(g, 80)}.pdf")
            z.writestr(f"{carpeta}/catalogo_facebook.csv", csv_facebook(listos))
            z.writestr(f"{carpeta}/lista_whatsapp.xlsx", xlsx_whatsapp(listos))
            z.writestr(f"{carpeta}/LEAME.txt", _leame(len(listos), sin_foto, fallaron, fecha).encode("utf-8-sig"))
        destino = f"catalogos_redes/{carpeta}_{timezone.localtime():%H%M%S}.zip"
        with open(ruta_zip, "rb") as fz:
            guardado = default_storage.save(destino, File(fz))
    return guardado, len(listos), sin_foto, fallaron


def _leame(n, sin_foto, fallaron, fecha):
    lineas = [
        f"Catálogo de AllPetcr.com — armado por el ERP el {fecha:%d/%m/%Y}.",
        f"Productos: {n}.",
        "",
        "PDF/  → el catálogo completo y uno por categoría (más liviano para mandar por WhatsApp).",
        "Para_WhatsApp_y_Facebook/  → fotos limpias 1080×1080 para el catálogo de WhatsApp Business y Facebook.",
        "Para_estados_y_publicaciones/  → 1080×1350, la misma para Instagram, Facebook y estados de WhatsApp.",
        "   (Los alimentos con ficha técnica llevan ingredientes, nutrición y beneficios; lo demás, foto, peso y precio.)",
        "catalogo_facebook.csv  → se sube en Facebook (Administrador de ventas → Catálogo → Agregar artículos → Archivo).",
        "lista_whatsapp.xlsx  → nombre, precio, descripción y enlace de cada producto, para copiar en WhatsApp Business.",
        "",
        "Los precios son los del sistema ese día. Si cambian, se vuelve a generar desde el ERP.",
    ]
    if sin_foto:
        lineas.append(f"Quedaron fuera {sin_foto} producto(s) sin foto.")
    if fallaron:
        lineas.append(f"No se pudo abrir la foto de: {', '.join(fallaron)}.")
    return "\r\n".join(lineas) + "\r\n"
