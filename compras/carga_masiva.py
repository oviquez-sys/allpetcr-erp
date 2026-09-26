"""Carga masiva de mercadería desde Excel o CSV (auditoría 26/09/2026, INV-01).

POR QUÉ EXISTE
--------------
Hay mucha mercadería por ingresar y hasta hoy la única forma de cargar una
factura grande era un comando técnico (`cargar_compra_19_09`) que se corre
con un `.bat` y la contraseña de la base. Esta pantalla hace lo mismo desde
el navegador —también desde el celular— y con las mismas garantías:

1. **Nada se guarda al subir el archivo.** Primero se muestra cada fila:
   producto nuevo o existente, cantidad, costo, precio, y los errores.
2. **Con un solo error no se puede confirmar.** Se corrige el Excel y se
   vuelve a subir. Cargar "lo que sí sirve" deja la factura a medias y
   después nadie sabe qué faltó.
3. **Al confirmar entra todo junto o nada**: productos nuevos, la compra, el
   inventario, el costo promedio, el asiento y los precios nuevos, en una
   sola transacción.
4. **Lo que se confirma es exactamente lo que se vio**: la vista previa viaja
   firmada (igual que en «Completar catálogo»), así que no se puede alterar
   entre la revisión y la confirmación.

CÓMO SE RECONOCE UN PRODUCTO
----------------------------
Por el código de barras si la fila lo trae (el de fábrica o el interno); si
no, por el nombre exacto (sin mayúsculas ni tildes). Si no aparece, es un
producto NUEVO y entonces el nombre y el precio de venta son obligatorios.
Un nombre que coincide con dos productos distintos es un error: adivinar
cuál es ingresaría mercadería al producto equivocado.
"""
import csv
import io
import unicodedata
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from catalogo.completar import MASCOTAS, buscar_categoria, normalizar_mascota
from catalogo.models import Producto
from catalogo.services import cambiar_precio

from . import services

# Columnas de la plantilla, en orden. Las obligatorias van primero.
COLUMNAS = [
    ("codigo_barras", "Código de barras", "El de fábrica. Vacío si no tiene: el ERP le da uno interno."),
    ("nombre", "Nombre", "Obligatorio si el producto es nuevo."),
    ("cantidad", "Cantidad", "Unidades FACTURADAS. Obligatorio."),
    ("costo_unitario", "Costo unitario", "Costo de cada unidad, sin IVA si la factura lo trae aparte. Obligatorio."),
    ("precio_venta", "Precio de venta", "Con IVA incluido. Obligatorio si es nuevo; si es existente y cambia, se actualiza."),
    ("bonificadas", "Bonificadas", "Unidades de regalo del proveedor (el 1 del 12+1). Opcional."),
    ("marca", "Marca", "Opcional."),
    ("categoria", "Categoría", "Opcional. Como aparece en el ERP, ej. «Juguetes › Pelotas»."),
    ("presentacion", "Presentación", "Opcional, ej. «Talla M» o «15 kg»."),
    ("mascota", "Mascota", f"Opcional: {', '.join(MASCOTAS)}."),
]
MAX_FILAS = 1000


def _plano(texto) -> str:
    texto = " ".join(str(texto or "").split()).lower()
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


# Encabezados que la gente escribe de verdad → campo.
_ALIAS = {_plano(etiqueta): clave for clave, etiqueta, _ in COLUMNAS}
_ALIAS.update({_plano(k): v for k, v in {
    "codigo": "codigo_barras", "código": "codigo_barras", "ean": "codigo_barras", "barras": "codigo_barras",
    "producto": "nombre", "descripcion": "nombre", "cant": "cantidad", "unidades": "cantidad",
    "costo": "costo_unitario", "precio": "precio_venta", "precio venta": "precio_venta",
    "bonificacion": "bonificadas", "regalo": "bonificadas", "especie": "mascota",
}.items()})


@dataclass
class Fila:
    numero: int
    codigo_barras: str = ""
    nombre: str = ""
    cantidad: str = "0"
    costo_unitario: str = "0"
    precio_venta: str = ""
    bonificadas: str = "0"
    marca: str = ""
    categoria_id: int | None = None
    categoria_txt: str = ""
    presentacion: str = ""
    mascota: str = ""
    producto_id: int | None = None
    precio_actual: str = ""
    errores: list = field(default_factory=list)

    @property
    def nuevo(self):
        return self.producto_id is None

    @property
    def cambia_precio(self):
        return bool(self.precio_venta) and not self.nuevo and Decimal(self.precio_venta) != Decimal(self.precio_actual)

    @property
    def total(self):
        try:
            return Decimal(self.cantidad) * Decimal(self.costo_unitario)
        except InvalidOperation:
            return Decimal("0")


