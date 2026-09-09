"""Muestra el estado REAL del arbol de categorias en la base del ERP.

Solo lee. Sirve para confirmar que no quedaron categorias repetidas ni
productos huerfanos despues de correr `asegurar_categorias`.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from catalogo.models import Categoria, Producto  # noqa: E402

print("TODAS LAS CATEGORIAS DE LA BASE")
print("=" * 78)
print(f"{'orden':>6}  {'productos':>9}  {'padre':<20}  nombre (entre comillas)")
print("-" * 78)
for c in Categoria.objects.select_related("padre").order_by("orden", "nombre"):
    padre = c.padre.nombre if c.padre else "(raiz)"
    # repr expone espacios de sobra o mayusculas raras que a simple vista no
    # se ven y que hacen que dos categorias "iguales" no lo sean.
    print(f"{c.orden:>6}  {c.productos.count():>9}  {padre:<20}  {c.nombre!r}")

print()
print(f"Total de categorias: {Categoria.objects.count()}")
print(f"Total de productos:  {Producto.objects.count()}")

sin_cat = Producto.objects.filter(categoria__isnull=True).count()
print(f"Productos sin categoria: {sin_cat}")

print()
print("NOMBRES PARECIDOS (posibles duplicados por tilde, mayuscula o espacio)")
print("-" * 78)
vistos = {}
for c in Categoria.objects.all():
    clave = c.nombre.strip().lower()
    vistos.setdefault(clave, []).append(c)
hubo = False
for clave, lista in sorted(vistos.items()):
    if len(lista) > 1:
        hubo = True
        print(f"  '{clave}':")
        for c in lista:
            print(f"     id={c.id}  {c.nombre!r}  ({c.productos.count()} productos)")
if not hubo:
    print("  Ninguno. No hay categorias repetidas.")
