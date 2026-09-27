"""Carga en el servidor las fichas de alimento (26/09/2026).

QUÉ HACE, EN ORDEN
    1. Pide la contraseña de la base del servidor (la misma de siempre).
    2. Corre `manage.py cargar_fichas_alimento --dry-run` CONTRA EL SERVIDOR:
       muestra cuántas fichas crea o actualiza y qué alimentos quedan sin
       ficha. No escribe nada.
    3. Te pregunta si seguís.
    4. Si escribís SI, lo aplica. Crea o actualiza las fichas (información
       oficial de cada fórmula) y vincula cada presentación a la suya. No toca
       precios, existencias, SKU, códigos de barras, nombres ni fotos.

Se ejecuta con CARGAR_FICHAS_ALIMENTO.bat (doble clic). Se puede repetir
cada vez que se agregan o corrigen fichas: actualiza, no duplica.
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
    proceso = subprocess.run([sys.executable, "manage.py", "cargar_fichas_alimento"] + argumentos, env=env)
    return proceso.returncode == 0


def main():
    print()
    print("=" * 66)
    print("  FICHAS DE ALIMENTO")
    print("=" * 66)
    print()
    print("  Esto carga en la base del servidor la información oficial de los")
    print("  alimentos (beneficios, ingredientes, análisis, guía). No toca precios")
    print("  ni existencias. Primero te muestra todo, sin escribir.")
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
    print("  Las fichas ya están en el ERP y el sitio web las muestra en la")
    print("  próxima visita a cada alimento (lee el catálogo en vivo).")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
