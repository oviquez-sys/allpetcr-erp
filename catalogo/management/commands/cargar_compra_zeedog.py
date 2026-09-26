"""Carga la compra de accesorios Zee.Dog / P.L.A.Y. (26/09/2026): productos,
fotos y existencias, desde el comparativo de precios oficiales de Oscar.

    python manage.py cargar_compra_zeedog --excel "…/ZeeDog_Comparativo_Oficial_CR_2026-09-26.xlsx" \
        --fotos "…/ZeeDog_Imagenes_Inventario" --factura OV-16251 --dry-run

DE DÓNDE SALE
-------------
La hoja "Comparativo" del Excel que armó Oscar: por cada producto trae el UPC
real de fábrica, marca, especie, nombre, variante (color/talla), cantidad
comprada, el costo neto SIN IVA que de verdad pagó (ya con el 5% de descuento
del proveedor aplicado) y el precio oficial de venta en Costa Rica (la
referencia de ZeeDog, que ya incluye IVA). La hoja "Orden de venta" es el
respaldo: la factura de Thinko Distribution línea por línea, y su subtotal
(₡667.522,14) cuadra con la columna de costo de "Comparativo" — se usa para
verificar, no se lee en este comando.

A diferencia de la compra de Belina, ACÁ NO HAY BONIFICACIONES: todo lo que
trae la hoja se pagó, así que cada línea entra con su cantidad facturada nomás.

EL CÓDIGO DE BARRAS ES EL UPC DE VERDAD, NO UNO INTERNO
--------------------------------------------------------
Los productos de Belina venían sueltos, sin código de fábrica que sirviera de
nada acá, y por eso a cada uno se le generaba un EAN-8 interno para la
etiqueta. Estos productos de Zee.Dog SÍ traen su propio código de barras real
(UPC/EAN de fábrica, ya impreso en el empaque), y ese código es el que se
guarda en `codigo_barras`: así, si el producto todavía trae su etiqueta
original, el POS ya lo reconoce sin necesidad de reetiquetarlo, y si hay que
imprimir una etiqueta nueva, sale con el mismo número (la pantalla de
etiquetas ya sabe dibujar EAN-13 o, si el código no es un EAN válido —caso de
los UPC de 12 dígitos—, Code128; ver `impresion/etiqueta.py::_simbologia`).

CÓMO SE ASIGNA LA CATEGORÍA
----------------------------
La hoja no trae columna de categoría (a diferencia de la de Belina): se
deduce del nombre del producto contra el árbol oficial, nunca se crea una
categoría nueva. Ver `_CATEGORIA_POR_PALABRA`. El reporte de la simulación
muestra cuántos productos cayeron en cada categoría para que Oscar lo revise
antes de confirmar.

GARANTÍAS
---------
- Todo o nada (una transacción). `--dry-run` muestra lo que haría sin guardar.
- La misma factura no entra dos veces (lo cuida `compras.services`).
- Un producto que ya existe (mismo SKU, o sea mismo UPC) no se toca: solo
  recibe mercadería nueva.
"""
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo import cabys
from catalogo.completar import buscar_categoria, normalizar_mascota
from catalogo.models import Producto
from compras.models import Proveedor
from compras.services import crear_y_recibir_compra
from core.models import Empresa, Sucursal

HOJA = "Comparativo"
PREFIJO_SKU = "ZDG-"
EXTENSIONES = (".jpg", ".jpeg", ".png", ".webp")
TASA_IVA = Decimal("0.13")

COLUMNAS = ["UPC proveedor", "Marca", "Especie", "Producto en documento", "Cantidad",
            "Costo neto sin IVA", "Precio oficial CR", "Nombre oficial", "Variante verificada",
            "Archivo de imagen"]

