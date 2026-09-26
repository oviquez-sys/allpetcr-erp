"""Carga la compra de Belina (alimento) directo en el servidor, con sus fotos.

QUÉ HACE, EN ORDEN
    1. Pregunta el número de factura de Belina y si se pagó de contado.
    2. Pide la contraseña de la base (la misma de siempre, del portapapeles).
    3. Corre `manage.py cargar_compra_belina --dry-run` CONTRA EL SERVIDOR:
       muestra cuántos productos, unidades, regalos y el TOTAL de la factura,
       sin guardar nada. Comparalo con el papel de Belina.
    4. Si escribís SI, lo aplica: crea los productos, sube las fotos al
       bucket y mete la mercadería como compra recibida (kardex, costo,
       asiento). Los de regalo entran a costo cero.

Se ejecuta con CARGAR_BELINA.bat (doble clic).
"""
import os
import subprocess
import sys

from _cargar_compra_en_servidor import BASE_DATOS, HOST, PUERTO, USUARIO, fallar, pedir_contrasena

try:
    from _llaves_spaces import ACCESS_KEY_ID, SECRET_ACCESS_KEY
except ImportError:  # pragma: no cover
    ACCESS_KEY_ID = SECRET_ACCESS_KEY = ""

BUCKET, REGION = "allpetcr-fotos", "nyc3"
EXCEL = r"C:\Users\Usuario\Desktop\INVENTARIO 15-09-26\Belina precios allpet.xlsx"
FOTOS = r"C:\Users\Usuario\Desktop\INVENTARIO 15-09-26\Belina_Imagenes_Inventario"


def correr(argumentos, env, titulo):
    print()
    print("-" * 66)
    print(f"  {titulo}")
    print("-" * 66)
    proceso = subprocess.run([sys.executable, "manage.py", "cargar_compra_belina"] + argumentos, env=env)
    return proceso.returncode == 0


def main():
    print()
    print("=" * 66)
    print("  COMPRA DE BELINA (ALIMENTO) — PRODUCTOS, FOTOS Y EXISTENCIAS")
    print("=" * 66)
    print()
    if not ACCESS_KEY_ID or not SECRET_ACCESS_KEY:
        fallar("Falta el archivo _llaves_spaces.py (llaves de las fotos). Avisale a Claude.")
    if not os.path.isfile(EXCEL):
        fallar(f"No encontré el Excel:\n  {EXCEL}")
    print("  Antes de seguir: GUARDÁ y CERRÁ el Excel de Belina.")
    print()
    factura = input("  Número de factura de Belina: ").strip()
    if not factura:
        fallar("Sin número de factura no se carga: es lo que evita cargarla dos veces.")
    credito = input("  ¿Se la debés todavía a Belina? (no / si): ").strip().upper()
    forma_pago = "CRE" if credito in ("SI", "S") else "CON"
    print()

    clave = pedir_contrasena()
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
    argumentos = ["--excel", EXCEL, "--fotos", FOTOS, "--factura", factura, "--forma-pago", forma_pago]

    if not correr(argumentos + ["--dry-run"], entorno, "PASO 1 de 2 — Viendo qué haría (no guarda nada)"):
        fallar("La simulación se detuvo. El mensaje de arriba dice por qué.")
    if input("\n  ¿El TOTAL coincide con la factura? ¿Lo cargo de verdad? (escribí SI): ").strip().upper() != "SI":
        fallar("Cancelado. No se guardó nada.")
    if not correr(argumentos, entorno, "PASO 2 de 2 — Cargando (las fotos tardan unos minutos)"):
        fallar("Se detuvo antes de terminar. Va en una sola transacción: no quedó nada a medias.")

    print()
    print("=" * 66)
    print("  LISTO. Los productos ya están en el ERP con foto, precio y existencias.")
    print("  Para etiquetarlos: Admin › Códigos de barras, buscá por marca (NutriSource, PureVita, Balance).")
    print("=" * 66)
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
