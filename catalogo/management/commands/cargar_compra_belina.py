"""Carga la compra de alimento de Belina (26/09/2026): productos, fotos y existencias.

    python manage.py cargar_compra_belina --excel "…/Belina precios allpet.xlsx" \
        --fotos "…/Belina_Imagenes_Inventario" --factura 12345 --dry-run

DE DÓNDE SALE
-------------
La hoja "Inventario (subir)" que armó Oscar con el comparativo de precios del
mercado. Columnas que se usan: Código de proveedor, Nombre, Cantidad, Costo
unitario (sin IVA), Precio de venta (con IVA), Bonificadas, Marca, Categoría,
Presentación, Mascota. Las demás (precio más bajo, alerta…) son el trabajo de
precios y no se cargan.

LAS BONIFICADAS
---------------
Belina mandó unidades de regalo. Instrucción de Oscar: que queden registradas
a costo cero, con el precio sugerido, para poder etiquetarlas y regalarlas o
venderlas. Entran como bonificadas de la MISMA compra, así el documento cuadra
contra el papel del proveedor:

- Producto que vino SOLO de regalo (Cantidad 0): la línea lleva 0 facturadas y
  N bonificadas; entra a bodega a costo cero y la factura no la cobra.
- Producto que vino pagado y además con regalo (ej. 1 + 1): el costo de la
  factura se reparte entre todas las unidades (ver
  `LineaCompra.costo_real_unitario`). La unidad regalada no suma costo; el
  costo promedio baja, que es justamente lo que vale el regalo.

POR QUÉ UN COMANDO Y NO LA PANTALLA DE CARGA MASIVA
---------------------------------------------------
La pantalla reconoce productos por código de barras o por nombre, y esta hoja
no trae ninguno de los dos que sirva: el código es el interno de Belina y hay
nombres repetidos entre presentaciones ("Balance Puppy" 2 kg, 5 kg, 9,07 kg y
14,97 kg). Además hay 120 fotos que asociar. El comando usa el código de
Belina como SKU con prefijo (BEL-17004) —así no choca con los SKU de 5 dígitos
del otro proveedor— y sube cada foto al producto de su código.

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

HOJA = "Inventario (subir)"
PREFIJO_SKU = "BEL-"
EXTENSIONES = (".jpg", ".jpeg", ".png", ".webp")
TASA_IVA = Decimal("0.13")

# Categoría de la hoja → categoría del árbol oficial. Nunca se crea una.
CATEGORIAS = {
    "alimento seco": "Alimento › Alimento seco",
    "alimento humedo": "Alimento › Alimento húmedo",
    "alimento húmedo": "Alimento › Alimento húmedo",
    "premios": "Snacks y premios",
}

# Abreviaturas de la factura que se reemplazan por la marca en el nombre.
ABREVIATURAS = {"PureVita": ("PV ",), "NutriSource": ("NS ",)}


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


def nombre_de_venta(nombre, marca, presentacion):
    """"PV GF DOG Salmon" + PureVita + 4 lb → "PureVita GF DOG Salmon 4 lb".

    Así el cliente y el cajero ven la marca, y dos presentaciones del mismo
    alimento no quedan con el mismo nombre."""
    for prefijo in ABREVIATURAS.get(marca, ()):
        if nombre.startswith(prefijo):
            nombre = nombre[len(prefijo):]
    if marca and not nombre.lower().startswith(marca.lower()):
        nombre = f"{marca} {nombre}"
    if presentacion and presentacion.lower() not in nombre.lower():
        nombre = f"{nombre} {presentacion}"
    return nombre[:200]


class Command(BaseCommand):
    help = "Carga la compra de Belina (productos, bonificadas, fotos) desde su Excel."

    def add_arguments(self, parser):
        parser.add_argument("--excel", required=True)
        parser.add_argument("--fotos", default="", help="Carpeta con las fotos, nombradas por código.")
        parser.add_argument("--factura", required=True, help="N.º de factura de Belina.")
        parser.add_argument("--proveedor", default="BELINA")
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
        enc = [_texto(c) for c in filas[0]]
        necesarias = ["Código de proveedor", "Nombre", "Cantidad", "Costo unitario", "Precio de venta",
                      "Bonificadas", "Marca", "Categoría", "Presentación", "Mascota"]
        faltan = [n for n in necesarias if n not in enc]
        if faltan:
            raise CommandError(f"Faltan columnas en la hoja: {', '.join(faltan)}")
        idx = {n: enc.index(n) for n in necesarias}

        datos, errores, vistos = [], [], set()
        for n, f in enumerate(filas[1:], start=2):
            if not any(_texto(c) for c in f):
                continue
            d = {k: f[i] if i < len(f) else None for k, i in idx.items()}
            codigo = _texto(d["Código de proveedor"])
            fila = {
                "fila": n, "codigo": codigo,
                "nombre": _texto(d["Nombre"]), "marca": _texto(d["Marca"]),
                "presentacion": _texto(d["Presentación"]),
                "cantidad": _decimal(d["Cantidad"]), "costo": _decimal(d["Costo unitario"]),
                "precio": _decimal(d["Precio de venta"]), "bonificadas": _decimal(d["Bonificadas"]),
                "categoria_txt": _texto(d["Categoría"]), "mascota_txt": _texto(d["Mascota"]),
            }
            if not codigo:
                errores.append(f"Fila {n}: sin código de proveedor.")
            elif codigo in vistos:
                errores.append(f"Fila {n}: el código {codigo} está repetido.")
            vistos.add(codigo)
            if fila["cantidad"] < 0 or fila["bonificadas"] < 0 or fila["costo"] < 0:
                errores.append(f"Fila {n} ({codigo}): hay un número negativo.")
            if fila["cantidad"] + fila["bonificadas"] <= 0:
                errores.append(f"Fila {n} ({codigo}): no trae unidades ni facturadas ni bonificadas.")
            if fila["precio"] <= 0:
                errores.append(f"Fila {n} ({codigo}): falta el precio de venta.")
            if fila["cantidad"] > 0 and fila["costo"] <= 0:
                errores.append(f"Fila {n} ({codigo}): tiene unidades facturadas pero costo 0.")
            fila["categoria"] = buscar_categoria(CATEGORIAS.get(fila["categoria_txt"].lower(), fila["categoria_txt"]))
            if fila["categoria_txt"] and fila["categoria"] is None:
                errores.append(f"Fila {n} ({codigo}): la categoría «{fila['categoria_txt']}» no existe en el ERP.")
            fila["mascota"] = normalizar_mascota(fila["mascota_txt"]) or ""
            if fila["mascota_txt"] and not fila["mascota"]:
                errores.append(f"Fila {n} ({codigo}): mascota «{fila['mascota_txt']}» no válida.")
            fila["nombre_venta"] = nombre_de_venta(fila["nombre"], fila["marca"], fila["presentacion"])
            datos.append(fila)

        nombres = {}
        for fila in datos:
            nombres.setdefault(fila["nombre_venta"].lower(), []).append(fila["codigo"])
        for nombre, codigos in nombres.items():
            if len(codigos) > 1:
                errores.append(f"Dos productos quedarían con el mismo nombre ({', '.join(codigos)}): {nombre}")
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
        # Las líneas que son solo regalo necesitan la migración 0006 de
        # compras. Si la base del servidor todavía no la tiene (no se publicó
        # el cambio), se avisa en castellano en vez de reventar a mitad.
        from django.db import connection
        from django.db.migrations.recorder import MigrationRecorder

        if ("compras", "0006_linea_solo_bonificada") not in MigrationRecorder(connection).applied_migrations():
            raise CommandError("El servidor todavía no tiene la actualización que acepta productos de regalo.\n"
                               "  Primero doble clic en SUBIR_CAMBIOS.bat, esperá 5 minutos y volvé a intentar.")
        datos = self._leer(op["excel"])
        fotos = self._fotos(op["fotos"])
        empresa = Empresa.objects.first()
        sucursal = Sucursal.objects.filter(empresa=empresa).order_by("id").first()
        if empresa is None or sucursal is None:
            raise CommandError("No hay empresa o sucursal configurada.")

        r = {"nuevos": 0, "existentes": 0, "fotos": 0, "sin_foto": [], "regalo": []}
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
                        categoria=f["categoria"], categoria_original=f["categoria_txt"][:120],
                    )
                    codigo = siguiente_interno(usados)
                    usados.add(codigo)
                    producto.codigo_barras = codigo
                    propuesta = cabys.proponer(producto)
                    campos = ["codigo_barras"]
                    if propuesta:
                        producto.cabys = propuesta.codigo
                        campos.append("cabys")
                    producto.save(update_fields=campos)
                    r["nuevos"] += 1
                else:
                    r["existentes"] += 1

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

                if f["cantidad"] == 0:
                    r["regalo"].append(f"{f['bonificadas']:g} × {f['nombre_venta']}")
                lineas.append({"producto": producto, "cantidad": f["cantidad"],
                               "cantidad_bonificada": f["bonificadas"], "costo_unitario": f["costo"]})

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
        facturadas = sum(f["cantidad"] for f in datos)
        bonificadas = sum(f["bonificadas"] for f in datos)
        w("")
        w(f"  Productos en la hoja ....... {len(datos)}  (nuevos {r['nuevos']}, ya existían {r['existentes']})")
        w(f"  Unidades que entran ........ {facturadas + bonificadas:g}  "
          f"(facturadas {facturadas:g} + de regalo {bonificadas:g})")
        w(f"  Compra ..................... {compra.numero} — factura {compra.factura_proveedor} — "
          f"{compra.get_forma_pago_display()}")
        w(f"  Subtotal sin IVA ........... ₡{compra.total:,.2f}")
        w(f"  IVA 13 % ................... ₡{compra.iva:,.2f}")
        w(self.style.SUCCESS(f"  TOTAL DE LA FACTURA ........ ₡{compra.total + compra.iva:,.2f}"
                             "   <- comparalo con el papel de Belina"))
        w(f"  Fotos asociadas ............ {r['fotos']}")
        if r["regalo"]:
            w(f"\n  Productos que vinieron SOLO de regalo (entran a costo cero): {len(r['regalo'])}")
            for linea in r["regalo"]:
                w(f"    {linea}")
        if r["sin_foto"]:
            w(self.style.WARNING(f"\n  Sin foto en la carpeta: {len(r['sin_foto'])}"))
            for linea in r["sin_foto"]:
                w(f"    {linea}")
        if seco:
            w(self.style.WARNING("\n  SIMULACIÓN: no se guardó nada.\n"))
        else:
            w(self.style.SUCCESS("\n  LISTO: guardado.\n"))
