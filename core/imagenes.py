"""Punto único para leer y escribir fotos de producto.

Por qué existe: `Producto.imagen` guarda solo la ruta relativa (texto), y el
archivo puede vivir en disco local o en un bucket S3-compatible según
`MEDIA_STORAGE_BACKEND` (ver config/settings.py). Si cada comando o vista
escribe con `Path(settings.MEDIA_ROOT) / ...` directo, ese código deja de
funcionar el día que se apunte a S3 — así que todo pasa por acá, que usa
`default_storage` y por lo tanto respeta el interruptor sin que el resto del
código sepa ni le importe dónde está el archivo de verdad.
"""
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

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
    return default_storage.save(ruta, ContentFile(contenido))


def url_imagen_producto(ruta: str) -> str:
    """URL pública para mostrar una foto ya guardada, o "" si no hay ruta."""
    if not ruta:
        return ""
    return default_storage.url(ruta)