@dataclass
class Revision:
    filas: list = field(default_factory=list)
    errores_generales: list = field(default_factory=list)

    @property
    def con_errores(self):
        return [f for f in self.filas if f.errores]

    @property
    def valida(self):
        return bool(self.filas) and not self.con_errores and not self.errores_generales

    @property
    def total(self):
        return sum((f.total for f in self.filas), Decimal("0"))

    @property
    def nuevos(self):
        return sum(1 for f in self.filas if f.nuevo)


def plantilla_excel() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Mercadería"
    ws.append([etiqueta for _, etiqueta, _ in COLUMNAS])
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="0B3161")
    ws.append(["7501234567895", "Ejemplo: Arnés acolchado talla M (borre esta fila)", 12, 2500, 6900, 1,
               "Marca X", "Paseo › Arneses", "Talla M", "Perro"])
    for i, ancho in enumerate([18, 42, 10, 14, 15, 12, 16, 26, 16, 14], start=1):
        ws.column_dimensions[chr(64 + i)].width = ancho
    ayuda = wb.create_sheet("Instrucciones")
    ayuda.append(["Columna", "Qué va"])
    for _, etiqueta, texto in COLUMNAS:
        ayuda.append([etiqueta, texto])
    ayuda.column_dimensions["A"].width = 20
    ayuda.column_dimensions["B"].width = 90
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _leer_filas(archivo):
    """Devuelve (encabezado, filas) de un .xlsx o un .csv."""
    nombre = (getattr(archivo, "name", "") or "").lower()
    if nombre.endswith(".csv"):
        texto = archivo.read().decode("utf-8-sig", errors="replace")
        dialecto = csv.Sniffer().sniff(texto[:2000], delimiters=",;\t") if texto.strip() else csv.excel
        filas = list(csv.reader(io.StringIO(texto), dialecto))
    else:
        from openpyxl import load_workbook

        wb = load_workbook(archivo, read_only=True, data_only=True)
        filas = [list(f) for f in wb.worksheets[0].iter_rows(values_only=True)]
    if not filas:
        return [], []
    return filas[0], filas[1:]


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def _numero(valor):
    """Número de lo que escriba la gente: «2.500», «2500,50», «₡2 500». None si no es número."""
    texto = _texto(valor).replace("₡", "").replace("¢", "").replace(" ", "")
    if not texto:
        return Decimal("0")
    if "," in texto and "." in texto:          # 2.500,50 → 2500.50
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:                          # 2500,50 → 2500.50
        texto = texto.replace(",", ".")
    elif texto.count(".") == 1 and len(texto.split(".")[1]) == 3:
        texto = texto.replace(".", "")          # 2.500 (miles) → 2500
    try:
        return Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def revisar(empresa, archivo) -> Revision:
    """Lee el archivo y arma la vista previa. NO guarda nada."""
    rev = Revision()
    try:
        encabezado, crudas = _leer_filas(archivo)
    except Exception:  # noqa: BLE001 — cualquier archivo ilegible es el mismo error para el usuario
        rev.errores_generales.append("No se pudo leer el archivo. Use la plantilla (.xlsx) o un .csv.")
        return rev
    columnas = {}
    for i, titulo in enumerate(encabezado):
        clave = _ALIAS.get(_plano(titulo))
        if clave and clave not in columnas:
            columnas[clave] = i
    faltan = [et for c, et, _ in COLUMNAS[:4] if c not in columnas and c != "codigo_barras" and c != "nombre"]
    if "codigo_barras" not in columnas and "nombre" not in columnas:
        faltan.insert(0, "Código de barras o Nombre")
    if faltan:
        rev.errores_generales.append(f"Faltan columnas: {', '.join(faltan)}. Descargue la plantilla.")
        return rev

    productos = list(Producto.objects.filter(empresa=empresa, activo=True))
    por_codigo = {p.codigo_barras: p for p in productos if p.codigo_barras}
    por_sku = {p.sku: p for p in productos}
    por_nombre = {}
    for p in productos:
        por_nombre.setdefault(_plano(p.nombre), []).append(p)
    codigos_vistos = {}

    for n, cruda in enumerate(crudas, start=2):
        def celda(clave):
            i = columnas.get(clave)
            return _texto(cruda[i]) if i is not None and i < len(cruda) else ""

        if not any(_texto(v) for v in cruda):
            continue
        if len(rev.filas) >= MAX_FILAS:
            rev.errores_generales.append(f"El archivo pasa de {MAX_FILAS} filas: divídalo en dos.")
            break
        f = Fila(numero=n, codigo_barras=celda("codigo_barras"), nombre=celda("nombre")[:200],
                 marca=celda("marca")[:80], presentacion=celda("presentacion")[:120])
        if f.nombre.lower().startswith("ejemplo:"):
            continue   # la fila de ejemplo de la plantilla

        for clave in ("cantidad", "costo_unitario", "precio_venta", "bonificadas"):
            valor = _numero(celda(clave))
            if valor is None:
                f.errores.append(f"«{celda(clave)}» no es un número ({clave.replace('_', ' ')}).")
                valor = Decimal("0")
            setattr(f, clave, str(valor) if (clave != "precio_venta" or valor > 0) else "")
        # 0 facturadas vale si la fila trae bonificadas: regalo del proveedor.
        if Decimal(f.cantidad) < 0 or (Decimal(f.cantidad) == 0 and Decimal(f.bonificadas) <= 0):
            f.errores.append("La cantidad tiene que ser mayor que cero (o la fila tiene que traer bonificadas).")
        if Decimal(f.costo_unitario) < 0:
            f.errores.append("El costo no puede ser negativo.")
        if Decimal(f.bonificadas) < 0:
            f.errores.append("Las bonificadas no pueden ser negativas.")

        # ¿Qué producto es?
        producto = None
        if f.codigo_barras:
            producto = por_codigo.get(f.codigo_barras) or por_sku.get(f.codigo_barras)
            if f.codigo_barras in codigos_vistos:
                f.errores.append(f"El código {f.codigo_barras} ya viene en la fila {codigos_vistos[f.codigo_barras]}: "
                                 "sume las cantidades en una sola fila.")
            codigos_vistos[f.codigo_barras] = n
        if producto is None and f.nombre and not f.codigo_barras:
            candidatos = por_nombre.get(_plano(f.nombre), [])
            if len(candidatos) > 1:
                f.errores.append(f"Hay {len(candidatos)} productos que se llaman «{f.nombre}»: "
                                 "ponga el código de barras para saber cuál es.")
            elif candidatos:
                producto = candidatos[0]
        if producto is not None:
            f.producto_id = producto.id
            f.nombre = producto.nombre
            f.precio_actual = str(producto.precio_venta)
        else:
            if not f.nombre:
                f.errores.append("No existe un producto con ese código: para crearlo escriba el nombre.")
            if not f.precio_venta:
                f.errores.append("Producto nuevo: falta el precio de venta.")

        if celda("categoria"):
            cat = buscar_categoria(celda("categoria"))
            if cat is None:
                f.errores.append(f"La categoría «{celda('categoria')}» no existe en el ERP.")
            else:
                f.categoria_id, f.categoria_txt = cat.id, str(cat)
        if celda("mascota"):
            f.mascota = normalizar_mascota(celda("mascota")) or ""
            if not f.mascota:
                f.errores.append(f"Mascota «{celda('mascota')}» no válida. Opciones: {', '.join(MASCOTAS)}.")
        rev.filas.append(f)

    if not rev.filas and not rev.errores_generales:
        rev.errores_generales.append("El archivo no trae ninguna fila con mercadería.")
    return rev


