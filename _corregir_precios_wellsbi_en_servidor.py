"""Corrige en el servidor el precio de venta de 4 productos Wellsbi (19/10/2026).

QUÉ HACE, EN ORDEN
    1. Pide la contraseña de la base del servidor (la misma de siempre).
    2. Busca los 4 SKU y muestra, sin escribir nada: nombre, precio actual y
       precio nuevo. Si un SKU no existe, se detiene sin tocar nada.
    3. Te pregunta si seguís.
    4. Si escribís SI, cambia los precios por `catalogo.services.cambiar_precio`
       (queda en el historial de precios, con motivo) en UNA sola transacción,
       y vuelve a leerlos de la base para mostrarte cómo quedaron.

Solo precio de venta (con IVA incluido, como todo precio_venta). No toca
costos, existencias ni ningún otro producto.

Se ejecuta con CORREGIR_PRECIOS_WELLSBI.bat (doble clic). Repetirlo no hace
daño: lo que ya tiene el precio correcto se informa como "ya estaba bien".
"""
import os
import sys
from decimal import Decimal

from _cargar_compra_en_servidor import BASE_DATOS, HOST, PUERTO, USUARIO, fallar, pedir_contrasena

PRECIOS = {
    "WEL-178": Decimal("2840"),
    "WEL-154": Decimal("2840"),
    "WEL-192": Decimal("1840"),
    "WEL-185": Decimal("3550"),
}
MOTIVO = "Corrección de precio pedida por Oscar (19/10/2026)"


def colones(valor):
    return f"₡{valor:,.0f}".replace(",", ".")


def mostrar(productos, titulo):
    print()
    print("-" * 66)
    print(f"  {titulo}")
    print("-" * 66)
    for sku, nuevo in PRECIOS.items():
        p = productos[sku]
        estado = "ya estaba bien" if p.precio_venta == nuevo else f"{colones(p.precio_venta)} → {colones(nuevo)}"
        print(f"  {sku}  {p.nombre[:38]:<38}  {estado}")


def main():
    print()
    print("=" * 66)
    print("  CORREGIR PRECIOS WELLSBI (4 productos)")
    print("=" * 66)
    print()
    clave = pedir_contrasena()
    os.environ.update({
        "POSTGRES_HOST": HOST, "POSTGRES_PORT": PUERTO, "POSTGRES_DB": BASE_DATOS,
        "POSTGRES_USER": USUARIO, "POSTGRES_PASSWORD": clave, "PGSSLMODE": "require",
        "DJANGO_SECRET_KEY": "solo-para-esta-carga", "PYTHONIOENCODING": "utf-8",
        "DJANGO_SETTINGS_MODULE": "config.settings",
    })
    import django
    django.setup()
    from django.db import transaction
    from catalogo.models import Producto
    from catalogo.services import cambiar_precio

    def leer():
        encontrados = {p.sku: p for p in Producto.objects.filter(sku__in=PRECIOS)}
        faltan = [s for s in PRECIOS if s not in encontrados]
        if faltan:
            fallar(f"No encontré estos códigos en el servidor: {', '.join(faltan)}.\n"
                   "  No se cambió nada. Avisale a Claude.")
        return encontrados

    antes = leer()
    mostrar(antes, "PASO 1 de 2 — Así quedaría (todavía no se escribe nada)")

    pendientes = [s for s, n in PRECIOS.items() if antes[s].precio_venta != n]
    if not pendientes:
        print("\n  Los 4 ya tienen el precio correcto. No hay nada que hacer.")
        input("\n  Presioná Enter para cerrar.")
        return

    if input("\n  ¿Cambio estos precios de verdad en el servidor? (escribí SI y Enter): ").strip().upper() != "SI":
        fallar("Cancelado por vos. No se escribió nada.")

    with transaction.atomic():
        for sku in pendientes:
            cambiar_precio(producto=antes[sku], nuevo_precio=PRECIOS[sku], motivo=MOTIVO)

    despues = leer()
    mostrar(despues, "PASO 2 de 2 — Leído de nuevo de la base, después del cambio")
    mal = [s for s, n in PRECIOS.items() if despues[s].precio_venta != n]
    print()
    print("=" * 66)
    print("  ALGO NO CALZA: " + ", ".join(mal) if mal else "  LISTO. Los 4 precios quedaron bien y en el historial de precios.")
    print("=" * 66)
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
