"""Punto único para leer y escribir fotos de producto.

Por qué existe: `Producto.imagen` guarda solo la ruta relativa (texto), y el
archivo puede vivir en disco local o en un bucket S3-compatible según
`MEDIA_STORAGE_BACKEND` (ver config/settings.py). Si cada comando o vista
escribe con `Path(settings.MEDIA_ROOT) / ...` directo, ese código deja de
funcionar el día que se apunte a S3 — así que todo pasa por acá, que usa
`default_storage` y por lo tanto respeta el interruptor sin que el resto del
código sepa ni le importe dónde está el archivo de verdad.
"""
import io
import logging
import posixpath

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

CARPETA_PRODUCTOS = "productos"


def guardar_imagen_producto(nombre_archivo: str, contenido: bytes) -> str:
    """Guarda los bytes de una foto y devuelve la ruta relativa a guardar en
    `Producto.imagen` (ej. "productos/75564.png").

    Si ya existe un archivo con ese nombre, se sobrescribe: es el
    comportamiento esperado al reemplazar la foto de un producto (los
    comandos de importación son idempotentes a propósito).
    """
    ruta = f"{CARPETA_PRODUCTOS}/{nombre_archivo}"
    if default_storage.exists(ruta):
        default_storage.delete(ruta)
    guardada = default_storage.save(ruta, ContentFile(contenido))
    generar_miniatura(guardada, forzar=True)
    return guardada


def url_imagen_producto(ruta: str) -> str:
    """URL pública para mostrar una foto ya guardada, o "" si no hay ruta."""
    if not ruta:
        return ""
    return default_storage.url(ruta)


# --------------------------------------------------------------------------
# Miniaturas (20/09/2026)
# --------------------------------------------------------------------------
# POR QUÉ: las fotos originales miden ~1024 px y pesan 100–400 KB. El POS,
# "Recibir mercadería" y "Etiquetas" muestran cientos de tarjetas: pedir la
# foto grande para un cuadrito de 60 px eran decenas de megas por pantalla
# (medido el 20/09: ~0,9 s por foto desde el bucket). La miniatura pesa
# ~10 KB y vive al lado del original, con nombre deducible de él, así que
# armar su URL no cuesta ninguna consulta ni viaje al bucket.
#
# Si una miniatura todavía no existe (foto vieja, o subida por un camino que
# no la genera), el navegador falla al cargarla y el script static/js/fotos.js
# pide `/foto/<id>/`, que la genera en ese momento y redirige a ella: el
# sistema se repara solo, sin que nadie corra nada. `generar_miniaturas`
# (lo corre entrypoint.sh en cada despliegue) las deja listas de antemano.
LADO_MINIATURA = 240  # px del lado mayor: nítida hasta ~120 px en pantallas 2x
CARPETA_MINIATURAS = f"{CARPETA_PRODUCTOS}/min"


def ruta_miniatura(ruta: str) -> str:
    """"productos/75564.jpeg" -> "productos/min/75564.webp" ("" si no hay foto)."""
    if not ruta:
        return ""
    base = posixpath.splitext(posixpath.basename(ruta))[0]
    return f"{CARPETA_MINIATURAS}/{base}.webp"


def url_miniatura(ruta: str, version=None) -> str:
    """URL de la miniatura, SIN verificar que exista (a propósito: ver arriba).

    `version` (ej. producto.actualizado_en) va como ?v= para que, al cambiar
    la foto, el navegador no siga mostrando la miniatura vieja de su caché."""
    mini = ruta_miniatura(ruta)
    if not mini:
        return ""
    url = default_storage.url(mini)
    if version is not None:
        marca = int(version.timestamp()) if hasattr(version, "timestamp") else version
        url += ("&" if "?" in url else "?") + f"v={marca}"
    return url


def generar_miniatura(ruta: str, *, forzar=False) -> str:
    """Crea la miniatura de una foto ya guardada. Devuelve su ruta, o "" si
    el original no existe o no se puede leer (nunca lanza: una foto rota no
    debe tumbar una pantalla ni una compra)."""
    from PIL import Image, ImageOps

    mini = ruta_miniatura(ruta)
    if not mini:
        return ""
    try:
        if not forzar and default_storage.exists(mini):
            return mini
        if not default_storage.exists(ruta):
            return ""
        with default_storage.open(ruta, "rb") as f:
            img = Image.open(io.BytesIO(f.read()))
            img = ImageOps.exif_transpose(img)  # fotos de celular giradas
            img.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            salida = io.BytesIO()
            img.save(salida, "WEBP", quality=80, method=4)
        if default_storage.exists(mini):
            default_storage.delete(mini)
        return default_storage.save(mini, ContentFile(salida.getvalue()))
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo generar la miniatura de %s", ruta)
        return ""


def datos_foto(producto) -> dict:
    """Lo que necesita el navegador para mostrar la foto de un producto:
    miniatura (rápida), original (para ampliar) y el respaldo que la genera
    si falta. Mismo contrato para plantillas y para las pantallas en JS."""
    if not getattr(producto, "imagen", ""):
        return {"miniatura": "", "imagen": "", "respaldo": ""}
    return {
        "miniatura": url_miniatura(producto.imagen, getattr(producto, "actualizado_en", None)),
        "imagen": url_imagen_producto(producto.imagen),
        "respaldo": f"/foto/{producto.pk}/",
    }


def completar_foto(fila: dict) -> dict:
    """Para las consultas `.values()` que viajan como JSON al navegador:
    recibe la fila con `imagen` (ruta cruda), `id` y, si viene,
    `actualizado_en`, y la deja con imagen/miniatura/respaldo como URLs."""
    ruta = fila.get("imagen") or ""
    version = fila.pop("actualizado_en", None)
    fila["imagen"] = url_imagen_producto(ruta)
    fila["miniatura"] = url_miniatura(ruta, version) if ruta else ""
    fila["respaldo"] = f"/foto/{fila['id']}/" if ruta else ""
    return fila
