"""Sube las fotos editadas de "imagenes editadas" y las asocia en el servidor.

QUÉ HACE
    Corre `manage.py cargar_fotos_por_sku <carpeta> --reemplazar` pero
    apuntando DIRECTO al servidor: la base de datos en DigitalOcean Y el
    bucket de fotos (Spaces), en la misma pasada. Cada foto se sube al
    bucket y el producto con ese SKU queda apuntando a ella — viejo o nuevo.

    --reemplazar porque estas son fotos EDITADAS de mercadería que ya tenía
    foto: sin esa bandera, `cargar_fotos_por_sku` las salta para no pisar una
    foto ya curada. Acá sí queremos pisarla.

DE DÓNDE SALEN LAS FOTOS
    De la carpeta conectada "imagenes editadas". El nombre del archivo tiene
    que ser el código (SKU) exacto, ej. "75564.png" -> producto 75564. Lo que
    no calza con ningún SKU se lista al final para revisar a mano, en vez de
    adivinar.

Se ejecuta con CARGAR_FOTOS_EDITADAS.bat (doble clic).
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path(__file__).resolve().parent

# Mismo servidor que _cargar_compra_en_servidor.py y _subir_al_servidor.py.
HOST = "allpetcr-db-do-user-41044000-0.l.db.ondigitalocean.com"
PUERTO = "25060"
BASE_DATOS = "defaultdb"
USUARIO = "doadmin"

# Mismo bucket que usa SUBIR_FOTOS.bat / TRAER_RESPALDOS_NUBE.bat.
BUCKET = "allpetcr-fotos"
REGION = "nyc3"

# La carpeta con las fotos editadas. Si el día de mañana está en otro lado,
# se le pasa como argumento: CARGAR_FOTOS_EDITADAS.bat "OTRA\RUTA".
CARPETA_POR_DEFECTO = r"C:\Users\Usuario\Desktop\INVENTARIO 15-09-26\imagenes editadas"

try:
    from _llaves_spaces import ACCESS_KEY_ID, SECRET_ACCESS_KEY
except ImportError:  # pragma: no cover - solo si falta el archivo de llaves
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


def leer_portapapeles():
    """Lee el portapapeles de Windows. Nunca revienta ni ensucia la pantalla.

    Los dos detalles, aprendidos a los golpes el 18/09/2026:

    - `encoding`/`errors` explícitos. Sin ellos Python decodifica con la
      página de códigos vieja de Windows (cp1252) y cualquier cosa que haya
      quedado copiada —el log de la corrida anterior, algo de otra app— tira
      un UnicodeDecodeError dentro del hilo lector de subprocess. El programa
      sigue vivo, pero escupe un traspié de veinte líneas justo antes de
      pedir la contraseña, y eso parece un error grave cuando no lo es.
    - Si lo copiado no se PARECE a una contraseña, no se ofrece. Preguntar
      "¿uso esa?" mostrando 877 caracteres de otra cosa no ayuda: confunde y
      hace dudar de si el programa entendió algo.
    """
    try:
        proceso = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
    except Exception:
        return ""
    if proceso.returncode != 0:
        return ""
    texto = (proceso.stdout or "").strip()
    # Las de DigitalOcean rondan los 25 caracteres y no llevan espacios.
    if not texto or len(texto) > 120 or any(c.isspace() for c in texto):
        return ""
    return texto


def pedir_contrasena():
    print(f"  Servidor : {HOST}")
    print(f"  Base     : {BASE_DATOS}    Usuario: {USUARIO}")
    print()
    print("  Falta la contraseña. En DigitalOcean, en el panel de la base:")
    print("    Connection details > 'Connection parameters' > password > show")
    print("  Copiá SOLO la contraseña (empieza con AVNS_).")
    print()

    clave = leer_portapapeles()
    if clave and clave.startswith("postgresql://"):
        try:
            clave = unquote(urlparse(clave).password or "")
        except Exception:
            clave = ""

    if clave:
        print(f"  En el portapapeles hay: {clave[:5]}{'*' * max(0, len(clave) - 5)}"
              f"  ({len(clave)} caracteres)")
        if input("  ¿Uso esa? (SI / no): ").strip().upper() not in ("", "SI", "S"):
            clave = ""

    if not clave:
        clave = input("  Contraseña: ").strip()

    if not clave:
        fallar("No hay contraseña.")
    if "..." in clave or "…" in clave:
        fallar("La contraseña trae puntos suspensivos. Copiá la completa con 'show'.")
    if len(clave) < 15:
        fallar(f"La contraseña tiene solo {len(clave)} caracteres. Parece cortada.")
    if any(c.isspace() for c in clave):
        fallar("La contraseña trae espacios o saltos de línea. Copiala de nuevo.")
    return clave


def main():
    print()
    print("=" * 66)
    print("  SUBIR LAS FOTOS EDITADAS Y ASOCIARLAS EN EL SERVIDOR")
    print("=" * 66)
    print()

    if not ACCESS_KEY_ID or not SECRET_ACCESS_KEY:
        fallar("Falta el archivo _llaves_spaces.py con las llaves del bucket.\n"
               "  Avisale a Claude y te lo vuelve a dejar.")

    carpeta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(CARPETA_POR_DEFECTO)
    if not carpeta.is_dir():
        fallar(f"No encontré la carpeta: {carpeta}")
    print(f"  Carpeta de fotos: {carpeta}")

    clave = pedir_contrasena()
    entorno = os.environ.copy()
    entorno.update({
        "POSTGRES_HOST": HOST,
        "POSTGRES_PORT": PUERTO,
        "POSTGRES_DB": BASE_DATOS,
        "POSTGRES_USER": USUARIO,
        "POSTGRES_PASSWORD": clave,
        "PGSSLMODE": "require",
        "DJANGO_SECRET_KEY": "solo-para-esta-carga",
        "MEDIA_STORAGE_BACKEND": "s3",
        "AWS_STORAGE_BUCKET_NAME": BUCKET,
        "AWS_S3_REGION_NAME": REGION,
        "AWS_S3_ENDPOINT_URL": f"https://{REGION}.digitaloceanspaces.com",
        "AWS_S3_CUSTOM_DOMAIN": f"{BUCKET}.{REGION}.digitaloceanspaces.com",
        "AWS_ACCESS_KEY_ID": ACCESS_KEY_ID,
        "AWS_SECRET_ACCESS_KEY": SECRET_ACCESS_KEY,
    })

    print()
    print("-" * 66)
    print("  Subiendo y asociando (puede tardar varios minutos)...")
    print("-" * 66)
    proceso = subprocess.run(
        [sys.executable, "manage.py", "cargar_fotos_por_sku", str(carpeta), "--reemplazar"],
        env=entorno,
    )
    if proceso.returncode != 0:
        fallar("Algo falló. El mensaje de arriba dice qué.")

    print()
    print("=" * 66)
    print("  LISTO")
    print("=" * 66)
    print()
    print("  Avisale a Claude para publicar el catálogo en el sitio.")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
