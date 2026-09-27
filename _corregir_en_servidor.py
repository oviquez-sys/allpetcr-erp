"""Aplica en el servidor las correcciones de catalogo/correcciones/*.csv (27/09/2026).

QUÉ HACE, EN ORDEN
    1. Pide la contraseña de la base del servidor (la misma de siempre).
    2. Corre `manage.py corregir_productos --dry-run` CONTRA EL SERVIDOR con cada
       archivo de correcciones: muestra cada cambio con su motivo. No escribe nada.
    3. Te pregunta si seguís.
    4. Si escribís SI, lo aplica. Solo nombre o mascota: nunca precios,
       existencias, SKU ni códigos de barras.

Se ejecuta con CORREGIR_PRODUCTOS.bat (doble clic). Repetirlo no hace daño:
lo que ya está corregido se informa como "ya estaba bien".
"""
import glob
import os
import subprocess
import sys

from _cargar_compra_en_servidor import BASE_DATOS, HOST, PUERTO, USUARIO, fallar, pedir_contrasena

LISTAS = sorted(glob.glob(os.path.join("catalogo", "correcciones", "*.csv")))


def correr(argumentos, env, titulo):
    print()
    print("-" * 66)
    print(f"  {titulo}")
    print("-" * 66)
    for lista in LISTAS:
        print(f"  Archivo: {lista}")
        proceso = subprocess.run([sys.executable, "manage.py", "corregir_productos", lista] + argumentos, env=env)
        if proceso.returncode != 0:
            return False
    return True


def main():
    print()
    print("=" * 66)
    print("  CORRECCIONES DE PRODUCTO")
    print("=" * 66)
    print()
    print("  Esto corrige en la base del servidor datos de producto que no")
    print("  coinciden con el empaque (nombre o mascota). Primero te muestra")
    print("  cada cambio con su motivo, sin escribir.")
    print()
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
        "PYTHONIOENCODING": "utf-8",
    })

    if not correr(["--dry-run"], entorno, "PASO 1 de 2 — Viendo qué haría (no escribe nada)"):
        fallar("La simulación se detuvo. El mensaje de arriba dice por qué.")

    if input("\n  ¿Lo aplico de verdad en el servidor? (escribí SI y Enter): ").strip().upper() != "SI":
        fallar("Cancelado por vos. No se escribió nada.")

    if not correr([], entorno, "PASO 2 de 2 — Aplicando en el servidor"):
        fallar("Se detuvo antes de terminar. Como va en una sola transacción,\n"
               "  no quedó nada a medias.")

    print()
    print("=" * 66)
    print("  LISTO")
    print("=" * 66)
    print()
    print("  Las correcciones ya están en el ERP y el sitio web las muestra")
    print("  en la próxima visita (lee el catálogo en vivo).")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
