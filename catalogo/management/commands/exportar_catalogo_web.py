"""Exporta el catálogo real al sitio web (allpetcr-web/data/).

Por qué existe
-------------
El sitio web necesita mostrar productos reales, pero el ERP todavía no expone
una API (no hay Django REST Framework instalado). Este comando es el puente
simple mientras tanto: lee la base real y escribe los dos JSON que el sitio
ya sabe leer, con exactamente la forma que espera `lib/types.ts`.

Cuando exista la API, este comando deja de ser necesario: el sitio hará fetch
en vivo. Hasta entonces, se corre a mano cada vez que cambien precios o
productos.

QUÉ NO SE EXPORTA (deliberado, no olvido)
-----------------------------------------
- `costo_promedio`, `margen_pct`, `markup_pct`: es lo que te cuesta y lo que
  ganás. Publicarlo en internet le entrega tu estructura de costos a la
  competencia. NUNCA debe salir.
- `stock_actual` exacto: se traduce a un booleano `disponible`. Publicar
  "quedan 3 unidades" le dice a cualquiera cuánto volumen manejás. El cliente
  solo necesita saber si hay o no hay.
- `imagen`: desactivado por ahora a pedido de Oscar (las fotos actuales se van
  a mejorar antes de publicarlas). Para activarlo, poner INCLUIR_IMAGENES=True.
- Productos inactivos: no se exportan.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalogo.models import Categoria, Producto
from core.models import Empresa

# Cambiar a True cuando las fotos de producto estén listas para publicarse.
INCLUIR_IMAGENES = False

# Ruta por defecto del proyecto web, relativa a la carpeta del ERP.
DESTINO_POR_DEFECTO = Path(__file__).resolve().parents[4] / "allpetcr-web" / "data"


class Command(BaseCommand):
    help = "Exporta el catálogo (productos y categorías) al sitio web en formato JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--destino", type=str, default=None,
            help="Carpeta data/ del sitio web. Por defecto: ../allpetcr-web/data",
        )
        parser.add_argument(
            "--incluir-sin-precio", action="store_true",
            help="Incluir productos con precio 0. Por defecto se omiten (no tiene "
                 "sentido publicar un producto sin precio).",
        )

    def handle(self, *args, **opciones):
        empresa = Empresa.objects.first()
        if empresa is None:
            raise CommandError("No hay ninguna empresa configurada en la base de datos.")

        destino = Path(opciones["destino"]) if opciones["destino"] else DESTINO_POR_DEFECTO
        if not destino.exists():
            raise CommandError(
                f"No existe la carpeta destino:\n  {destino}\n\n"
                "Verificá que el proyecto allpetcr-web esté junto a allpetcr-erp, "
                "o pasá la ruta con --destino."
            )

        productos = Producto.objects.filter(empresa=empresa, activo=True).select_related("categoria")
        if not opciones["incluir_sin_precio"]:
            productos = productos.exclude(precio_venta=0)
        productos = productos.order_by("nombre")

        datos_productos = []
        for p in productos:
            fila = {
                "sku": p.sku,
                "nombre": p.nombre,
                "categoria_id": p.categoria_id,
                "presentacion": p.presentacion or "",
                "precio_venta": float(p.precio_venta),
                # Booleano, NO la cantidad exacta: el cliente necesita saber si
                # hay, no cuánto inventario manejás.
                "disponible": p.stock_actual > 0,
            }
            if INCLUIR_IMAGENES:
                fila["imagen"] = p.imagen or ""
            else:
                fila["imagen"] = ""
            datos_productos.append(fila)

        # Solo las categorías que realmente tienen productos publicados, más
        # sus padres (para no dejar referencias colgando).
        ids_usados = {p["categoria_id"] for p in datos_productos if p["categoria_id"]}
        ids_completos = set(ids_usados)
        for cat in Categoria.objects.filter(id__in=ids_usados).select_related("padre"):
            padre = cat.padre
            while padre is not None:
                ids_completos.add(padre.id)
                padre = padre.padre

        datos_categorias = [
            {"id": c.id, "nombre": c.nombre, "padre_id": c.padre_id}
            for c in Categoria.objects.filter(id__in=ids_completos).order_by("nombre")
        ]

        ruta_productos = destino / "productos.json"
        ruta_categorias = destino / "categorias.json"
        ruta_productos.write_text(
            json.dumps(datos_productos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        ruta_categorias.write_text(
            json.dumps(datos_categorias, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        sin_categoria = sum(1 for p in datos_productos if not p["categoria_id"])
        agotados = sum(1 for p in datos_productos if not p["disponible"])
        omitidos = Producto.objects.filter(empresa=empresa, activo=True).count() - len(datos_productos)

        self.stdout.write(self.style.SUCCESS(
            f"\nExportados {len(datos_productos)} productos y {len(datos_categorias)} categorías."
        ))
        self.stdout.write(f"  {ruta_productos}")
        self.stdout.write(f"  {ruta_categorias}")

        if omitidos:
            self.stdout.write(self.style.WARNING(
                f"\n  {omitidos} producto(s) activos quedaron fuera por tener precio 0. "
                "Usá --incluir-sin-precio si los querés igual."
            ))
        if sin_categoria:
            self.stdout.write(self.style.WARNING(
                f"  {sin_categoria} producto(s) sin categoría asignada: van a aparecer "
                "agrupados como 'Sin categoría' en el sitio."
            ))
        if agotados:
            self.stdout.write(
                f"  {agotados} producto(s) sin stock: se publican como no disponibles."
            )
        if not INCLUIR_IMAGENES:
            self.stdout.write(
                "\n  Imágenes NO exportadas (INCLUIR_IMAGENES=False en este archivo)."
            )
        self.stdout.write(self.style.WARNING(
            "\n  Recordá: costos y márgenes NUNCA se exportan. Solo precio de venta.\n"
        ))
