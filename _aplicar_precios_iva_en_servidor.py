"""Aplica los precios nuevos con IVA y pasa la empresa a régimen tradicional,
directo en el servidor (20/09/2026). Lo aprobó Oscar: versión "Medio".

QUÉ HACE, EN ORDEN
    1. Pide la contraseña de la base del servidor (la misma de siempre).
    2. Corre `manage.py aplicar_precios_iva --dry-run` CONTRA EL SERVIDOR y
       muestra qué cambiaría. No escribe nada.
    3. Te pregunta si seguís.
    4. Si escribís SI, aplica: precios nuevos y régimen tradicional, las dos
       cosas juntas o ninguna.

Los precios salen de data\\PRECIOS_NUEVOS_IVA.xlsx (el Excel aprobado). Esa
carpeta NO se sube a GitHub, y el Excel trae costos.

Se ejecuta con APLICAR_PRECIOS_IVA.bat (doble clic).
"""
import os
import subprocess
import sys
from pathlib import Path

from _cargar_compra_en_servidor import BASE_DATOS, HOST, PUERTO, USUARIO, fallar, pedir_contrasena

BASE = Path(__file__).resolve().parent
EXCEL = BASE / "data" / "PRECIOS_NUEVOS_IVA.xlsx"


def correr(argumentos, env, titulo):
    print()
    print("-" * 66)
    print(f"  {titulo}")
    print("-" * 66)
    proceso = subprocess.run(
        [sys.executable, "manage.py", "aplicar_precios_iva", "--excel", str(EXCEL)] + argumentos, env=env
    )
    return proceso.returncode == 0


def main():
    print()
    print("=" * 66)
    print("  PRECIOS NUEVOS CON IVA + RÉGIMEN TRADICIONAL")
    print("=" * 66)
    print()
    print("  Esto escribe DIRECTO en la base del servidor en DigitalOcean:")
    print("  - pone los precios nuevos (ya con el IVA incluido),")
    print("  - y cambia la empresa a régimen tradicional.")
    print()
    print("  Primero te muestra todo, sin tocar nada.")
    print()
    if not EXCEL.exists():
        fallar(f"No encuentro el Excel de precios:\n  {EXCEL}\n  Avisale a Claude.")

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
    })

    if not correr(["--dry-run"], entorno, "PASO 1 de 2 — Viendo qué haría (no escribe nada)"):
        fallar("La simulación se detuvo. El mensaje de arriba dice por qué.")

    if input("\n  ¿Aplico esto de verdad en el servidor? (escribí SI y Enter): ").strip().upper() != "SI":
        fallar("Cancelado por vos. No se escribió nada.")

    if not correr([], entorno, "PASO 2 de 2 — Aplicando en el servidor"):
        fallar("Se detuvo antes de terminar. Como todo va en una sola transacción,\n"
               "  no quedó nada a medias: ni precios ni régimen cambiaron.")

    print()
    print("=" * 66)
    print("  LISTO")
    print("=" * 66)
    print()
    print("  - La página web toma los precios nuevos sola.")
    print("  - Falta reimprimir las etiquetas del estante (llevan el precio viejo).")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
