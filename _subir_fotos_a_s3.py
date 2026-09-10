"""Sube al bucket de fotos (DigitalOcean Spaces) SOLO las fotos de los
productos que siguen en el catálogo.

POR QUÉ HACE FALTA: el servidor donde vive el ERP se reconstruye desde cero
en cada despliegue (Docker) — cualquier foto guardada solo en su disco se
pierde en el próximo cambio que se suba. Un bucket S3-compatible (Spaces)
es un disco aparte que sobrevive a los despliegues; por eso el ERP, cuando
tiene MEDIA_STORAGE_BACKEND=s3, guarda y lee las fotos ahí en vez de en su
propio disco (ver config/settings.py).

POR QUÉ NO SUBE TODA LA CARPETA (10/09/2026): el 09/09/2026 se borraron 348
productos de catálogo de proveedor que nunca se compraron, pero sus fotos
siguen en media/productos/. Subirlas sería publicar en internet fotos de
mercadería que no se vende. Por eso la lista de qué subir sale de la BASE DE
DATOS (el campo `imagen` de cada producto vivo), no de listar la carpeta.

QUÉ HACE, EN ORDEN:
  1. Le pregunta a la base local qué foto usa cada producto del catálogo.
  2. Por cada una, si el bucket ya la tiene, la salta (correrlo dos veces
     no duplica nada).
  3. Si no la tiene, la sube.

LO QUE NO HACE:
  - No borra ni modifica nada localmente.
  - No borra nada del bucket.
  - No sube las fotos huérfanas (las de productos que ya no existen).

Se ejecuta con SUBIR_FOTOS.bat (doble clic).
"""
import mimetypes
import os
import sys
from pathlib import Path

import django

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from catalogo.models import Producto  # noqa: E402

# --- Datos del bucket -------------------------------------------------------
#
# El bucket "allpetcr-fotos" ya existe (se creó junto con el resto de la
# infraestructura el 09/09/2026). Estos valores no son secretos.
BUCKET = "allpetcr-fotos"
REGION = "nyc3"
ENDPOINT = f"https://{REGION}.digitaloceanspaces.com"
DOMINIO_PUBLICO = f"{BUCKET}.{REGION}.digitaloceanspaces.com"

# Las llaves NO van acá: este archivo sí se sube a GitHub y el repositorio
# es público. Viven en _llaves_spaces.py, que está en .gitignore.
try:
    from _llaves_spaces import ACCESS_KEY_ID, SECRET_ACCESS_KEY
except ImportError:  # pragma: no cover - solo pasa si falta el archivo
    ACCESS_KEY_ID = SECRET_ACCESS_KEY = ""


def fallar(mensaje):
    print()
    print("=" * 66)
    print("  SE DETUVO")
    print("=" * 66)
    print()
    print(f"  {mensaje}")
    print()
    input("  Presioná Enter para cerrar.")
    sys.exit(1)


def main():
    print()
    print("=" * 66)
    print("  SUBIR FOTOS DE PRODUCTO AL BUCKET (Spaces)")
    print("=" * 66)
    print()

    if not ACCESS_KEY_ID or not SECRET_ACCESS_KEY:
        fallar("Falta el archivo _llaves_spaces.py con las llaves del bucket.\n"
               "  Avisale a Claude y te lo vuelve a dejar.")

    carpeta_media = BASE / "media"
    if not (carpeta_media / "productos").is_dir():
        fallar(f"No encontré la carpeta de fotos: {carpeta_media / 'productos'}")

    # --- Qué fotos importan: las del catálogo vivo, no las de la carpeta ---
    total_productos = Producto.objects.count()
    rutas = sorted({r for r in Producto.objects.exclude(imagen="")
                    .values_list("imagen", flat=True) if r})

    existentes = [r for r in rutas if (carpeta_media / r).is_file()]
    faltantes = [r for r in rutas if not (carpeta_media / r).is_file()]

    # Fotos en la carpeta que ya no usa ningún producto (las de los 348
    # borrados). Se cuentan solo para informar: no se tocan.
    en_carpeta = {f"productos/{p.name}"
                  for p in (carpeta_media / "productos").iterdir() if p.is_file()}
    huerfanas = en_carpeta - set(rutas)

    print(f"  Productos en el catálogo : {total_productos}")
    print(f"  Con foto asignada        : {len(rutas)}")
    print(f"  Fotos listas para subir  : {len(existentes)}")
    if faltantes:
        print(f"  Con foto que NO está en el disco: {len(faltantes)}")
    print(f"  Fotos huérfanas que NO se suben : {len(huerfanas)}")
    print(f"  (son de productos que ya no existen; quedan intactas en tu disco)")
    print()
    print(f"  Bucket destino: {BUCKET} ({REGION})")
    print()

    if not existentes:
        fallar("No hay nada que subir.")

    if input("  ¿Sigo? (escribí SI y Enter): ").strip().upper() != "SI":
        fallar("Cancelado por vos. No se subió nada.")

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        fallar("Falta el paquete 'boto3'. Instalalo con:\n"
               "  .\\.venv\\Scripts\\python.exe -m pip install boto3")

    cliente = boto3.client(
        "s3",
        region_name=REGION,
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY_ID,
        aws_secret_access_key=SECRET_ACCESS_KEY,
        config=Config(s3={"addressing_style": "virtual"}),
    )

    print()
    print("-" * 66)
    print("  Subiendo...")
    print("-" * 66)

    subidas = 0
    saltadas = 0
    fallidas = 0
    for i, ruta in enumerate(existentes, start=1):
        archivo = carpeta_media / ruta
        clave = ruta.replace("\\", "/")
        try:
            cliente.head_object(Bucket=BUCKET, Key=clave)
            saltadas += 1
            continue
        except Exception:
            pass  # no existe todavía en el bucket: se sube

        # El Content-Type se deduce de la extensión: si se sube todo como
        # image/jpeg, el navegador se traga un .png mal etiquetado pero
        # next/image (que sí lo respeta) lo rechaza.
        tipo, _ = mimetypes.guess_type(archivo.name)
        try:
            cliente.upload_file(
                str(archivo), BUCKET, clave,
                ExtraArgs={"ACL": "public-read",
                           "ContentType": tipo or "application/octet-stream"},
            )
            subidas += 1
        except Exception as e:
            fallidas += 1
            print(f"  ERROR con {ruta}: {e}")

        if i % 50 == 0 or i == len(existentes):
            print(f"  ...{i}/{len(existentes)} revisadas "
                  f"(subidas: {subidas}, ya estaban: {saltadas}, fallidas: {fallidas})")

    print()
    print("=" * 66)
    print("  LISTO")
    print("=" * 66)
    print()
    print(f"  Subidas nuevas : {subidas}")
    print(f"  Ya estaban     : {saltadas}")
    print(f"  Fallidas       : {fallidas}")
    print()
    if fallidas:
        print("  Si algo falló, correlo de nuevo: lo que ya subió no se repite.")
        print()
    if existentes:
        print("  Ejemplo de foto ya publicada:")
        print(f"    https://{DOMINIO_PUBLICO}/{existentes[0]}")
        print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
