"""Carga la compra de alimento Gosbi (26/09/2026): productos, fotos y
existencias, desde el comparativo de precios de tiendas de Oscar.

    python manage.py cargar_compra_gosbi --excel "…/Gosbi_Comparativo_Tiendas_CR_2026-09-26.xlsx" \
        --fotos "…/Gosbi_Imagenes_Inventario" --factura 00100001010000010909 --dry-run

DE DÓNDE SALE
-------------
La hoja "Comparativo": por producto trae el código de Vecevet (el
distribuidor que factura), especie, nombre, presentación, cantidad
comprada, el costo unitario sin IVA de la factura, y el precio mínimo y
máximo observados en dos tiendas de Costa Rica (Petentrega y Pet Shop
2Go) para esa misma presentación. La hoja "Factura" es el respaldo:
la factura real de Vecevet (n.º 00100001010000010909, 18/09/2026) línea
por línea — su subtotal (₡406.008,85) es el control contra el que se
verificó este comando.

QUÉ PRECIO SE CARGA (decisión de Oscar, 26/09/2026)
----------------------------------------------------
A diferencia de Belina y ZeeDog, esta hoja NO trae un precio de venta ya
decidido: trae el mínimo y el máximo de dos tiendas competidoras. Oscar
eligió cargar el **mínimo** (más competitivo que el máximo, aunque deja
menos margen que la política histórica de markup de AllPetCR — ver
`claude/regla-de-precios.md` en el proyecto). Dos productos no tenían
precio en ninguna tienda (agotados en las dos): a esos se les asigna el
mínimo más bajo entre los productos de su MISMO costo unitario (misma
receta y tamaño de bolsa), que es lo más parecido a lo que Oscar habría
elegido para ellos. El reporte de la simulación avisa cuáles fueron.

EL CÓDIGO DE BARRAS ES INTERNO, NO EL DE VECEVET
--------------------------------------------------
El "código proveedor" de esta hoja (71020, 918, 920…) es el código interno
de Vecevet, no un EAN de fábrica — a diferencia de los UPC reales de
ZeeDog. Por eso acá se genera un EAN-8 interno para la etiqueta, igual que
se hizo con Belina.

CÓMO SE ASIGNA LA CATEGORÍA (decisión de Oscar, 26/09/2026)
-------------------------------------------------------------
La hoja no trae columna de categoría. Nunca se crea una nueva: se cuelga
del árbol oficial según esta regla, confirmada con Oscar porque "Gosbits"
y "Natsbi" no son alimento completo obvio:

- Presentación en kilos (bolsas de 1,5 a 3 kg, sea de perro o de gato) →
  Alimento › Alimento seco.
- Nombre con "Gosbits" (premio semihúmedo en bolsita) → Snacks y premios.
- El resto (Natsbi, Fresko, Delicat — bolsitas húmedas) → Alimento ›
  Alimento húmedo.

GARANTÍAS
---------
- Todo o nada (una transacción). `--dry-run` muestra lo que haría sin guardar.
- La misma factura no entra dos veces (lo cuida `compras.services`).
- Un producto que ya existe (mismo SKU) no se toca: solo recibe mercadería.
"""
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo import cabys
from catalogo.codigos import siguiente_interno
from catalogo.completar import buscar_categoria, normalizar_mascota
from catalogo.models import Producto
from compras.models import Proveedor
from compras.services import crear_y_recibir_compra
from core.models import Empresa, Sucursal

HOJA = "Comparativo"
PREFIJO_SKU = "GOS-"
EXTENSIONES = (".jpg", ".jpeg", ".png", ".webp")
TASA_IVA = Decimal("0.13")

COLUMNAS = ["Código proveedor", "Especie", "Marca", "Producto", "Presentación", "Cantidad comprada",
            "Costo unitario sin IVA", "Venta mínimo CR", "Venta máximo CR", "Archivo imagen"]


def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def _decimal(v):
    t = _texto(v).replace("₡", "").replace(",", "")
    if not t:
        return None
    try:
        return Decimal(t)
    except Exception:
        raise CommandError(f"«{v}» no es un número.")


