"""Sube las fotos OFICIALES de alimentos y las asocia en el servidor (27/09/2026).

QUÉ HACE, EN ORDEN
    1. Lista las fotos de IMAGENES\\alimentos-oficiales-subir (una por SKU,
       ya revisadas y aprobadas por Oscar en revision.html).
    2. Pide la contraseña de la base del servidor (la misma de siempre).
    3. Te pregunta si seguís.
    4. Si escribís SI, corre `cargar_fotos_por_sku --reemplazar` contra el
       servidor: cada foto sube al bucket y el producto queda apuntando a ella.
       Solo cambia la foto: no toca precios, existencias, nombres ni SKU.

Las fotos van en WebP a propósito: la foto vieja era .jpg o .png, así que la
nueva queda en OTRA dirección. Con la misma dirección, el sitio y Cloudflare
seguirían mostrando la foto vieja hasta 30 días (caché de imágenes).

Se ejecuta con CARGAR_FOTOS_ALIMENTOS.bat (doble clic).
"""
import os
import subprocess
import sys
from pathlib import Path

from _cargar_fotos_editadas_en_servidor import (
    ACCESS_KEY_ID, BASE_DATOS, BUCKET, HOST, PUERTO, REGION, SECRET_ACCESS_KEY, USUARIO, fallar, pedir_contrasena,
)

CARPETA = Path(__file__).resolve().parents[2] / "IMAGENES" / "alimentos-oficiales-subir"


def main():
    print()
    print("=" * 66)
    print("  FOTOS OFICIALES DE ALIMENTOS")
    print("=" * 66)
    print()
    if not ACCESS_KEY_ID or not SECRET_ACCESS_KEY:
        fallar("Falta el archivo _llaves_spaces.py con las llaves del bucket.\n  Avisale a Claude.")
    if not CARPETA.is_dir():
        fallar(f"No encontré la carpeta: {CARPETA}")
    fotos = sorted(CARPETA.glob("*.webp"))
    if not fotos:
        fallar(f"No hay fotos .webp en {CARPETA}")
    print(f"  Carpeta: {CARPETA}")
    print(f"  Fotos a subir: {len(fotos)} (reemplazan la foto actual de cada producto)")
    print()
    for i in range(0, len(fotos), 6):
        print("   " + "  ".join(f.stem.ljust(10) for f in fotos[i:i + 6]))
    print()

    clave = pedir_contrasena()
    if input(f"\n  ¿Subo estas {len(fotos)} fotos al servidor? (escribí SI y Enter): ").strip().upper() != "SI":
        fallar("Cancelado por vos. No se subió nada.")

    entorno = os.environ.copy()
    entorno.update({
        "POSTGRES_HOST": HOST, "POSTGRES_PORT": PUERTO, "POSTGRES_DB": BASE_DATOS,
        "POSTGRES_USER": USUARIO, "POSTGRES_PASSWORD": clave, "PGSSLMODE": "require",
        "DJANGO_SECRET_KEY": "solo-para-esta-carga", "PYTHONIOENCODING": "utf-8",
        "MEDIA_STORAGE_BACKEND": "s3", "AWS_STORAGE_BUCKET_NAME": BUCKET, "AWS_S3_REGION_NAME": REGION,
        "AWS_S3_ENDPOINT_URL": f"https://{REGION}.digitaloceanspaces.com",
        "AWS_S3_CUSTOM_DOMAIN": f"{BUCKET}.{REGION}.digitaloceanspaces.com",
        "AWS_ACCESS_KEY_ID": ACCESS_KEY_ID, "AWS_SECRET_ACCESS_KEY": SECRET_ACCESS_KEY,
    })
    print()
    print("-" * 66)
    print("  Subiendo y asociando (puede tardar varios minutos)...")
    print("-" * 66)
    proceso = subprocess.run([sys.executable, "manage.py", "cargar_fotos_por_sku", str(CARPETA), "--reemplazar"], env=entorno)
    if proceso.returncode != 0:
        fallar("Algo falló. El mensaje de arriba dice qué.")
    print()
    print("=" * 66)
    print("  LISTO")
    print("=" * 66)
    print()
    print("  Las fotos nuevas ya están en el ERP; el sitio las muestra en la")
    print("  próxima visita (lee el catálogo en vivo).")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
