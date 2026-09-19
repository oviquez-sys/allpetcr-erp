"""Muestra las ventas que hay en la base del SERVIDOR. Solo lee, no escribe.

POR QUÉ EXISTE
    La carga de la compra se detuvo porque encontró ventas registradas, y la
    tienda todavía no ha abierto. Casi seguro son las pruebas de cuando se
    montó el punto de venta y las impresoras, pero "casi seguro" no alcanza
    para tocar el inventario: si alguna venta fuera de mercadería que de
    verdad salió del local, poner las existencias en cero dejaría el conteo
    inflado y nadie se daría cuenta hasta contar la bodega.

    Esto lista cada venta con su fecha, su monto y los productos que movió,
    para decidir con el dato a la vista.

NO ESCRIBE NADA. Ni una fila. Se puede correr las veces que haga falta.

Se ejecuta con VER_VENTAS.bat (doble clic).
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path(__file__).resolve().parent

HOST = "allpetcr-db-do-user-41044000-0.l.db.ondigitalocean.com"
PUERTO = "25060"
BASE_DATOS = "defaultdb"
USUARIO = "doadmin"


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
    print()
    print("  Contraseña de la base (la de DigitalOcean, empieza con AVNS_).")
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
    return clave


# El programa que corre del otro lado, ya con Django levantado contra el
# servidor. Va como texto para que todo quepa en un solo archivo y en un solo
# doble clic.
CONSULTA = r'''
from django.db.models import Sum

from caja.models import SesionCaja
from catalogo.models import Producto
from inventario.models import MovimientoInventario
from ventas.models import FacturaVenta

print()
print("=" * 70)
print("  VENTAS EN LA BASE DEL SERVIDOR")
print("=" * 70)

ventas = FacturaVenta.objects.select_related("usuario", "sesion_caja").order_by("creado_en")
print()
print(f"  Facturas de venta en total : {ventas.count()}")
print(f"    - emitidas (cuentan)     : {ventas.filter(estado='EMI').count()}")
print(f"    - anuladas (ya reversadas): {ventas.filter(estado='ANU').count()}")
total_emitidas = ventas.filter(estado="EMI").aggregate(t=Sum("total"))["t"] or 0
print(f"  Monto de las emitidas      : CRC {total_emitidas:,.2f}")

print()
print("-" * 70)
print("  UNA POR UNA")
print("-" * 70)
for v in ventas:
    quien = v.usuario.username if v.usuario else "(sin usuario)"
    print()
    print(f"  {v.numero}  {v.creado_en:%d/%m/%Y %H:%M}  {v.get_estado_display().upper()}")
    print(f"    Total CRC {v.total:,.2f} · {v.get_medio_pago_display()} · hecha por {quien}")
    for l in v.lineas.select_related("producto"):
        print(f"      {l.cantidad:g} x {l.producto.sku} — {l.producto.nombre}")

print()
print("-" * 70)
print("  QUÉ MERCADERÍA SALIÓ POR ESAS VENTAS (movimientos de kardex)")
print("-" * 70)
salidas = MovimientoInventario.objects.filter(tipo="VEN").select_related("producto")
if not salidas.exists():
    print()
    print("  Ninguna. No hay un solo movimiento de inventario por venta.")
else:
    print()
    for m in salidas.order_by("fecha"):
        print(f"  {m.fecha:%d/%m/%Y %H:%M}  {m.cantidad:g} x {m.producto.sku} — "
              f"{m.producto.nombre}  (ref {m.referencia})")

print()
print("-" * 70)
print("  CAJA")
print("-" * 70)
print()
for s in SesionCaja.objects.select_related("usuario").order_by("abierta_en"):
    quien = s.usuario.username if s.usuario else "(sin usuario)"
    print(f"  Sesión de {quien}: abierta {s.abierta_en:%d/%m/%Y %H:%M} · "
          f"{s.get_estado_display()}")

print()
print("-" * 70)
print("  INVENTARIO HOY")
print("-" * 70)
print()
print(f"  Productos en el catálogo      : {Producto.objects.count()}")
print(f"  Con existencia mayor que cero : {Producto.objects.filter(stock_actual__gt=0).count()}")
unidades = Producto.objects.aggregate(t=Sum("stock_actual"))["t"] or 0
print(f"  Unidades en bodega            : {unidades:g}")
print()
'''


def main():
    print()
    print("=" * 66)
    print("  VER LAS VENTAS DEL SERVIDOR (solo lectura)")
    print("=" * 66)
    print()
    print("  Esto NO escribe nada. Solo muestra qué ventas hay registradas,")
    print("  para saber si son las pruebas o si alguna es de verdad.")
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
        "DJANGO_SECRET_KEY": "solo-para-esta-consulta",
    })

    proceso = subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", CONSULTA], env=entorno
    )
    if proceso.returncode != 0:
        fallar("No se pudo consultar. El mensaje de arriba dice por qué.")

    print()
    print("=" * 66)
    print("  Copiale esta pantalla a Claude.")
    print("=" * 66)
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
