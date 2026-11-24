"""Catálogo de WhatsApp por Meta (24/11/2026).

Arma el CSV que Meta (Administrador de ventas) descarga cada día del enlace de
`CatalogoMeta`, y que WhatsApp Business muestra como «catálogo conectado».
Es la forma de tener todos los productos en WhatsApp: a mano serían unas 30
horas y cada cambio de precio habría que corregirlo uno por uno.

Qué entra
---------
Lo mismo que el «Catálogo para redes» (`redes.productos`): lo publicado en la
web, con precio y con foto. Los agotados también, como «out of stock»: si se
sacaran del archivo, Meta los borraría y, al volver a haber, los revisaría de
nuevo como productos nuevos.

Quedan fuera los de salud (antiparasitarios, medicamentos): la política de
comercio de WhatsApp no permite medicamentos y restringe los productos de
salud. NexGard, además, no está publicado en la web.

La descripción
--------------
La de la ficha (la misma de la web) y debajo el cierre de la muestra que
aprobó Oscar el 24/11/2026:
- la línea de entrega, que se cambia en la pantalla;
- el envío gratis y los números del sorteo, que salen de la campaña vigente
  con sus montos, zonas y fechas (campanas/reglas.py) y desaparecen solos
  cuando la campaña deja de darlos;
- hasta cuándo vale la oferta, si el producto está en promoción;
- «Precio con IVA» y cómo pedir.
Si un dato no está en el sistema, no se escribe.
"""
import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .redes import _crc, _enlace, productos

MARCA_ENLACE = "o=whatsapp-catalogo"  # el código de origen, como los del plan de Navidad
RAICES_FUERA = {"Salud y cuidado"}
CATEGORIAS_FUERA = {"Dietas veterinarias"}
# Por nombre, para lo de salud que esté en otra categoría (un champú
# antipulgas en Higiene). «pulgas?\b» para no sacar una cama de 30 pulgadas.
PATRON_FUERA = re.compile(
    r"pulgas?\b|garrapat|parasit|nexgard|bravecto|simparica|frontline|ivermect|medicament|antibi[oó]tic|vacuna",
    re.IGNORECASE,
)
ESPECIES = ("perro", "gato", "dog", "cat", "puppy", "cachorro", "kitten", "gatito", "canino", "felino")
COLUMNAS = ["id", "title", "description", "availability", "condition", "price", "sale_price",
            "sale_price_effective_date", "link", "image_link", "brand", "product_type", "custom_label_0"]