def categoria_de(nombre_producto, presentacion):
    if presentacion.strip().lower().endswith("kg"):
        return "Alimento › Alimento seco"
    if "gosbits" in nombre_producto.lower():
        return "Snacks y premios"
    return "Alimento › Alimento húmedo"


def nombre_de_venta(nombre, marca, presentacion):
    """"Natsbi Steamed Duck" + Gosbi + "500 g" → "Gosbi Natsbi Steamed Duck 500 g".
    La hoja ya marca "Gosbi" como marca de Natsbi, Gosbits, Fresko y Delicat
    (son todas líneas del mismo fabricante), así que un producto se busca por
    "Gosbi" y aparecen todas. Presentación al final para que dos tamaños del
    mismo sabor no queden con el mismo nombre."""
    if marca and not nombre.lower().startswith(marca.lower()):
        nombre = f"{marca} {nombre}"
    if presentacion and presentacion.lower() not in nombre.lower():
        nombre = f"{nombre} {presentacion}"
    return nombre[:200]


class Command(BaseCommand):
    help = "Carga la compra de alimento Gosbi (productos, fotos) desde su Excel comparativo."

    def add_arguments(self, parser):
        parser.add_argument("--excel", required=True)
        parser.add_argument("--fotos", default="", help="Carpeta con las fotos, nombradas por código de Vecevet.")
        parser.add_argument("--factura", required=True, help="N.º de factura de Vecevet.")
        parser.add_argument("--proveedor", default="VECEVET")
        parser.add_argument("--forma-pago", default="CON", choices=["CON", "CRE"])
        parser.add_argument("--dry-run", action="store_true")

    # ── lectura ──────────────────────────────────────────────────────────
    def _leer(self, ruta):
        from openpyxl import load_workbook

        if not Path(ruta).is_file():
            raise CommandError(f"No encontré el Excel: {ruta}")
        wb = load_workbook(ruta, data_only=True, read_only=True)
        if HOJA not in wb.sheetnames:
            raise CommandError(f"El Excel no tiene la hoja «{HOJA}». Hojas: {', '.join(wb.sheetnames)}")
        filas = list(wb[HOJA].iter_rows(values_only=True))

        fila_enc = None
        for n, f in enumerate(filas):
            enc = [_texto(c) for c in f]
            if all(c in enc for c in COLUMNAS):
                fila_enc = n
                break
        if fila_enc is None:
            raise CommandError(f"No encontré la fila de encabezados en la hoja «{HOJA}».")
        enc = [_texto(c) for c in filas[fila_enc]]
        idx = {n: enc.index(n) for n in COLUMNAS}

        datos, errores, vistos = [], [], set()
        for n, f in enumerate(filas[fila_enc + 1:], start=fila_enc + 2):
            if not any(_texto(c) for c in f):
                continue
            d = {k: f[i] if i < len(f) else None for k, i in idx.items()}
            codigo = _texto(d["Código proveedor"])
            fila = {
                "fila": n, "codigo": codigo, "marca": _texto(d["Marca"]),
                "mascota_txt": _texto(d["Especie"]), "producto": _texto(d["Producto"]),
                "presentacion": _texto(d["Presentación"]),
                "cantidad": _decimal(d["Cantidad comprada"]) or Decimal("0"),
                "costo": _decimal(d["Costo unitario sin IVA"]),
                "venta_minimo": _decimal(d["Venta mínimo CR"]),
                "archivo": _texto(d["Archivo imagen"]),
            }
            if not codigo:
                errores.append(f"Fila {n}: sin código de proveedor.")
            elif codigo in vistos:
                errores.append(f"Fila {n}: el código {codigo} está repetido.")
            vistos.add(codigo)
            if fila["cantidad"] <= 0:
                errores.append(f"Fila {n} ({codigo}): la cantidad tiene que ser mayor que cero.")
            if fila["costo"] is None or fila["costo"] <= 0:
                errores.append(f"Fila {n} ({codigo}): falta el costo.")
            if not fila["producto"]:
                errores.append(f"Fila {n} ({codigo}): falta el nombre del producto.")
            fila["mascota"] = normalizar_mascota(fila["mascota_txt"]) or ""
            if fila["mascota_txt"] and not fila["mascota"]:
                errores.append(f"Fila {n} ({codigo}): especie «{fila['mascota_txt']}» no válida.")
            nombre_categoria = categoria_de(fila["producto"], fila["presentacion"])
            fila["categoria"] = buscar_categoria(nombre_categoria)
            if fila["categoria"] is None:
                errores.append(f"Fila {n} ({codigo}): la categoría «{nombre_categoria}» no existe en el ERP.")
            fila["categoria_txt"] = nombre_categoria
            fila["nombre_venta"] = nombre_de_venta(fila["producto"], fila["marca"], fila["presentacion"])
            datos.append(fila)

        # Precio: el mínimo de tienda. Si ninguna tienda lo tenía (agotado en
        # las dos), se usa el mínimo más bajo entre productos del MISMO costo
        # unitario (misma receta y tamaño de bolsa) — ver el docstring.
        por_costo = {}
        for f in datos:
            if f["venta_minimo"] is not None and f["costo"] is not None:
                por_costo.setdefault(f["costo"], []).append(f["venta_minimo"])
        sin_precio_de_mercado = []
        for f in datos:
            if f["venta_minimo"] is not None:
                f["precio"] = f["venta_minimo"]
                f["precio_inferido"] = False
            else:
                candidatos = por_costo.get(f["costo"], [])
                if not candidatos:
                    errores.append(f"Fila {f['fila']} ({f['codigo']}): sin precio de ninguna tienda y sin otro "
                                   "producto del mismo costo para estimarlo. Decime qué precio ponerle.")
                    continue
                f["precio"] = min(candidatos)
                f["precio_inferido"] = True
                sin_precio_de_mercado.append(f"{f['codigo']} {f['nombre_venta']} -> ₡{f['precio']:,.0f}")

        nombres = {}
        for fila in datos:
            nombres.setdefault(fila["nombre_venta"].lower(), []).append(fila["codigo"])
        for nombre, codigos in nombres.items():
            if len(codigos) > 1:
                errores.append(f"Dos productos quedarían con el mismo nombre ({', '.join(codigos)}): {nombre}")

        if errores:
            raise CommandError("El Excel tiene errores, no se cargó nada:\n  " + "\n  ".join(errores))
        return datos, sin_precio_de_mercado

    def _fotos(self, carpeta):
        if not carpeta:
            return {}
        p = Path(carpeta)
        if not p.is_dir():
            raise CommandError(f"No encontré la carpeta de fotos: {carpeta}")
        return {a.stem: a for a in p.iterdir() if a.is_file() and a.suffix.lower() in EXTENSIONES}

    # ── carga ────────────────────────────────────────────────────────────
    def handle(self, *args, **op):
        seco = op["dry_run"]
        datos, sin_precio_de_mercado = self._leer(op["excel"])
        fotos = self._fotos(op["fotos"])
        empresa = Empresa.objects.first()
        sucursal = Sucursal.objects.filter(empresa=empresa).order_by("id").first()
        if empresa is None or sucursal is None:
            raise CommandError("No hay empresa o sucursal configurada.")

        r = {"nuevos": 0, "existentes": 0, "fotos": 0, "sin_foto": [], "por_categoria": {}}
        with transaction.atomic():
            usados = set(Producto.objects.exclude(codigo_barras="").values_list("codigo_barras", flat=True))
            lineas = []
            for f in datos:
                sku = PREFIJO_SKU + f["codigo"]
                producto = Producto.objects.filter(sku=sku).first()
                if producto is None:
                    producto = Producto.objects.create(
                        empresa=empresa, sku=sku, nombre=f["nombre_venta"], precio_venta=f["precio"],
                        marca=f["marca"][:80], presentacion=f["presentacion"][:120], mascota=f["mascota"],
                        categoria=f["categoria"], categoria_original=f["categoria_txt"],
                    )
                    codigo_barras = siguiente_interno(usados)
                    usados.add(codigo_barras)
                    producto.codigo_barras = codigo_barras
                    propuesta = cabys.proponer(producto)
                    campos = ["codigo_barras"]
                    if propuesta:
                        producto.cabys = propuesta.codigo
                        campos.append("cabys")
                    producto.save(update_fields=campos)
                    r["nuevos"] += 1
                else:
                    r["existentes"] += 1

                r["por_categoria"][f["categoria_txt"]] = r["por_categoria"].get(f["categoria_txt"], 0) + 1

                archivo = fotos.get(f["codigo"])
                if archivo is None:
                    r["sin_foto"].append(f"{f['codigo']} {f['nombre_venta']}")
                elif not producto.imagen:
                    if not seco:
                        from core.imagenes import guardar_imagen_producto

                        producto.imagen = guardar_imagen_producto(
                            f"{sku}{archivo.suffix.lower()}", archivo.read_bytes())
                        producto.save(update_fields=["imagen"])
                    r["fotos"] += 1

                lineas.append({"producto": producto, "cantidad": f["cantidad"], "costo_unitario": f["costo"]})

            proveedor = Proveedor.objects.filter(empresa=empresa, nombre__iexact=op["proveedor"]).first()
            if proveedor is None:
                proveedor = Proveedor.objects.create(empresa=empresa, nombre=op["proveedor"])
            subtotal = sum((l["cantidad"] * l["costo_unitario"] for l in lineas), Decimal("0"))
            tradicional = empresa.regimen == Empresa.Regimen.TRADICIONAL
            iva = (subtotal * TASA_IVA).quantize(Decimal("0.01"), ROUND_HALF_UP) if tradicional else Decimal("0")
            compra = crear_y_recibir_compra(
                proveedor=proveedor, sucursal=sucursal, lineas=lineas, forma_pago=op["forma_pago"],
                factura_proveedor=op["factura"], iva=iva,
            )
            self._informe(r, datos, compra, sin_precio_de_mercado, seco)
            if seco:
                transaction.set_rollback(True)

    def _informe(self, r, datos, compra, sin_precio_de_mercado, seco):
        w = self.stdout.write
        unidades = sum(f["cantidad"] for f in datos)
        w("")
        w(f"  Productos en la hoja ....... {len(datos)}  (nuevos {r['nuevos']}, ya existían {r['existentes']})")
        w(f"  Unidades que entran ........ {unidades:g}")
        w(f"  Compra ..................... {compra.numero} — factura {compra.factura_proveedor} — "
          f"{compra.get_forma_pago_display()}")
        w(f"  Subtotal sin IVA ........... ₡{compra.total:,.2f}")
        w(f"  IVA 13 % ................... ₡{compra.iva:,.2f}")
        w(self.style.SUCCESS(f"  TOTAL DE LA FACTURA ........ ₡{compra.total + compra.iva:,.2f}"
                             "   <- comparalo con la factura de Vecevet"))
        w("  Se cargó el precio MÍNIMO de mercado entre las tiendas consultadas (así lo pediste).")
        w(f"  Fotos asociadas ............ {r['fotos']}")
        w("\n  Categoría asignada (revisá que tenga sentido antes de confirmar):")
        for categoria, cantidad in sorted(r["por_categoria"].items()):
            w(f"    {categoria} ...... {cantidad}")
        if sin_precio_de_mercado:
            w(self.style.WARNING(f"\n  Sin precio en ninguna tienda (agotados): {len(sin_precio_de_mercado)}"))
            w("  Se les puso el mínimo de otro producto del mismo costo — revisalos con más cuidado:")
            for linea in sin_precio_de_mercado:
                w(f"    {linea}")
        if r["sin_foto"]:
            w(self.style.WARNING(f"\n  Sin foto en la carpeta: {len(r['sin_foto'])}"))
            for linea in r["sin_foto"]:
                w(f"    {linea}")
        if seco:
            w(self.style.WARNING("\n  SIMULACIÓN: no se guardó nada.\n"))
        else:
            w(self.style.SUCCESS("\n  LISTO: guardado.\n"))
