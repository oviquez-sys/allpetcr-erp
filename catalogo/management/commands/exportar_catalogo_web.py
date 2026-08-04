"""Exporta el catálogo real al sitio web (allpetcr-web/).

Por qué existe
-------------
El sitio web necesita mostrar productos reales, pero el ERP todavía no expone
una API (no hay Django REST Framework instalado). Este comando es el puente
simple mientras tanto: lee la base real, escribe los dos JSON que el sitio ya
sabe leer y copia las fotos a su carpeta pública.

Cuando exista la API, este comando deja de ser necesario: el sitio hará fetch
en vivo. Hasta entonces, se corre a mano cada vez que cambien precios,
productos o existencias.

QUÉ NO SE EXPORTA (deliberado, no olvido)
-----------------------------------------
- `costo_promedio`, `margen_pct`, `markup_pct`: es lo que te cuesta y lo que
  ganás. Publicarlo en internet le entrega tu estructura de costos a la
  competencia. NUNCA debe salir.
- `stock_actual` exacto: se traduce a un booleano `disponible`. Publicar
  "quedan 3 unidades" le dice a cualquiera cuánto volumen manejás. El cliente
  solo necesita saber si hay o no hay.
- Productos inactivos: no se exportan.
- Productos sin existencias: no se exportan (ver SOLO_EN_EXISTENCIA).
"""
import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalogo.models import Categoria, Producto
from core.models import Empresa

# Las fotos de producto ya están listas: entraron con el inventario del
# 02/08/2026 (528 imágenes en data/INVENTARIO_ALLPETCR.xlsx, ~15 KB cada una).
# Antes esto era False porque las fotos viejas no estaban para publicarse.
INCLUIR_IMAGENES = True

# ─────────────────────────────────────────────────────────────────────────
#  REGLA: el sitio solo publica lo que hay en existencia.
#  Decidido por Oscar el 02/08/2026.
#
#  QUÉ CUESTA, para que la decisión se pueda revisar con los datos a la vista:
#  un producto agotado desaparece del sitio y su página `/producto/<sku>`
#  deja de existir. Si Google ya la había indexado, pasa a dar 404 y se
#  pierde el posicionamiento que tenía; cuando el producto vuelva, arranca
#  de cero. La práctica habitual en comercio electrónico es la contraria —
#  conservar la página y marcarla `OutOfStock`, que es lo que el sitio ya
#  sabe hacer con la insignia "Sin existencias".
#
#  Hoy el punto es discutible: de los 532 productos del catálogo, 348 están
#  en cero, y publicar 348 fichas vacías tampoco ayuda a nadie.
#
#  Para volver atrás: poner False. El sitio no necesita ningún otro cambio,
#  vuelve a recibir los agotados con `disponible: false` y los muestra con
#  su insignia.
# ─────────────────────────────────────────────────────────────────────────
SOLO_EN_EXISTENCIA = True

# Ruta por defecto del proyecto web, relativa a la carpeta del ERP.
WEB_POR_DEFECTO = Path(__file__).resolve().parents[4] / "allpetcr-web"


