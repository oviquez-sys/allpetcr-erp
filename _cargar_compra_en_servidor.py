"""Carga la compra de setiembre 2026 (factura 19/09) directo en el servidor.

QUÉ HACE, EN ORDEN
    1. Pregunta el número de factura y el proveedor (quedan en el documento
       de compra, que es lo que después cuadra contra el papel).
    2. Pide la contraseña de la base del servidor (igual que
       SUBIR_INVENTARIO_AL_SERVIDOR.bat: mismo servidor, mismo usuario).
    3. Corre `manage.py cargar_compra_19_09 --dry-run --con-existencias`
       CONTRA EL SERVIDOR y te muestra exactamente qué haría, sin escribir
       nada todavía — incluido el TOTAL de la compra, para que lo compares
       con la factura del proveedor antes de aplicar.
    4. Te pregunta si seguís.
    5. Si decís que sí, corre el mismo comando sin --dry-run: ahí sí escribe.

QUÉ ESCRIBE
    - Catálogo: productos nuevos, los que vuelven, nombres, categorías,
      descripciones y precios (con su historial de cambio de precio).
    - Existencias: la mercadería entra como una COMPRA recibida, con su
      movimiento de kardex, su costo promedio recalculado y su asiento
      contable. O sea lo mismo que Compras › Recibir mercadería, pero con
      las 300 líneas de una sola vez. Si algo sale mal, se reversa entera
      desde Compras (anular la compra), no a mano.

Se ejecuta con CARGAR_COMPRA_19_09.bat (doble clic).
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path(__file__).resolve().parent

# Mismos datos que usa _subir_al_servidor.py: un solo servidor de producción.
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
        fallar("La contraseña trae puntos suspensivos.\n"
               "  Copiaste el texto RECORTADO de la pantalla, no la contraseña\n"
               "  completa. Hacé clic en 'show' al lado de password y copiá eso.")
    if len(clave) < 15:
        fallar(f"La contraseña tiene solo {len(clave)} caracteres y las de\n"
               "  DigitalOcean son más largas. Parece cortada.")
    if any(c.isspace() for c in clave):
        fallar("La contraseña trae espacios o saltos de línea. Copiala de nuevo.")
    return clave


def correr(argumentos, env, titulo):
    print()
    print("-" * 66)
    print(f"  {titulo}")
    print("-" * 66)
    proceso = subprocess.run([sys.executable, "manage.py", "cargar_compra_19_09"] + argumentos, env=env)
    return proceso.returncode == 0


def pedir_datos_de_la_factura():
    """El número de factura y el proveedor quedan en el documento de compra.

    Se preguntan en vez de fijarlos en el código porque son lo que después
    permite cuadrar la contabilidad contra el papel del proveedor — y porque
    el número de factura es la llave que evita cargar dos veces la misma
    mercadería.
    """
    print("  Datos de la factura del proveedor (Enter deja lo que está entre paréntesis):")
    print()
    factura = input("  Numero de factura (19-09-2026): ").strip() or "19-09-2026"
    proveedor = input("  Proveedor (BUEN AMIGO): ").strip() or "BUEN AMIGO"
    credito = input("  ¿Se la debés todavía al proveedor? (no / si): ").strip().upper()
    forma_pago = "CRE" if credito in ("SI", "S") else "CON"
    print()
    print(f"  Factura {factura} — {proveedor} — "
          f"{'a crédito (queda como cuenta por pagar)' if forma_pago == 'CRE' else 'contado (sale de Bancos)'}")
    return factura, proveedor, forma_pago


def main():
    print()
    print("=" * 66)
    print("  CARGAR LA COMPRA DE SETIEMBRE 2026 (FACTURA 19/09)")
    print("=" * 66)
    print()
    print("  Esto escribe DIRECTO en la base del servidor en DigitalOcean:")
    print("  productos nuevos, los que vuelven, precios, y la mercadería")
    print("  entra al inventario como una compra recibida (con su costo y su")
    print("  asiento contable).")
    print()
    print("  MANDA LA CANTIDAD DEL EXCEL: si un producto ya traía existencia en")
    print("  el sistema, se pone en cero antes de recibir la factura, para que")
    print("  quede exactamente lo que dice la hoja. Se puede porque la tienda")
    print("  no ha abierto y no hay una sola venta; si hubiera, el comando se")
    print("  niega solo.")
    print()

    factura, proveedor, forma_pago = pedir_datos_de_la_factura()
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
    })

    # --igualar-al-excel: manda la cantidad de la hoja. Lo que el sistema
    # traía de estos productos venía de una carga anterior, no de una venta
    # (la tienda no ha abierto), así que se pone en cero con un ajuste y entra
    # la factura. El comando mismo se niega a hacerlo si encuentra una venta
    # registrada, y en ese caso hay que sacar la bandera de acá.
    # FV-00000036 (12/09/2026, ₡5.156, un arnés) es la prueba del punto de
    # venta que quedó sin anular cuando se montó el agente de impresión. Se
    # revisó una por una con VER_VENTAS.bat: las otras 35 ya están anuladas.
    # Va nombrada, no con un "forzar": si mañana aparece otra venta emitida
    # que nadie revisó, el comando se vuelve a plantar, que es lo que se
    # quiere. Sigue pendiente anularla desde el ERP para sacarla de los libros.
    opciones = ["--con-existencias", "--igualar-al-excel", "--factura", factura,
                "--proveedor", proveedor, "--forma-pago", forma_pago,
                "--ignorar-ventas", "FV-00000036"]

    if not correr(["--dry-run"] + opciones, entorno,
                  "PASO 1 de 2 — Viendo qué haría (no escribe nada)"):
        fallar("La simulación falló. El mensaje de arriba dice por qué.")

    print()
    print("-" * 66)
    print("  Arriba está TODO lo que va a pasar si seguís: qué se crea, qué")
    print("  precio cambia, cuántas unidades entran a bodega, y qué productos")
    print("  quedan sin categoría o sin mascota para revisar después.")
    print()
    print("  ANTES DE SEGUIR: mirá el 'Total de la compra' y comparalo con la")
    print("  factura del proveedor. Ese número queda en la contabilidad y en el")
    print("  costo de cada producto.")
    print("-" * 66)
    if input("\n  ¿Aplico esto de verdad en el servidor? (escribí SI y Enter): ").strip().upper() != "SI":
        fallar("Cancelado por vos. No se escribió nada.")

    if not correr(opciones, entorno, "PASO 2 de 2 — Aplicando en el servidor"):
        fallar("La carga falló a mitad de camino. Como todo va en una sola "
               "transacción, no quedó nada a medias — es seguro volver a intentar.")

    print()
    print("=" * 66)
    print("  LISTO")
    print("=" * 66)
    print()
    print("  Siguiente paso: CARGAR_FOTOS_EDITADAS.bat, y después avisale a")
    print("  Claude para publicar el catálogo en el sitio.")
    print()
    input("  Presioná Enter para cerrar.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fallar("Cancelado con Ctrl+C.")
