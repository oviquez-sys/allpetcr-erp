"""Genera el PDF de un recibo real y lo deja en la carpeta para poder verlo.

No manda ningun correo: solo dibuja el recibo y guarda el archivo. Sirve para
revisar el diseno antes de mandarselo a un cliente.

Se corre desde PROBAR_PDF.bat. Va como archivo .py y no como `python -c`
dentro del .bat porque el HTML de prueba lleva `<` y `>`, que en la consola de
Windows son operadores de redireccion y rompen el comando (paso el 02/09/2026).
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.template.loader import render_to_string  # noqa: E402

from core.pdf import html_a_pdf, logo_data_uri  # noqa: E402
from ventas.models import FacturaVenta  # noqa: E402

SALIDA = "Recibo-prueba.pdf"
HTML_SALIDA = "Recibo-prueba.html"

# Se borra el PDF viejo ANTES de empezar (02/09/2026). Sin esto, si el script
# falla a mitad de camino el .bat abre el archivo de la corrida anterior y uno
# cree estar viendo el resultado nuevo. Paso, y costo media hora de diagnostico
# sobre un archivo que no era el que se estaba mirando.
for viejo in (SALIDA, HTML_SALIDA):
    if os.path.exists(viejo):
        os.remove(viejo)
        print(f"  (borrado el {viejo} de la corrida anterior)")

print("Buscando el ultimo recibo emitido...")
factura = (
    FacturaVenta.objects
    .select_related("empresa", "sucursal", "cliente")
    .prefetch_related("lineas__producto")
    .order_by("-id")
    .first()
)
if factura is None:
    print("No hay ninguna venta registrada todavia. Hace una venta de prueba")
    print("en el POS y volve a correr esto.")
    raise SystemExit(1)

print(f"  Usando {factura.numero} — total CRC {factura.total:,.0f}")

logo = logo_data_uri()
print(f"  Logo embebido: {'SI, ' + str(len(logo)) + ' caracteres' if logo else 'NO SE ENCONTRO'}")

print("Armando el HTML del recibo...")
html = render_to_string(
    "ventas/factura.html",
    {"f": factura, "es_email": True, "logo_src": logo},
)

# El HTML tambien se guarda: si el PDF sale raro, esto dice si el problema
# esta en la plantilla (antes de Chromium) o en el dibujado (despues).
with open(HTML_SALIDA, "w", encoding="utf-8") as fh:
    fh.write(html)

crudos = [t for t in ("{% if", "{% for", "{{ f.", "{% comment") if t in html]
if crudos:
    print()
    print("  PROBLEMA: la plantilla NO se proceso. Quedaron etiquetas crudas:")
    for t in crudos:
        print(f"    {t}")
    print("  Eso significa que Django devolvio el archivo tal cual en vez de")
    print("  rellenarlo. El PDF va a salir mostrando codigo.")
else:
    print("  Plantilla procesada correctamente (no quedan etiquetas crudas).")

print("Dibujando el recibo con Chromium...")
pdf = html_a_pdf(html)

if not pdf:
    print()
    print("NO SE PUDO GENERAR EL PDF.")
    print("Revisa el registro de arriba: si dice que Playwright no esta")
    print("instalado, corre INSTALAR_PDF.bat. Si dice otra cosa, mostrasela")
    print("a Claude.")
    raise SystemExit(1)

with open(SALIDA, "wb") as f:
    f.write(pdf)

print()
print(f"LISTO. PDF generado: {len(pdf):,} bytes")
print(f"  Archivo: {os.path.abspath(SALIDA)}")
print()
print("Abrilo y revisa dos cosas:")
print("  1. Que se vea el logo arriba a la izquierda.")
print("  2. Que las columnas no se monten unas sobre otras.")