def a_datos(rev: Revision) -> list[dict]:
    return [asdict(f) for f in rev.filas]


@transaction.atomic
def aplicar(*, empresa, filas: list[dict], proveedor, sucursal, forma_pago, factura_proveedor, iva, usuario):
    """Crea los productos nuevos, registra y recibe la compra, y cambia los
    precios. Todo o nada. Devuelve la compra."""
    lineas, precios = [], []
    for datos in filas:
        f = Fila(**{k: v for k, v in datos.items() if k in Fila.__dataclass_fields__})
        if f.producto_id:
            producto = Producto.objects.get(pk=f.producto_id, empresa=empresa)
            if f.cambia_precio:
                precios.append((producto, Decimal(f.precio_venta)))
            campos = []
            for campo in ("marca", "presentacion", "mascota"):
                if getattr(f, campo) and not getattr(producto, campo):
                    setattr(producto, campo, getattr(f, campo))
                    campos.append(campo)
            if f.categoria_id and not producto.categoria_id:
                producto.categoria_id = f.categoria_id
                campos.append("categoria")
            if campos:   # solo completa lo vacío: nunca pisa datos puestos a mano
                producto.save(update_fields=campos + ["actualizado_en"])
        else:
            if f.codigo_barras and Producto.objects.filter(codigo_barras=f.codigo_barras).exists():
                raise ValidationError(f"Fila {f.numero}: el código {f.codigo_barras} ya existe.")
            from .views import _generar_sku
            producto = Producto.objects.create(
                empresa=empresa, sku=_generar_sku(), nombre=f.nombre, codigo_barras=f.codigo_barras,
                precio_venta=Decimal(f.precio_venta), marca=f.marca, presentacion=f.presentacion,
                mascota=f.mascota, categoria_id=f.categoria_id,
            )
        lineas.append({"producto": producto, "cantidad": Decimal(f.cantidad),
                       "cantidad_bonificada": Decimal(f.bonificadas), "costo_unitario": Decimal(f.costo_unitario)})
    compra = services.crear_y_recibir_compra(
        proveedor=proveedor, sucursal=sucursal, lineas=lineas, forma_pago=forma_pago,
        factura_proveedor=factura_proveedor, usuario=usuario, iva=iva,
    )
    for producto, precio in precios:
        cambiar_precio(producto=producto, nuevo_precio=precio, usuario=usuario,
                       motivo=f"Carga masiva {compra.numero}")
    return compra