# Palabra en el nombre del producto → categoría del árbol oficial. La primera
# que calza gana. Nunca se crea una categoría: si no calza ninguna, cae en
# "Juguetes", que es donde vive el resto del catálogo de accesorios sueltos
# de este mismo pedido (los "Brainiacs", las frutas de peluche, etc.)
_CATEGORIA_POR_PALABRA = [
    ("BOWL", "Comederos y bebederos"),
    ("AIRTAG", "Ropa y accesorios"),
    ("COLLAR", "Paseo"),
    ("HARNESS", "Paseo"),
    ("ARNES", "Paseo"),
    ("LEASH", "Paseo"),
]
CATEGORIA_POR_DEFECTO = "Juguetes"


def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def _decimal(v):
    t = _texto(v).replace("₡", "").replace(",", "")
    if not t:
        return Decimal("0")
    try:
        return Decimal(t)
    except Exception:
        raise CommandError(f"«{v}» no es un número.")


def categoria_de(nombre_producto):
    n = nombre_producto.upper()
    for palabra, categoria in _CATEGORIA_POR_PALABRA:
        if palabra in n:
            return categoria
    return CATEGORIA_POR_DEFECTO


def nombre_de_venta(nombre_oficial, marca, variante):
    """"Zee.Bowl - Plato ajustable para perro" + Zee.Dog + Bordeau →
    "Zee.Dog Zee.Bowl - Plato ajustable para perro Bordeau". Así dos colores o
    tallas del mismo modelo no quedan con el mismo nombre."""
    nombre = nombre_oficial
    if marca and not nombre.lower().startswith(marca.lower()):
        nombre = f"{marca} {nombre}"
    if variante and variante.lower() not in nombre.lower() and variante.lower() not in ("única", "unica"):
        nombre = f"{nombre} {variante}"
    return nombre[:200]


