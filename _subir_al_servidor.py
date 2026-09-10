"""Sube el inventario de esta computadora a la base de datos del servidor.

QUÉ HACE, EN ORDEN:
  1. Saca un respaldo FRESCO de la base local (solo datos, sin fotos).
  2. Te pide la cadena de conexión del servidor y la usa SOLO en memoria.
  3. Restaura ese respaldo en la base del servidor.
  4. Cuenta los productos que quedaron allá, para que veas que llegó.

LO QUE NO HACE:
  - No modifica la base local. El paso 1 solo lee.
  - No guarda la contraseña en ningún archivo. Se pide cada vez.

Se ejecuta con SUBIR_INVENTARIO_AL_SERVIDOR.bat (doble clic).
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path(__file__).resolve().parent
TRASLADO = BASE / "_respaldo_traslado"


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


def correr(pasos, env=None, titulo=""):
    if titulo:
        print()
        print("-" * 66)
        print(f"  {titulo}")
        print("-" * 66)
    proceso = subprocess.run([sys.executable] + pasos, env=env)
    return proceso.returncode == 0


def leer_portapapeles():
    """Devuelve el texto del portapapeles de Windows, o cadena vacía.

    Usa PowerShell porque viene con Windows y no obliga a instalar nada.
    """
    try:
        proceso = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return ""
    if proceso.returncode != 0:
        return ""
    return (proceso.stdout or "").strip()


def enmascarar(url):
    """Muestra la cadena sin revelar la contraseña."""
    if "@" not in url or "://" not in url:
        return url[:60]
    esquema, resto = url.split("://", 1)
    credencial, servidor = resto.split("@", 1)
    usuario = credencial.split(":")[0]
    return f"{esquema}://{usuario}:********@{servidor}"


def main():
    print()
    print("=" * 66)
    print("  SUBIR EL INVENTARIO AL SERVIDOR")
    print("=" * 66)
    print()
    print("  Esto copia lo que hay en la base de ESTA computadora hacia la")
    print("  base del servidor en DigitalOcean.")
    print()
    print("  La base local NO se toca: solo se lee.")
    print()

    # --- 1. Datos del servidor -------------------------------------------
    #
    # Solo se pide la CONTRASEÑA. El resto (servidor, puerto, base, usuario)
    # no es secreto y va aquí fijo.
    #
    # Antes se pedía la cadena de conexión completa y falló: al copiarla de la
    # pantalla de DigitalOcean se copió el texto recortado con "..." en vez de
    # la contraseña. Una contraseña con puntos suspensivos entra sin quejarse
    # y el error aparece recién al final. Por eso ahora se pide sola y se
    # revisa antes de intentar nada.
    HOST = "allpetcr-db-do-user-41044000-0.l.db.ondigitalocean.com"
    PUERTO = "25060"
    BASE_DATOS = "defaultdb"
    USUARIO = "doadmin"

    print(f"  Servidor : {HOST}")
    print(f"  Base     : {BASE_DATOS}    Usuario: {USUARIO}")
    print()
    print("  Falta la contraseña. En DigitalOcean, en el panel de la base:")
    print("    Connection details > 'Connection parameters' > password > show")
    print("  Copiá SOLO la contraseña (empieza con AVNS_).")
    print()

    clave = leer_portapapeles()
    if clave and clave.startswith("postgresql://"):
        # Pegaron la cadena entera: se extrae la contraseña.
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

    # --- Revisiones que atrapan el error antes de intentar conectar -------
    if not clave:
        fallar("No hay contraseña.")
    if "..." in clave or "…" in clave:
        fallar("La contraseña trae puntos suspensivos.\n"
               "  Eso significa que copiaste el texto RECORTADO de la pantalla,\n"
               "  no la contraseña completa. Hacé clic en 'show' al lado de\n"
               "  password y copiá lo que aparece.")
    if len(clave) < 15:
        fallar(f"La contraseña tiene solo {len(clave)} caracteres y las de\n"
               "  DigitalOcean son más largas. Parece cortada.")
    if any(c.isspace() for c in clave):
        fallar("La contraseña trae espacios o saltos de línea. Copiala de nuevo.")

    entorno_servidor = os.environ.copy()
    entorno_servidor.update({
        "POSTGRES_HOST": HOST,
        "POSTGRES_PORT": PUERTO,
        "POSTGRES_DB": BASE_DATOS,
        "POSTGRES_USER": USUARIO,
        "POSTGRES_PASSWORD": clave,
        "PGSSLMODE": "require",
        "DJANGO_PRODUCTION": "",
        "DJANGO_SECRET_KEY": "solo-para-este-traslado",
    })

    print()
    print(f"  Destino: {HOST}, base '{BASE_DATOS}'")
    print()
    if input("  ¿Sigo? (escribí SI y Enter): ").strip().upper() != "SI":
        fallar("Cancelado por vos. No se tocó nada.")

    # --- 2. Respaldo fresco de la base LOCAL ------------------------------
    TRASLADO.mkdir(exist_ok=True)
    if not correr(
        ["manage.py", "respaldar", "--sin-fotos", "--destino", str(TRASLADO), "--conservar", "3"],
        titulo="PASO 1 de 3 — Respaldo de la base de esta computadora",
    ):
        fallar("No se pudo sacar el respaldo local. El mensaje de arriba dice por qué.")

    respaldos = sorted(TRASLADO.glob("respaldo_allpetcr_*.zip"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    if not respaldos:
        fallar(f"El respaldo no apareció en {TRASLADO}.")
    reciente = respaldos[0]
    print(f"\n  Respaldo listo: {reciente.name} ({reciente.stat().st_size // 1024} KB)")

    # --- 3. Restaurar ese respaldo EN EL SERVIDOR -------------------------
    if not correr(
        ["manage.py", "restaurar", "--archivo", str(reciente),
         "--destino", str(TRASLADO), "--confirmar"],
        env=entorno_servidor,
        titulo="PASO 2 de 3 — Subiendo al servidor",
    ):
        fallar("La subida falló. El mensaje de arriba dice por qué.\n"
               "  Causa más común: el servidor no acepta conexiones desde esta\n"
               "  computadora todavía (falta agregarla como origen de confianza).")

    # --- 4. Verificar ------------------------------------------------------
    print()
    print("-" * 66)
    print("  PASO 3 de 3 — Verificando que llegó")
    print("-" * 66)
    codigo = (
        "from catalogo.models import Producto;"
        "from django.contrib.auth import get_user_model;"
        "print('  PRODUCTOS EN EL SERVIDOR :', Producto.objects.count());"
        "print('  USUARIOS EN EL SERVIDOR  :', get_user_model().objects.count())"
    )
    subprocess.run([sys.executable, "manage.py", "shell", "-c", codigo],
                   env=entorno_servidor)

    print()
    print("=" * 66)
    print("  LISTO")
    print("=" * 66)
    print()
    print("  Si los números de arriba coinciden con lo que tenés en la tienda,")
    print("  el inventario ya está en el servidor.")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