CIERRE_FINAL = "Precio con IVA. Agregalo al carrito y mandanos el pedido."
PALABRA = {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"}


def fuera_por_salud(producto) -> bool:
    c = producto.categoria
    raiz = c.padre if c is not None and c.padre_id else c
    if raiz is not None and raiz.nombre in RAICES_FUERA:
        return True
    if c is not None and c.nombre in CATEGORIAS_FUERA:
        return True
    return bool(PATRON_FUERA.search(producto.nombre or ""))


def seleccion(empresa):
    """(items, cuántos quedaron fuera por salud, cuántos por no tener foto)."""
    items, sin_foto = productos(empresa, solo_existencia=False)
    dentro, fuera = [], 0
    for i in items:
        if fuera_por_salud(i.producto):
            fuera += 1
        else:
            dentro.append(i)
    return dentro, fuera, sin_foto


# ---------------------------------------------------------------------------
# El cierre de la descripción
# ---------------------------------------------------------------------------
@dataclass
class Cierre:
    entrega: str = ""
    envio_bajo: str = ""
    envio_alto: str = ""
    sorteo_bajo: str = ""
    sorteo_alto: str = ""
    umbral: Decimal | None = None


def _lista(nombres):
    if len(nombres) <= 1:
        return "".join(nombres)
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


def _zonas(campana) -> str:
    """«Heredia / Mercedes» → «Mercedes»; un cantón solo queda como está."""
    nombres = []
    for zona in campana.lista_zonas:
        nombre = zona.split("/")[-1].strip()
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    return _lista(nombres)


def _numeros(n) -> str:
    return "un número" if n == 1 else f"{PALABRA.get(n, n)} números"


def cierre(empresa, linea_entrega="", momento=None) -> Cierre:
    from campanas.reglas import vigente

    momento = momento or timezone.now()
    c = Cierre(entrega=(linea_entrega or "").strip())
    campana = vigente(empresa, momento)
    if campana is None:
        return c
    c.umbral = campana.umbral_bono
    umbral = _crc(campana.umbral_bono)
    if campana.da_envio_gratis(momento):
        zonas = _zonas(campana)
        donde = f" en {zonas}" if zonas else ""
        hasta = f"{timezone.localtime(campana.envio_hasta):%d/%m}"
        c.envio_bajo = f"🎁 Pedido de más de {umbral}: envío gratis{donde} (hasta el {hasta})."
        c.envio_alto = f"🎁 Este producto pasa de {umbral}: envío gratis{donde} (hasta el {hasta})."
    if campana.acepta(momento):
        n, bono = campana.numeros_compra, campana.numeros_bono
        desde = f" de {_crc(campana.compra_minima)} o más" if campana.compra_minima > 0 else ""
        base = f"🎄 Si estás inscrito en el sorteo del {timezone.localtime(campana.sorteo_en):%d/%m}, "
        plazo = f" (compras hasta el {timezone.localtime(campana.cierre):%d/%m})."
        if n and bono:
            c.sorteo_bajo = base + f"cada compra{desde} te da {_numeros(n)}, y {PALABRA.get(n + bono, n + bono)} si pasa de {umbral}" + plazo
            c.sorteo_alto = base + f"esta compra te da {_numeros(n + bono)}" + plazo
        elif n:
            c.sorteo_bajo = c.sorteo_alto = base + f"cada compra{desde} te da {_numeros(n)}" + plazo
        elif bono:
            c.sorteo_bajo = base + f"cada compra de más de {umbral} te da {_numeros(bono)}" + plazo
            c.sorteo_alto = base + f"esta compra te da {_numeros(bono)}" + plazo
    return c


def titulo(producto) -> str:
    """El nombre de la web, con la especie si el nombre no la dice: en un chat
    el producto llega suelto, sin la categoría alrededor."""
    nombre = (producto.nombre or "").strip()
    mascota = (producto.mascota or "").strip()
    if mascota and mascota.lower() != "otros" and not any(e in nombre.lower() for e in ESPECIES):
        nombre = f"{nombre} · {mascota}"
    return nombre[:150]


def descripcion(item, c: Cierre) -> str:
    p = item.producto
    texto = (p.descripcion or "").strip() or p.nombre
    alto = c.umbral is not None and Decimal(item.precio) > c.umbral
    lineas = [c.entrega, c.envio_alto if alto else c.envio_bajo, c.sorteo_alto if alto else c.sorteo_bajo]
    if item.oferta:
        lineas.append(f"🏷️ Precio de oferta hasta el {item.oferta['hasta']:%d/%m} o hasta agotar existencias.")
    lineas.append(CIERRE_FINAL)
    return texto[:4000] + "\n\n" + "\n".join(linea for linea in lineas if linea)


def _tipo(item) -> str:
    c = item.producto.categoria
    return item.raiz if c is None or not c.padre_id else f"{item.raiz} > {c.nombre}"


def csv_meta(empresa, linea_entrega="", momento=None) -> bytes:
    """El archivo que lee Meta. Sin BOM: lo lee una máquina, no Excel."""
    from core.imagenes import url_imagen_producto

    momento = momento or timezone.now()
    items, _, _ = seleccion(empresa)
    c = cierre(empresa, linea_entrega, momento)
    sitio = settings.SITIO_WEB_URL.rstrip("/")
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow(COLUMNAS)
    for i in items:
        p = i.producto
        precio_normal = i.oferta["precio_antes"] if i.oferta else p.precio_venta
        imagen = url_imagen_producto(p.imagen)
        if imagen.startswith("/"):
            imagen = sitio + imagen
        vigencia = ""
        if i.oferta:
            promo = i.oferta["item"].promocion
            vigencia = f"{promo.inicio:%Y-%m-%d}T00:00-06:00/{promo.fin:%Y-%m-%d}T23:59-06:00"
        w.writerow([
            p.sku, titulo(p), descripcion(i, c),
            "in stock" if p.stock_actual > 0 else "out of stock", "new",
            f"{Decimal(precio_normal):.2f} CRC",
            f"{Decimal(i.oferta['precio']):.2f} CRC" if i.oferta else "",
            vigencia, f"{_enlace(p)}?{MARCA_ENLACE}", imagen, p.marca or "AllPetcr.com", _tipo(i), p.mascota or "",
        ])
    return salida.getvalue().encode("utf-8")
