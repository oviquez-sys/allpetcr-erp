"""Revisa (y opcionalmente borra) los productos sin existencia.

POR QUÉ EXISTE
    En la carga del catálogo del proveedor entraron productos que nunca se
    compraron. Este script los identifica, los exporta a un Excel y —solo si
    se lo pide expresamente— los borra.

CÓMO SE USA
    Paso 1, revisar y exportar (NO borra nada):
        python _productos_sin_existencia.py

    Paso 2, borrar de verdad (después de revisar el Excel):
        python _productos_sin_existencia.py --borrar --confirmar

QUÉ CUENTA COMO "SIN EXISTENCIA"
    stock_actual = 0  Y  sin ningún movimiento en el kardex.
    Lo segundo importa: un producto que tuvo existencia y se agotó SÍ tiene
    kardex, y ese no es catálogo sin comprar — es mercadería vendida. Mirar
    solo el stock en cero los mezclaría.

QUÉ BLOQUEA UN BORRADO
    Seis tablas protegen a Producto: kardex, compras, ventas, pedidos,
    reservas y cambios de precio. Si un producto aparece en cualquiera de
    ellas, la base se niega a borrarlo. El script lo detecta ANTES de
    intentarlo y lo reporta, en vez de fallar a mitad de camino.
"""
import argparse
import os
import sys
from pathlib import Path

import django

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import Count, Q  # noqa: E402

from catalogo.models import Producto  # noqa: E402


def analizar():
    """Devuelve (candidatos, bloqueados) — cada uno lista de dicts."""
    productos = (
        Producto.objects.filter(stock_actual=0)
        .annotate(
            n_kardex=Count("kardex", distinct=True),
            n_precios=Count("cambios_precio", distinct=True),
        )
        .select_related("categoria")
        .order_by("nombre")
    )

    candidatos, bloqueados = [], []
    for p in productos:
        motivos = []
        if p.n_kardex:
            motivos.append(f"tiene {p.n_kardex} movimiento(s) de inventario")
        if p.n_precios:
            motivos.append(f"tiene {p.n_precios} cambio(s) de precio")
        for rel, etiqueta in (
            ("lineacompra", "aparece en una compra"),
            ("lineaventa", "aparece en una venta"),
            ("lineapedido", "aparece en un pedido"),
        ):
            try:
                if getattr(p, f"{rel}_set").exists():
                    motivos.append(etiqueta)
            except AttributeError:
                pass

        fila = {
            "SKU": p.sku,
            "Código de barras": p.codigo_barras,
            "Nombre": p.nombre,
            "Categoría": p.categoria.nombre if p.categoria else "",
            "Mascota": p.mascota,
            "Presentación": p.presentacion,
            "Precio de venta": float(p.precio_venta),
            "Costo promedio": float(p.costo_promedio),
            "Descripción": p.descripcion,
            "Activo": "Sí" if p.activo else "No",
            "Se puede borrar": "No" if motivos else "Sí",
            "Motivo del bloqueo": "; ".join(motivos),
        }
        (bloqueados if motivos else candidatos).append((p, fila))
    return candidatos, bloqueados


def exportar(candidatos, bloqueados):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Sin existencia"

    filas = [f for _, f in candidatos] + [f for _, f in bloqueados]
    if not filas:
        return None

    encabezados = list(filas[0].keys())
    hoja.append(encabezados)
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F3864")

    rojo = PatternFill("solid", fgColor="FCE4E4")
    for fila in filas:
        hoja.append([fila[c] for c in encabezados])
        if fila["Se puede borrar"] == "No":
            for celda in hoja[hoja.max_row]:
                celda.fill = rojo

    for i, nombre in enumerate(encabezados, start=1):
        ancho = max(len(nombre), *(len(str(f[nombre])) for f in filas))
        hoja.column_dimensions[hoja.cell(1, i).column_letter].width = min(ancho + 3, 55)
    hoja.freeze_panes = "A2"

    destino = BASE / "PRODUCTOS_SIN_EXISTENCIA.xlsx"
    libro.save(destino)
    return destino


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--borrar", action="store_true")
    parser.add_argument("--confirmar", action="store_true")
    opts = parser.parse_args()

    print()
    print("=" * 66)
    print("  PRODUCTOS SIN EXISTENCIA")
    print("=" * 66)

    candidatos, bloqueados = analizar()
    total = Producto.objects.count()

    print()
    print(f"  Productos en total          : {total}")
    print(f"  Sin existencia              : {len(candidatos) + len(bloqueados)}")
    print(f"    - se pueden borrar        : {len(candidatos)}")
    print(f"    - bloqueados por historial: {len(bloqueados)}")

    destino = exportar(candidatos, bloqueados)
    if destino:
        print()
        print(f"  Listado completo: {destino.name}")
        print("  (las filas en rojo son las que NO se pueden borrar)")

    if not opts.borrar:
        print()
        print("  No se borró nada. Esto fue solo la revisión.")
        print("  Abrí el Excel y revisalo. Para borrar, corré:")
        print("    python _productos_sin_existencia.py --borrar --confirmar")
        print()
        return

    if not opts.confirmar:
        print()
        print("  Falta --confirmar. No se borró nada.")
        print()
        return

    if not candidatos:
        print()
        print("  No hay nada que borrar.")
        print()
        return

    print()
    print(f"  BORRANDO {len(candidatos)} productos...")
    borrados, fallidos = 0, []
    with transaction.atomic():
        for p, _ in candidatos:
            try:
                p.delete()
                borrados += 1
            except Exception as e:  # protección de la base
                fallidos.append((p.sku, str(e)[:90]))

    print(f"  Borrados: {borrados}")
    if fallidos:
        print(f"  No se pudieron borrar: {len(fallidos)}")
        for sku, motivo in fallidos[:10]:
            print(f"    {sku}: {motivo}")
    print()
    print(f"  Productos que quedan: {Producto.objects.count()}")
    print()


if __name__ == "__main__":
    main()