class Command(BaseCommand):
    help = "Exporta el catálogo (productos, categorías e imágenes) al sitio web."

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
        parser.add_argument(
            "--incluir-agotados", action="store_true",
            help="Publicar también lo que no hay en existencia, marcado como no "
                 "disponible. Anula SOLO_EN_EXISTENCIA para esta corrida.",
        )
        parser.add_argument(
            "--limpiar-imagenes", action="store_true",
            help="Borra de public/productos/ las fotos de productos que ya no se "
                 "publican. Por defecto solo se cuentan: borrar archivos es "
                 "irreversible y la carpeta pesa poco.",
        )

    def handle(self, *args, **opciones):
        empresa = Empresa.objects.first()
        if empresa is None:
            raise CommandError("No hay ninguna empresa configurada en la base de datos.")

        destino = Path(opciones["destino"]) if opciones["destino"] else WEB_POR_DEFECTO / "data"
        if not destino.exists():
            raise CommandError(
                f"No existe la carpeta destino:\n  {destino}\n\n"
                "Verificá que el proyecto allpetcr-web esté junto a allpetcr-erp, "
                "o pasá la ruta con --destino."
            )
        raiz_web = destino.parent

        activos = Producto.objects.filter(empresa=empresa, activo=True)
        productos = activos.select_related("categoria")
        if not opciones["incluir_sin_precio"]:
            productos = productos.exclude(precio_venta=0)

        solo_stock = SOLO_EN_EXISTENCIA and not opciones["incluir_agotados"]
        if solo_stock:
            productos = productos.filter(stock_actual__gt=0)
        productos = productos.order_by("nombre")

        datos_productos = []
        for p in productos:
            fila = {
                "sku": p.sku,
                "nombre": p.nombre,
                "categoria_id": p.categoria_id,
                "presentacion": p.presentacion or "",
                "descripcion": p.descripcion or "",
                "mascota": p.mascota or "",
                "precio_venta": float(p.precio_venta),
                # Booleano, NO la cantidad exacta: el cliente necesita saber si
                # hay, no cuánto inventario manejás. Con SOLO_EN_EXISTENCIA
                # activo siempre sale True, pero el campo se mantiene: entre
                # dos exportaciones el stock cambia, y el sitio necesita poder
                # marcar un agotado sin esperar a la siguiente corrida.
                "disponible": p.stock_actual > 0,
                "imagen": self._ruta_web(p) if INCLUIR_IMAGENES else "",
            }
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

        copiadas, sobrantes = 0, []
        if INCLUIR_IMAGENES:
            copiadas, sobrantes = self._copiar_imagenes(
                datos_productos, raiz_web, opciones["limpiar_imagenes"]
            )

        # ── resumen ──
        sin_categoria = sum(1 for p in datos_productos if not p["categoria_id"])
        sin_foto = sum(1 for p in datos_productos if not p["imagen"])
        agotados_fuera = activos.filter(stock_actual__lte=0).count() if solo_stock else 0
        sin_precio_fuera = 0 if opciones["incluir_sin_precio"] else activos.filter(precio_venta=0).count()

        self.stdout.write(self.style.SUCCESS(
            f"\nExportados {len(datos_productos)} productos y {len(datos_categorias)} categorías."
        ))
        self.stdout.write(f"  {ruta_productos}")
        self.stdout.write(f"  {ruta_categorias}")
        if INCLUIR_IMAGENES:
            self.stdout.write(f"  {copiadas} imágenes → {raiz_web / 'public' / 'productos'}")

        if solo_stock and agotados_fuera:
            self.stdout.write(self.style.WARNING(
                f"\n  {agotados_fuera} producto(s) activos NO se publicaron por estar sin "
                "existencias (regla SOLO_EN_EXISTENCIA).\n"
                "  Usá --incluir-agotados si necesitás publicarlos marcados como agotados."
            ))
        if sin_precio_fuera:
            self.stdout.write(self.style.WARNING(
                f"  {sin_precio_fuera} producto(s) quedaron fuera por tener precio 0. "
                "Usá --incluir-sin-precio si los querés igual."
            ))
        if sin_categoria:
            self.stdout.write(self.style.WARNING(
                f"  {sin_categoria} producto(s) sin categoría asignada: van a aparecer "
                "agrupados como 'Sin categoría' en el sitio."
            ))
        if sin_foto:
            self.stdout.write(self.style.WARNING(
                f"  {sin_foto} producto(s) publicados sin foto: el sitio muestra "
                "'Foto pendiente' en su lugar."
            ))
        if sobrantes:
            accion = "borradas" if opciones["limpiar_imagenes"] else "sin usar"
            self.stdout.write(
                f"  {len(sobrantes)} foto(s) en public/productos/ de productos que ya no se "
                f"publican ({accion})."
            )
            if not opciones["limpiar_imagenes"]:
                self.stdout.write("    Usá --limpiar-imagenes para borrarlas.")

        self.stdout.write(self.style.WARNING(
            "\n  Recordá: costos y márgenes NUNCA se exportan. Solo precio de venta.\n"
        ))

    # ── imágenes ─────────────────────────────────────────────────────────
    @staticmethod
    def _ruta_web(producto):
        """Ruta pública de la foto, o "" si el producto no tiene.

        `Producto.imagen` guarda "productos/75564.jpeg" (relativo a media/).
        El sitio la sirve desde su propio public/, así que la ruta publicada
        es "/productos/75564.jpeg" — absoluta, para que funcione igual en la
        portada, en el catálogo y en la ficha, sin depender de la URL actual.
        """
        if not producto.imagen:
            return ""
        return "/" + producto.imagen.lstrip("/")

    def _copiar_imagenes(self, datos, raiz_web, limpiar):
        """Copia a public/productos/ solo las fotos de lo que se publica.

        Se copia en vez de enlazar porque son dos proyectos independientes,
        cada uno con su despliegue: el sitio tiene que poder construirse sin
        el ERP al lado.
        """
        origen = Path(settings.MEDIA_ROOT) / "productos"
        destino = raiz_web / "public" / "productos"
        destino.mkdir(parents=True, exist_ok=True)

        esperados = set()
        copiadas = 0
        for fila in datos:
            if not fila["imagen"]:
                continue
            nombre = Path(fila["imagen"]).name
            esperados.add(nombre)
            src = origen / nombre
            if not src.exists():
                # La ruta está en la base pero el archivo no está en media/:
                # se publica sin foto en vez de dejar una imagen rota.
                fila["imagen"] = ""
                continue
            dst = destino / nombre
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dst)
            copiadas += 1

        sobrantes = [f for f in destino.iterdir() if f.is_file() and f.name not in esperados]
        if limpiar:
            for f in sobrantes:
                f.unlink()
        return copiadas, sobrantes
