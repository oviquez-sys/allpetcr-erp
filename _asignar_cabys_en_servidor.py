"""Carga el código CABYS de cada producto directo en el servidor (21/09/2026).

QUÉ HACE, EN ORDEN
    1. Pide la contraseña de la base del servidor (la misma de siempre).
    2. Corre `manage.py asignar_cabys --dry-run` CONTRA EL SERVIDOR: muestra
       cuántos productos recibirían código. No escribe nada.
    3. Te pregunta si seguís.
    4. Si escribís SI, lo aplica. No cambia precios ni IVA: solo el código.

En los dos pasos deja el Excel data\\CABYS_PARA_EL_CONTADOR.xlsx, para
mandárselo al contador. Esa carpeta no se sube a GitHub.

Se ejecuta con ASIGNAR_CABYS.bat (doble clic).
"""
import os
import subprocess
import sys

from _cargar_compra_en_servidor import BASE_DATOS, HOST, PUERTO, USUARIO, fallar, pedir_contrasena


def correr(argumentos, env, titulo):
    print()
    print("-" * 66)
    print(f"  {titulo}")
    print("-" * 66)
    proceso = subprocess.run([sys.executable, "manage.py", "asignar_cabys"] + argumentos, env=env)
    return proceso.returncode == 0


def main():
    print()
    print("=" * 66)
    print("  CÓDIGOS CABYS DE LOS PRODUCTOS")
    print("=" * 66)
    print()
    print("  Esto escribe en la base del servidor el código CABYS de cada")
    print("  producto (el que pide Hacienda en la factura electrónica).")
    print("  No toca precios ni IVA. Primero te muestra todo, sin escribir.")
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
    print("  Mandale al contador el Excel data\\CABYS_PARA_EL_CONTADOR.xlsx")
    print("  (los de color rojo y amarillo son los que tiene que revisar).")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
