"""Revisa que el respaldo mas reciente sirva de verdad.

No alcanza con que exista un archivo. Un respaldo vale si se puede ABRIR y si
adentro esta lo que tiene que estar. Esto comprueba las dos cosas y compara el
contenido contra la base viva.

Solo lee. No modifica ni la base ni los respaldos.
"""
import os
import zipfile
from datetime import datetime, timezone

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from catalogo.models import Producto  # noqa: E402
from ventas.models import FacturaVenta  # noqa: E402

CARPETA = "respaldos"

print("=" * 74)
print("REVISION DEL RESPALDO MAS RECIENTE")
print("=" * 74)

if not os.path.isdir(CARPETA):
    print(f"No existe la carpeta '{CARPETA}'. No hay ningun respaldo.")
    raise SystemExit(1)

zips = [f for f in os.listdir(CARPETA) if f.lower().endswith(".zip")]
if not zips:
    print("NO HAY NI UN RESPALDO .zip. El negocio no tiene copia de seguridad.")
    raise SystemExit(1)

zips.sort(key=lambda f: os.path.getmtime(os.path.join(CARPETA, f)), reverse=True)
mas_nuevo = os.path.join(CARPETA, zips[0])
mtime = datetime.fromtimestamp(os.path.getmtime(mas_nuevo), tz=timezone.utc)
edad_dias = (datetime.now(timezone.utc) - mtime).days
peso = os.path.getsize(mas_nuevo)

print(f"\nArchivo : {zips[0]}")
print(f"Fecha   : {mtime.astimezone().strftime('%d/%m/%Y %H:%M')}")
print(f"Peso    : {peso:,} bytes")
print(f"Edad    : {edad_dias} dia(s)")

if edad_dias > 7:
    print("\n  *** ATENCION: el respaldo tiene mas de una semana. ***")
    print("  Todo lo que pasó desde esa fecha NO esta respaldado.")

# ── que se pueda abrir ─────────────────────────────────────────────────────
print("\n1. ¿Se puede abrir el archivo?")
try:
    with zipfile.ZipFile(mas_nuevo) as z:
        danado = z.testzip()
        if danado:
            print(f"   NO. El archivo esta danado (falla en {danado}).")
            print("   ESTE RESPALDO NO SIRVE.")
            raise SystemExit(1)
        entradas = z.infolist()
    print(f"   Si. Se abre bien y trae {len(entradas)} archivos adentro.")
except zipfile.BadZipFile:
    print("   NO. No es un zip valido. ESTE RESPALDO NO SIRVE.")
    raise SystemExit(1)

# ── que traiga la base de datos ────────────────────────────────────────────
print("\n2. ¿Trae la base de datos?")
bases = [e for e in entradas if e.filename.lower().endswith((".sql", ".dump", ".json", ".sqlite3"))]
if not bases:
    print("   NO. No hay ningun archivo de base de datos adentro.")
    print("   Sin esto no se pueden recuperar ventas, inventario ni contabilidad.")
else:
    for e in bases:
        print(f"   Si: {e.filename}  ({e.file_size:,} bytes sin comprimir)")
        if e.file_size < 50_000:
            print("      *** Sospechosamente chico. Puede estar vacio. ***")

# ── que traiga las fotos ───────────────────────────────────────────────────
print("\n3. ¿Trae las fotos de los productos?")
fotos = [e for e in entradas if e.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
con_foto_en_base = Producto.objects.exclude(imagen="").count()
print(f"   Fotos dentro del respaldo : {len(fotos)}")
print(f"   Productos con foto ahora  : {con_foto_en_base}")
if len(fotos) < con_foto_en_base:
    faltan = con_foto_en_base - len(fotos)
    print(f"   *** Faltan {faltan} fotos en el respaldo. ***")
    print("   Son fotos cargadas despues de esa copia. Si se pierde el disco,")
    print("   esas no vuelven.")
elif fotos:
    print("   Estan todas.")

# ── que hay hoy en la base, para dimensionar lo que se perderia ───────────
print("\n4. ¿Que hay hoy en la base viva?")
print(f"   Productos          : {Producto.objects.count()}")
print(f"   Facturas de venta  : {FacturaVenta.objects.count()}")

print("\n" + "=" * 74)
if edad_dias > 7:
    print("CONCLUSION: hay un respaldo y se puede abrir, pero esta viejo.")
    print("Hay que hacer uno nuevo HOY y sacarlo de esta computadora.")
else:
    print("CONCLUSION: el respaldo esta al dia y se puede abrir.")
print("=" * 74)
print()
print("OJO CON ALGO IMPORTANTE:")
print("  Este respaldo esta en el MISMO disco que la base de datos.")
print("  Si la computadora no prende manana, se pierden los dos juntos.")
print("  Un respaldo solo protege de verdad cuando esta en otro lado.")
