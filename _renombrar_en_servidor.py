"""Renombra en el servidor los productos con nombres genéricos (26/09/2026).

QUÉ HACE, EN ORDEN
    1. Pide la contraseña de la base del servidor (la misma de siempre).
    2. Corre `manage.py renombrar_productos --dry-run` CONTRA EL SERVIDOR:
       muestra cada nombre viejo → nombre nuevo. No escribe nada.
    3. Te pregunta si seguís.
    4. Si escribís SI, lo aplica. Solo cambia el nombre: no toca precios,
       existencias, fotos, códigos de barras ni nada más.

Se ejecuta con RENOMBRAR_PRODUCTOS.bat (doble clic).
"""
import os
import subprocess
import sys

from _cargar_compra_en_servidor import BASE_DATOS, HOST, PUERTO, USUARIO, fallar, pedir_contrasena

LISTA = os.path.join("catalogo", "renombres", "2026-09-26.csv")


def correr(argumentos, env, titulo):
    print()
    print("-" * 66)
    print(f"  {titulo}")
    print("-" * 66)
    proceso = subprocess.run([sys.executable, "manage.py", "renombrar_productos", LISTA] + argumentos, env=env)
    return proceso.returncode == 0


def main():
    print()
    print("=" * 66)
    print("  NOMBRES DE PRODUCTO")
    print("=" * 66)
    print()
    print("  Esto cambia en la base del servidor los nombres genéricos")
    print("  (\"Arnes\", \"Juguete\", \"Collar\"...) por nombres que distinguen")
    print("  cada producto. Solo el nombre. Primero te muestra todo, sin escribir.")
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
    print("  Los nombres nuevos ya están en el ERP y el sitio web los muestra")
    print("  en la próxima visita (lee el catálogo en vivo).")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