class Command(BaseCommand):
    help = "Carga la compra de accesorios Zee.Dog / P.L.A.Y. (productos, fotos) desde su Excel comparativo."

    def add_arguments(self, parser):
        parser.add_argument("--excel", required=True)
        parser.add_argument("--fotos", default="", help="Carpeta con las fotos, nombradas por UPC.")
        parser.add_argument("--factura", required=True, help="N.º de factura/orden de Thinko Distribution.")
        parser.add_argument("--proveedor", default="THINKO DISTRIBUTION")
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
            upc = _texto(d["UPC proveedor"])
            producto_doc = _texto(d["Producto en documento"])
            fila = {
                "fila": n, "upc": upc, "marca": _texto(d["Marca"]),
                "mascota_txt": _texto(d["Especie"]), "producto_doc": producto_doc,
                "cantidad": _decimal(d["Cantidad"]),
                "costo": _decimal(d["Costo neto sin IVA"]).quantize(Decimal("0.01"), ROUND_HALF_UP),
                "precio": _decimal(d["Precio oficial CR"]),
                "nombre_oficial": _texto(d["Nombre oficial"]), "variante": _texto(d["Variante verificada"]),
                "archivo": _texto(d["Archivo de imagen"]),
            }
            if not upc:
                errores.append(f"Fila {n}: sin UPC de proveedor.")
            elif upc in vistos:
                errores.append(f"Fila {n}: el UPC {upc} está repetido.")
            vistos.add(upc)
            if fila["cantidad"] <= 0:
                errores.append(f"Fila {n} ({upc}): la cantidad tiene que ser mayor que cero.")
            if fila["costo"] <= 0:
                errores.append(f"Fila {n} ({upc}): falta el costo.")
            if fila["precio"] <= 0:
                errores.append(f"Fila {n} ({upc}): falta el precio oficial.")
            if not fila["nombre_oficial"]:
                errores.append(f"Fila {n} ({upc}): falta el nombre oficial.")
            fila["mascota"] = normalizar_mascota(fila["mascota_txt"]) or ""
            if fila["mascota_txt"] and not fila["mascota"]:
                errores.append(f"Fila {n} ({upc}): especie «{fila['mascota_txt']}» no válida.")
            nombre_categoria = categoria_de(fila["producto_doc"])
            fila["categoria"] = buscar_categoria(nombre_categoria)
            if fila["categoria"] is None:
                errores.append(f"Fila {n} ({upc}): la categoría «{nombre_categoria}» no existe en el ERP.")
            fila["categoria_txt"] = nombre_categoria
            fila["nombre_venta"] = nombre_de_venta(fila["nombre_oficial"], fila["marca"], fila["variante"])
            datos.append(fila)

        nombres = {}
        for fila in datos:
            nombres.setdefault(fila["nombre_venta"].lower(), []).append(fila["upc"])
        for nombre, upcs in nombres.items():
            if len(upcs) > 1:
                errores.append(f"Dos productos quedarían con el mismo nombre ({', '.join(upcs)}): {nombre}")

        usados_en_erp = set(Producto.objects.exclude(codigo_barras="")
                             .exclude(sku__in=[PREFIJO_SKU + f["upc"] for f in datos])
                             .values_list("codigo_barras", flat=True))
        for f in datos:
            if f["upc"] in usados_en_erp:
                errores.append(f"Fila {f['fila']} ({f['upc']}): ese código de barras ya lo tiene otro producto.")

        if errores:
            raise CommandError("El Excel tiene errores, no se cargó nada:\n  " + "\n  ".join(errores))
        return datos

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
        datos = self._leer(op["excel"])
        fotos = self._fotos(op["fotos"])
        empresa = Empresa.objects.first()
        sucursal = Sucursal.objects.filter(empresa=empresa).order_by("id").first()
        if empresa is None or sucursal is None:
            raise CommandError("No hay empresa o sucursal configurada.")

        r = {"nuevos": 0, "existentes": 0, "fotos": 0, "sin_foto": [], "por_categoria": {}}
        with transaction.atomic():
            lineas = []
            for f in datos:
                sku = PREFIJO_SKU + f["upc"]
                producto = Producto.objects.filter(sku=sku).first()
                if producto is None:
                    producto = Producto.objects.create(
                        empresa=empresa, sku=sku, nombre=f["nombre_venta"], precio_venta=f["precio"],
                        marca=f["marca"][:80], presentacion=f["variante"][:120], mascota=f["mascota"],
                        categoria=f["categoria"], categoria_original=f["categoria_txt"],
                        codigo_barras=f["upc"],
                    )
                    propuesta = cabys.proponer(producto)
                    if propuesta:
                        producto.cabys = propuesta.codigo
                        producto.save(update_fields=["cabys"])
                    r["nuevos"] += 1
                else:
                    r["existentes"] += 1

                r["por_categoria"][f["categoria_txt"]] = r["por_categoria"].get(f["categoria_txt"], 0) + 1

                archivo = fotos.get(f["upc"])
                if archivo is None:
                    r["sin_foto"].append(f"{f['upc']} {f['nombre_venta']}")
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
            self._informe(r, datos, compra, seco)
            if seco:
                transaction.set_rollback(True)

    def _informe(self, r, datos, compra, seco):
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
                             "   <- comparalo con el papel de Thinko/ZeeDog"))
        w("  (puede diferir del papel por unos pocos centavos: el costo de fábrica trae más "
          "decimales de los que guarda el ERP; no es un error.)")
        w(f"  Fotos asociadas ............ {r['fotos']}")
        w("\n  Categoría asignada (revisá que tenga sentido antes de confirmar):")
        for categoria, cantidad in sorted(r["por_categoria"].items()):
            w(f"    {categoria} ...... {cantidad}")
        if r["sin_foto"]:
            w(self.style.WARNING(f"\n  Sin foto en la carpeta: {len(r['sin_foto'])}"))
            for linea in r["sin_foto"]:
                w(f"    {linea}")
        if seco:
            w(self.style.WARNING("\n  SIMULACIÓN: no se guardó nada.\n"))
        else:
            w(self.style.SUCCESS("\n  LISTO: guardado.\n"))
