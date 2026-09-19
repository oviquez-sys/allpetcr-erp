"""Carga al catálogo la compra grande de setiembre 2026 (factura del 19/09).

Uso:
    python manage.py cargar_compra_19_09 --dry-run     # ver qué haría
    python manage.py cargar_compra_19_09               # aplicarlo

Por qué existe (y por qué NO se reusó `sincronizar_inventario`)
------------------------------------------------------------------
El Excel de esta compra (`data/PRECIOS_AllPetCR.xlsx`, hoja "Precios") no es
el inventario completo: son 300 líneas de UNA factura, con columnas propias
armadas para decidir el precio (costo, margen de categoría, tope por tramo de
costo, precio sugerido) que `sincronizar_inventario` no conoce y que no hay
que confundir con "Categoría web / Subcategoría".

Ese Excel ya trae, por fila, un diagnóstico hecho a mano contra el catálogo:
la columna "Estado" dice si el producto YA EN EL ERP (186), es NUEVO (80) o
VUELVE (34, un código que se había borrado el 09/09/2026 por no tener
existencia — ver PRODUCTOS_SIN_EXISTENCIA.xlsx). Este comando usa esa pista,
pero la vuelve a comprobar contra la base: lo que manda es si el SKU existe
de verdad, no el texto de la columna. Así el comando queda idempotente —
correrlo dos veces no revive un error de la primera pasada.

Reglas del proyecto que este comando respeta (no son opcionales)
------------------------------------------------------------------
- **El árbol de categorías se verifica contra la BASE, nunca contra el
  Excel** (lección de `arbol-de-categorias.md`, 01/09/2026). La columna
  "Categoría" de este Excel es una agrupación PARA CALCULAR EL MARGEN, no la
  categoría del sitio — tiene 12 valores como "Equipos electrónicos y
  muebles" que no existen en el árbol oficial. Este comando la traduce a una
  de las 16 raíces oficiales (`_MAPA_CATEGORIA`, con casos especiales por SKU
  donde una sola bolsa no alcanza) y NUNCA crea una raíz nueva: si la raíz
  esperada no existe en la base, es un error y se detiene, no se inventa.
- **Las existencias entran como COMPRA de verdad, no a mano** (con
  `--con-existencias`). El comando arma una `Compra` con una línea por
  cada línea de la factura y la RECIBE con `compras.services`: de ahí
  salen el movimiento de kardex (tipo COM), el recálculo del
  `costo_promedio` y el asiento contable —Debe Inventario / Haber Bancos
  o CxP—. O sea: lo mismo que haría Compras › Recibir mercadería a mano,
  pero con 300 líneas en una sola pasada.

  Por qué así y no escribiendo el stock directo: el kardex es la única
  fuente de verdad del inventario (regla del proyecto), y una compra deja
  además el documento con el número de factura del proveedor, la deuda o
  el pago, y su asiento. Y sobre todo: **se puede reversar de un solo
  golpe** con `anular_compra` si algo salió mal, cosa que un stock
  escrito a mano no permite.

  Ojo con el verbo: recibir una compra SUMA. No iguala. Para que cargarla
  dos veces no duplique existencias, el comando se niega a seguir si ya
  hay una compra con el mismo número de factura.

- **`--igualar-al-excel` hace que manden las cantidades del Excel**, no las
  que ya tenía el sistema (decisión de Oscar, 18/09/2026). Antes de recibir
  la factura, la existencia que el sistema traía de esos productos se baja a
  cero con un ajuste (AJU) con motivo, y después entra la factura completa.
  El resultado: existencia = lo que dice el Excel, y costo promedio = el
  costo de esta factura, sin arrastre del costo viejo.

  Se hace en ese orden a propósito. Ajustar DESPUÉS dejaría el costo
  promedio mezclado con el del stock viejo (una salida no recalcula costo,
  regla de `inventario.services`), y haría que la compra ya no calce con la
  factura del proveedor. Así el documento de compra queda igual al papel y
  el kardex cuenta la verdad en dos pasos: "esto que el sistema creía tener
  no está" y "esto es lo que entró".

  **Solo vale antes de abrir la tienda.** Si hay una venta emitida, el
  comando se niega: a partir de la primera venta el conteo se corrige con un
  ajuste de inventario físico, nunca igualando a una hoja de cálculo, porque
  la hoja no sabe lo que se vendió.

  La salida de emergencia es `--ignorar-ventas FV-00000036 [...]`: hay que
  NOMBRAR una por una las ventas que no movieron mercadería de verdad (las
  pruebas del punto de venta). Se diseñó así a propósito, en vez de un
  `--forzar` que apague el guardia entero: si mañana aparece una venta que no
  está en esa lista, el comando se vuelve a plantar. Una lista explícita no
  se pudre sola; un "forzar" sí.
- **El costo lo pone la compra, no el Excel.** `costo_promedio` se
  recalcula solo, por el kardex, con el costo de la factura.
- **El precio se cambia por `catalogo.services.cambiar_precio`.**
- **Un producto que YA estaba en el ERP conserva su categoría, su mascota y
  su descripción** si el Excel trae esos campos vacíos: no se borra un dato
  bueno con un blanco. Solo se completan si el producto no tenía nada
  todavía (por ejemplo, categoría nula).
- **Los "VUELVE" intentan recuperar su categoría y mascota de antes del
  borrado** (`PRODUCTOS_SIN_EXISTENCIA.xlsx`, que guarda una foto del
  catálogo justo antes de borrarlo). Si esa categoría ya no existe en la
  base, se usa el mapeo por defecto en vez de fallar.
"""
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Categoria, Producto
from catalogo.services import cambiar_precio
from compras.models import Compra, Proveedor
from compras.services import crear_compra, recibir_compra
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta

ARCHIVO_POR_DEFECTO = "data/PRECIOS_AllPetCR.xlsx"
HOJA_POR_DEFECTO = "Precios"
ARCHIVO_BAJAS_POR_DEFECTO = "PRODUCTOS_SIN_EXISTENCIA.xlsx"

# Encabezados que tiene que tener la hoja "Precios". Se busca por NOMBRE, no
# por posición: si alguien reordena columnas el comando lee igual, y si falta
# alguna de estas, se detiene con un mensaje claro en vez de leer cualquier
# cosa en el campo equivocado.
COLUMNAS_REQUERIDAS = [
    "Código", "Estado", "Código de barras", "Nombre", "Categoría", "Mascota",
    "Descripción", "Cant.", "Costo", "PRECIO SUGERIDO",
]

# La columna "Categoría" de este Excel agrupa por margen, no por navegación
# del sitio. Se traduce a una de las 16 raíces oficiales del árbol
# (`catalogo/management/commands/asegurar_categorias.py::ARBOL`).
_MAPA_CATEGORIA = {
    "Juguetes": "Juguetes",
    "Juguetes eléctricos": "Juguetes",
    "Accesorios de paseo": "Paseo",
    "Aseo y grooming": "Higiene y aseo",
    "Ropa y accesorios de moda": "Ropa y accesorios",
    "Comederos y bebederos": "Comederos y bebederos",
    "Salud y cuidado": "Salud y cuidado",
    "Transporte y viaje": "Transporte",
}

# Casos donde el nombre del producto decide mejor que el balde de precio:
# "Descanso y rascadores", "Higiene y desechables", "Equipos electrónicos y
# muebles" y "Otros" mezclan productos que van a raíces distintas del árbol.
# Decidido a mano el 18/09/2026 mirando el nombre de cada uno de los 37 SKU
# de esos cuatro baldes (ver conversación). `None` = no se pudo decidir sin
# ver el producto: se deja sin categoría y se reporta para que Oscar la
# asigne él.
_CATEGORIA_POR_SKU = {
    # Descanso y rascadores (16)
    "85523": "Rascadores y muebles",  # Hamaca para ventana para gatos
    "55802": "Descanso",              # Cama rectangular
    "55801": "Descanso",              # Cama rectangular
    "87223": "Rascadores y muebles",  # Arco (rascador)
    "89062": "Rascadores y muebles",  # Rascador cartón
    "89063": "Rascadores y muebles",  # Rascador cartón
    "87035": "Rascadores y muebles",  # Rascador cartón
    "83214": "Descanso",              # Casa carpa / tienda de campaña
    "77149": "Descanso",              # Cama redonda
    "79197": "Descanso",              # Manta refrescante
    "79205": "Descanso",              # Alfombrilla / cama de hielo
    "87179": "Rascadores y muebles",  # Rascador cartón
    "87177": "Rascadores y muebles",  # Rascador cartón
    "74273": "Descanso",              # Manta refrescante
    "87174": "Rascadores y muebles",  # Rascador cartón
    "00059": "Descanso",              # Manta
    # Higiene y desechables (15)
    "79190": "Higiene y aseo",        # Sabanillas para perros
    "85376": "Arena y sanitarios",    # Alfombra para arena de gato
    "79073": "Higiene y aseo",        # Pañal para perros
    "61403": "Higiene y aseo",        # Pañal para perros
    "88062": "Higiene y aseo",        # Bolsas para desechos
    "85433": "Higiene y aseo",        # Dispensador y bolsas para desechos
    "85434": "Higiene y aseo",        # Dispensador y bolsas para desechos
    "85432": "Higiene y aseo",        # Dispensador y bolsas para desechos
    "pv2602": "Higiene y aseo",       # Toallita húmeda
    "pv2603": "Higiene y aseo",       # Toallita húmeda
    "88015": "Higiene y aseo",        # Toallitas
    "79441": "Arena y sanitarios",    # Arenero para gato
    "82740": "Arena y sanitarios",    # Pala arena
    "75564": "Higiene y aseo",        # Dispensador bolsas (mochila)
    "88063": "Higiene y aseo",        # Dispensador bolsas
    # Equipos electrónicos y muebles (5)
    "85490": "Rascadores y muebles",  # Casa para mascotas
    "79534": "Comederos y bebederos",  # Fuente de agua
    "86955": None,                    # Lámpara solar — no encaja, revisar a mano
    "87289": "Comederos y bebederos",  # Fuente de agua
    "87153": "Comederos y bebederos",  # Comedero automático
    # Otros (1)
    "00065": None,                    # "Botón — intercambio de grabaciones": revisar a mano
}


def _texto(valor, limite=None):
    s = "" if valor is None else str(valor).strip()
    return s[:limite] if limite else s


def _decimal(valor):
    if valor in (None, ""):
        return Decimal("0")
    return Decimal(str(valor)).quantize(Decimal("0.01"))


class Command(BaseCommand):
    help = "Carga al catálogo la compra de setiembre 2026 (factura 19/09), sin tocar stock."

    def add_arguments(self, parser):
        parser.add_argument("--archivo", default=ARCHIVO_POR_DEFECTO)
        parser.add_argument("--hoja", default=HOJA_POR_DEFECTO)
        parser.add_argument("--archivo-bajas", default=ARCHIVO_BAJAS_POR_DEFECTO)
        parser.add_argument("--dry-run", action="store_true",
                             help="No escribe nada: muestra exactamente qué haría.")
        parser.add_argument("--usuario", default=None,
                             help="Username que queda firmando los cambios de precio.")
        parser.add_argument(
            "--con-existencias", action="store_true",
            help="Además del catálogo, mete la mercadería al inventario como una COMPRA "
                 "recibida (kardex + costo promedio + asiento contable). Sin esta "
                 "bandera solo se carga el catálogo y las existencias quedan en cero.",
        )
        parser.add_argument(
            "--igualar-al-excel", action="store_true",
            help="Manda la cantidad del Excel: la existencia que el sistema ya tenía de "
                 "estos productos se baja a cero con un ajuste ANTES de recibir la "
                 "factura, así queda exactamente lo que dice la hoja (y el costo de "
                 "esta factura, sin arrastre). Solo se permite antes de la primera venta.",
        )
        parser.add_argument(
            "--ignorar-ventas", nargs="*", default=[], metavar="NUMERO",
            help="Números de factura de venta que NO movieron mercadería de verdad "
                 "(pruebas del POS), ej. FV-00000036. Solo con --igualar-al-excel: "
                 "las ventas que no estén nombradas acá siguen bloqueando la corrida.",
        )
        parser.add_argument("--proveedor", default="BUEN AMIGO",
                             help="Proveedor de la compra. Si no existe, se crea.")
        parser.add_argument("--factura", default="19-09-2026",
                             help="N.º de factura del proveedor. Es la llave que evita "
                                  "cargar dos veces la misma mercadería.")
        parser.add_argument("--forma-pago", default="CON", choices=["CON", "CRE"],
                             help="CON = contado (sale de Bancos). CRE = crédito del "
                                  "proveedor (sube la cuenta por pagar).")

    def handle(self, *args, **op):
        seco = op["dry_run"]
        filas, encabezados = self._leer_precios(op["archivo"], op["hoja"])
        bajas = self._leer_bajas(op["archivo_bajas"])
        usuario = self._usuario(op["usuario"])
        empresa = Empresa.objects.first()
        if empresa is None:
            raise CommandError("No hay ninguna empresa configurada en la base de datos.")

        with transaction.atomic():
            r = self._cargar(filas, encabezados, bajas, usuario, empresa)
            if op["con_existencias"]:
                self._recibir_mercaderia(
                    filas, encabezados, empresa, usuario, r,
                    nombre_proveedor=op["proveedor"],
                    factura=op["factura"],
                    forma_pago=op["forma_pago"],
                    igualar=op["igualar_al_excel"],
                    ventas_de_prueba=op["ignorar_ventas"],
                )
            if seco:
                transaction.set_rollback(True)

        self._reportar(r, seco, con_existencias=op["con_existencias"])

    # ── lectura ──────────────────────────────────────────────────────────
    def _leer_precios(self, ruta, hoja):
        try:
            wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        except FileNotFoundError:
            raise CommandError(f"No se encontró el archivo: {ruta}")
        if hoja not in wb.sheetnames:
            raise CommandError(
                f"El Excel no tiene la hoja '{hoja}'. Hojas disponibles: {', '.join(wb.sheetnames)}"
            )
        ws = wb[hoja]
        todas = list(ws.iter_rows(values_only=True))
        wb.close()
        if not todas:
            raise CommandError("La hoja está vacía.")

        encabezado = [_texto(c) for c in todas[0]]
        idx = {nombre: i for i, nombre in enumerate(encabezado) if nombre}
        faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in idx]
        if faltantes:
            raise CommandError(
                "Faltan columnas que este comando necesita en la hoja "
                f"'{hoja}': {', '.join(faltantes)}.\n"
                "  Si el Excel cambió de forma, actualizá COLUMNAS_REQUERIDAS "
                "y el resto de este comando — no lo fuerces así."
            )
        filas = [f for f in todas[1:] if f and _texto(f[idx["Código"]])]
        return filas, idx

    def _leer_bajas(self, ruta):
        """SKU -> (categoría de antes del borrado, mascota de antes del borrado).

        Es opcional: si el archivo no está, los "VUELVE" simplemente usan el
        mapeo por defecto en vez de recuperar su categoría vieja.
        """
        if not ruta or not Path(ruta).is_file():
            return {}
        try:
            wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        except Exception:
            return {}
        ws = wb[wb.sheetnames[0]]
        filas = list(ws.iter_rows(values_only=True))
        wb.close()
        if not filas:
            return {}
        encabezado = [_texto(c) for c in filas[0]]
        idx = {nombre: i for i, nombre in enumerate(encabezado) if nombre}
        if "SKU" not in idx or "Categoría" not in idx:
            return {}
        resultado = {}
        for f in filas[1:]:
            if not f:
                continue
            sku = _texto(f[idx["SKU"]])
            if not sku:
                continue
            resultado[sku] = (
                _texto(f[idx["Categoría"]]),
                _texto(f[idx.get("Mascota", -1)]) if "Mascota" in idx else "",
            )
        return resultado

    def _usuario(self, username):
        if not username:
            return None
        from django.contrib.auth import get_user_model
        try:
            return get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist:
            raise CommandError(f"No existe el usuario '{username}'.")

    # ── categoría ────────────────────────────────────────────────────────
    def _resolver_categoria(self, sku, balde_precio, bajas, r):
        """Devuelve (Categoria u None, origen) para un producto NUEVO o que VUELVE.

        Nunca crea una raíz: si el nombre resuelto no existe en la base,
        es un error de configuración de este comando, no del Excel.
        """
        vieja = bajas.get(sku)
        if vieja and vieja[0]:
            cat = Categoria.objects.filter(nombre=vieja[0]).first()
            if cat:
                return cat, f"recuperada de antes del borrado ({vieja[0]})"
            r.categoria_vieja_no_encontrada.append((sku, vieja[0]))

        if sku in _CATEGORIA_POR_SKU:
            nombre = _CATEGORIA_POR_SKU[sku]
            if nombre is None:
                return None, "sin mapear a propósito — revisar a mano"
        else:
            nombre = _MAPA_CATEGORIA.get(balde_precio)
            if nombre is None:
                raise CommandError(
                    f"SKU {sku}: la categoría de precio '{balde_precio}' no tiene "
                    "mapeo a una raíz del árbol. Agregala a _MAPA_CATEGORIA o a "
                    "_CATEGORIA_POR_SKU en este comando antes de correrlo."
                )

        cat = Categoria.objects.filter(nombre=nombre).first()
        if cat is None:
            raise CommandError(
                f"SKU {sku}: se esperaba la categoría '{nombre}' y no existe en la "
                "base. Corré `manage.py asegurar_categorias` primero — este comando "
                "no crea raíces nuevas a propósito."
            )
        return cat, f"por mapeo ({balde_precio} -> {nombre})"

    # ── carga ────────────────────────────────────────────────────────────
    def _cargar(self, filas, idx, bajas, usuario, empresa):
        r = _Resultado()
        vistos = set()

        for fila in filas:
            sku = _texto(fila[idx["Código"]])
            nombre = _texto(fila[idx["Nombre"]], 200)
            if not sku or not nombre:
                r.saltados += 1
                continue
            if sku in vistos:
                r.duplicados.append(sku)
                continue
            vistos.add(sku)

            estado_excel = _texto(fila[idx["Estado"]])
            balde_precio = _texto(fila[idx["Categoría"]])
            mascota_excel = _texto(fila[idx["Mascota"]], 30)
            descripcion_excel = _texto(fila[idx["Descripción"]])
            codigo_barras = _texto(fila[idx["Código de barras"]], 30)
            costo = _decimal(fila[idx["Costo"]])
            cantidad = _decimal(fila[idx["Cant."]])
            precio = _decimal(fila[idx["PRECIO SUGERIDO"]])

            producto = Producto.objects.filter(sku=sku).first()

            if producto is not None:
                # ── actualizar: preserva lo que ya tenía si el Excel viene vacío ──
                if estado_excel == "NUEVO":
                    r.inconsistencias.append(
                        f"{sku}: el Excel dice NUEVO pero ya existe en el ERP — se actualizó en vez de crear."
                    )
                campos = []
                if nombre and producto.nombre != nombre:
                    producto.nombre = nombre
                    campos.append("nombre")
                if descripcion_excel and producto.descripcion != descripcion_excel:
                    producto.descripcion = descripcion_excel
                    campos.append("descripcion")
                if mascota_excel and producto.mascota != mascota_excel:
                    producto.mascota = mascota_excel
                    campos.append("mascota")
                if producto.categoria_id is None:
                    # Nunca tenía categoría: se le asigna en vez de dejarlo huérfano.
                    cat, origen = self._resolver_categoria(sku, balde_precio, bajas, r)
                    if cat is not None:
                        producto.categoria = cat
                        campos.append("categoria")
                        r.categoria_asignada_a_existente.append((sku, cat.nombre, origen))
                if campos:
                    producto.save(update_fields=campos + ["actualizado_en"])
                    r.actualizados += 1

                if precio > 0 and precio != producto.precio_venta:
                    try:
                        cambiar_precio(
                            producto=producto, nuevo_precio=precio, usuario=usuario,
                            motivo="Carga de la compra de setiembre 2026 (factura 19/09)",
                        )
                        r.precios.append((sku, producto.precio_venta, precio))
                    except ValidationError as e:
                        r.errores.append(f"{sku}: precio no aplicado — {'; '.join(e.messages)}")

                if costo > 0 and producto.costo_promedio > 0:
                    brecha = abs(costo - producto.costo_promedio)
                    if brecha / producto.costo_promedio > Decimal("0.01"):
                        r.costos.append((sku, producto.costo_promedio, costo))

                if not mascota_excel and not producto.mascota:
                    r.sin_mascota.append(sku)

            else:
                # ── crear: SIN stock. La cantidad se reporta para Compras ──
                if estado_excel == "YA EN EL ERP":
                    r.inconsistencias.append(
                        f"{sku}: el Excel dice YA EN EL ERP pero no existe — se creó."
                    )
                cat, origen = self._resolver_categoria(sku, balde_precio, bajas, r)
                if cat is None:
                    r.sin_categoria.append((sku, nombre))

                mascota = mascota_excel
                if not mascota and bajas.get(sku) and bajas[sku][1]:
                    mascota = bajas[sku][1][:30]
                if not mascota:
                    r.sin_mascota.append(sku)

                producto = Producto(
                    empresa=empresa,
                    sku=sku,
                    nombre=nombre,
                    categoria=cat,
                    categoria_original=balde_precio,
                    codigo_barras=codigo_barras,
                    descripcion=descripcion_excel,
                    mascota=mascota,
                    precio_venta=precio,
                )
                producto.save()
                r.creados += 1
                if estado_excel == "VUELVE":
                    r.vueltos.append(sku)
                if cantidad > 0:
                    r.pendiente_recibir.append((sku, nombre, cantidad, costo))

        return r

    # ── existencias: entran como compra recibida ─────────────────────────
    def _recibir_mercaderia(self, filas, idx, empresa, usuario, r, *,
                             nombre_proveedor, factura, forma_pago, igualar=False,
                             ventas_de_prueba=()):
        """Arma la compra con las líneas de la factura y la recibe.

        Una línea por cada línea del Excel, no por producto: la factura trae
        cuatro códigos dos veces (3 unidades a un precio y 12 al precio de
        volumen) y las dos son ciertas. Sumarlas en una sola línea con un
        costo promediado a mano sería reescribir la factura; dos líneas dejan
        el documento igual al papel y el kardex calcula el costo promedio él
        solo, que es su trabajo.
        """
        # La llave contra el doble cargo. Recibir dos veces la misma factura
        # duplicaría las existencias sin que nada fallara — es el error más
        # caro que podría cometer este comando, y el único que no se nota
        # hasta que alguien cuenta la bodega.
        ya_cargada = (
            Compra.objects.filter(empresa=empresa, factura_proveedor=factura)
            .exclude(estado=Compra.Estado.ANULADA)
            .first()
        )
        if ya_cargada:
            raise CommandError(
                f"La factura '{factura}' ya está cargada como compra "
                f"{ya_cargada.numero} ({ya_cargada.get_estado_display()}). "
                "No se vuelve a recibir: duplicaría las existencias.\n"
                "  Si de verdad es otra factura, pasale el número real con --factura."
            )

        sucursal = Sucursal.objects.filter(empresa=empresa).order_by("id").first()
        if sucursal is None:
            raise CommandError("La empresa no tiene ninguna sucursal configurada.")

        if igualar:
            # La única salvaguarda que importa acá. Antes de abrir, igualar a la
            # hoja es inofensivo: todo el stock del sistema salió de una hoja de
            # todos modos. Con una sola venta registrada deja de serlo, porque la
            # hoja no sabe lo que salió por caja y el ajuste borraría esa venta
            # del inventario sin que nada fallara.
            # Las anuladas no cuentan: su mercadería ya volvió a bodega por el
            # movimiento inverso, así que no hay nada que la hoja desconozca.
            emitidas = set(
                FacturaVenta.objects.filter(
                    empresa=empresa, estado=FacturaVenta.Estado.EMITIDA
                ).values_list("numero", flat=True)
            )
            sin_justificar = sorted(emitidas - set(ventas_de_prueba))
            if sin_justificar:
                raise CommandError(
                    f"Hay {len(sin_justificar)} venta(s) emitida(s) sin justificar: "
                    f"{', '.join(sin_justificar)}.\n"
                    "  --igualar-al-excel pone la existencia en lo que dice la hoja, y la "
                    "hoja no sabe lo que salió por caja: si esa mercadería se vendió de "
                    "verdad, el conteo quedaría inflado y no se notaría hasta contar la "
                    "bodega.\n"
                    "  Si fueron pruebas del punto de venta, nombralas:\n"
                    f"    --ignorar-ventas {' '.join(sin_justificar)}\n"
                    "  Si alguna fue una venta real, corré sin --igualar-al-excel (la "
                    "factura entra sumando) y corregí el conteo con un ajuste de "
                    "inventario físico."
                )
            r.ventas_ignoradas = sorted(emitidas & set(ventas_de_prueba))
            self._poner_en_cero(filas, idx, sucursal, usuario, r, factura)

        proveedor = Proveedor.objects.filter(
            empresa=empresa, nombre__iexact=nombre_proveedor
        ).first()
        if proveedor is None:
            proveedor = Proveedor.objects.create(empresa=empresa, nombre=nombre_proveedor)
            r.proveedor_creado = True
        r.proveedor = proveedor.nombre

        lineas = []
        for fila in filas:
            sku = _texto(fila[idx["Código"]])
            cantidad = _decimal(fila[idx["Cant."]])
            costo = _decimal(fila[idx["Costo"]])
            if not sku or cantidad <= 0:
                continue
            producto = Producto.objects.filter(sku=sku).first()
            if producto is None:
                # No debería pasar: el paso anterior los crea todos. Si pasa,
                # se reporta y la mercadería de esa línea NO entra, en vez de
                # que la compra quede sin una línea sin que nadie lo sepa.
                r.errores.append(f"{sku}: no se pudo recibir mercadería, el producto no existe.")
                continue
            lineas.append({"producto": producto, "cantidad": cantidad, "costo_unitario": costo})

        if not lineas:
            r.errores.append("No había ninguna línea con cantidad para recibir.")
            return

        compra = crear_compra(
            proveedor=proveedor, sucursal=sucursal, lineas=lineas,
            forma_pago=forma_pago, factura_proveedor=factura, usuario=usuario,
        )
        recibir_compra(compra=compra, usuario=usuario)

        r.compra_numero = compra.numero
        r.compra_total = compra.total
        r.compra_lineas = len(lineas)
        r.compra_unidades = sum(l["cantidad"] for l in lineas)
        r.compra_forma_pago = compra.get_forma_pago_display()
        r.compra_factura = factura

    def _poner_en_cero(self, filas, idx, sucursal, usuario, r, factura):
        """Baja a cero la existencia que el sistema traía de estos productos.

        Un ajuste (AJU) por producto, con motivo, ANTES de recibir la factura.
        No se escribe `stock_actual` a mano ni de milagro: pasa por el kardex
        como todo lo demás, así queda el rastro de qué creía tener el sistema
        y se puede revertir mirando el movimiento.
        """
        bodega = Bodega.principal_de(sucursal)
        if bodega is None:
            raise CommandError("La sucursal no tiene bodega configurada.")

        skus = {_texto(f[idx["Código"]]) for f in filas if _texto(f[idx["Código"]])}
        con_existencia = Producto.objects.filter(sku__in=skus, stock_actual__gt=0)
        for producto in con_existencia:
            habia = producto.stock_actual
            try:
                registrar_movimiento(
                    producto=producto, bodega=bodega, tipo="AJU",
                    cantidad=-habia,
                    referencia=f"IGUALAR-{factura}",
                    motivo=("Conteo antes de abrir: manda el Excel de la compra. "
                            f"El sistema traía {habia:g} y se pone en cero para que "
                            "quede solo lo que entra por esta factura."),
                    usuario=usuario,
                )
                r.puestos_en_cero.append((producto.sku, producto.nombre, habia))
            except ValidationError as e:
                r.errores.append(f"{producto.sku}: no se pudo poner en cero — {'; '.join(e.messages)}")

    # ── reporte ──────────────────────────────────────────────────────────
    def _reportar(self, r, seco, con_existencias=False):
        w = self.stdout.write
        titulo = "SIMULACIÓN (no se escribió nada)" if seco else "Carga aplicada"
        w(self.style.SUCCESS(f"\n{titulo}"))
        w(f"  Productos creados ........ {r.creados}  (de los cuales {len(r.vueltos)} son 'VUELVE')")
        w(f"  Productos actualizados ... {r.actualizados}")
        w(f"  Precios cambiados ........ {len(r.precios)}")
        w(f"  Categoría asignada a productos que no tenían ... {len(r.categoria_asignada_a_existente)}")

        if r.ventas_ignoradas:
            w(self.style.WARNING(
                f"\n  Se dio por hecho que {len(r.ventas_ignoradas)} venta(s) emitida(s) NO "
                f"movieron mercadería real: {', '.join(r.ventas_ignoradas)}."
            ))
            w("  Siguen en la contabilidad. Para sacarlas de los libros hay que anularlas")
            w("  desde el ERP (Ventas > la factura > Anular), no desde acá.")

        if r.puestos_en_cero:
            unidades = sum(u for _, _, u in r.puestos_en_cero)
            w(self.style.WARNING(
                f"\n  {len(r.puestos_en_cero)} producto(s) traían existencia en el sistema "
                f"({unidades:g} unidades) y se pusieron en CERO antes de recibir la factura,"
            ))
            w("  porque manda la cantidad del Excel. Quedó el ajuste en el kardex con su motivo:")
            for sku, nombre, habia in r.puestos_en_cero[:10]:
                w(f"    {sku} — {nombre}: el sistema traía {habia:g}")
            if len(r.puestos_en_cero) > 10:
                w(f"    … y {len(r.puestos_en_cero) - 10} más.")

        if con_existencias and r.compra_numero:
            w(self.style.SUCCESS(f"\n  MERCADERÍA RECIBIDA — compra {r.compra_numero}"))
            w(f"    Proveedor ........... {r.proveedor}"
              + ("  (se creó ahora)" if r.proveedor_creado else "  (ya existía)"))
            w(f"    Factura ............. {r.compra_factura}")
            w(f"    Forma de pago ....... {r.compra_forma_pago}")
            w(f"    Líneas .............. {r.compra_lineas}")
            w(f"    Unidades a bodega ... {r.compra_unidades:,.0f}")
            w(f"    Total de la compra .. ₡{r.compra_total:,.2f}")
            w(self.style.WARNING(
                "    ^ COMPARÁ ESE TOTAL CON LA FACTURA DEL PROVEEDOR antes de aplicar.\n"
                "      Es el número que va a quedar en la contabilidad y en el costo de\n"
                "      cada producto. Si no cuadra, el Excel no cuadra con el papel."
            ))
            w("    El costo promedio de cada producto lo recalculó el kardex con ese costo.")
        elif con_existencias:
            w(self.style.ERROR("\n  La mercadería NO entró. Revisá los errores de abajo."))
        elif r.pendiente_recibir:
            w(self.style.WARNING(
                f"\n  {len(r.pendiente_recibir)} producto(s) nuevo(s) quedaron con stock 0: "
                "esta corrida fue solo de catálogo (sin --con-existencias)."
            ))
            for sku, nombre, cant, costo in r.pendiente_recibir[:10]:
                w(f"    {sku} — {nombre}: la factura dice {cant} a ₡{costo:,.2f} c/u")
            if len(r.pendiente_recibir) > 10:
                w(f"    … y {len(r.pendiente_recibir) - 10} más.")

        if r.sin_categoria:
            w(self.style.WARNING(
                f"\n  {len(r.sin_categoria)} producto(s) nuevo(s) quedaron SIN categoría "
                "(no encajan en ninguna raíz del árbol, hay que decidir a mano):"
            ))
            for sku, nombre in r.sin_categoria:
                w(f"    {sku} — {nombre}")

        if r.sin_mascota:
            w(self.style.WARNING(
                f"\n  {len(r.sin_mascota)} producto(s) sin mascota (Perro/Gato/etc.) asignada."
            ))

        if r.categoria_asignada_a_existente:
            w(f"\n  Categoría asignada a productos que no tenían ninguna:")
            for sku, cat, origen in r.categoria_asignada_a_existente[:10]:
                w(f"    {sku}: {cat} ({origen})")
            if len(r.categoria_asignada_a_existente) > 10:
                w(f"    … y {len(r.categoria_asignada_a_existente) - 10} más.")

        if r.categoria_vieja_no_encontrada:
            w(self.style.WARNING(
                f"\n  {len(r.categoria_vieja_no_encontrada)} 'VUELVE' con categoría vieja que ya "
                "no existe en la base (se usó el mapeo por defecto):"
            ))
            for sku, nombre in r.categoria_vieja_no_encontrada:
                w(f"    {sku}: buscaba '{nombre}'")

        if r.precios:
            subidas = sum(1 for _, a, n in r.precios if n > a)
            w(self.style.WARNING(
                f"\n  {len(r.precios)} precio(s) cambiaron ({subidas} suben, "
                f"{len(r.precios) - subidas} bajan)."
            ))

        if r.costos:
            w(self.style.WARNING(
                f"\n  {len(r.costos)} producto(s) traen en la factura un costo distinto al que "
                "tenían en el kardex:"
            ))
            for sku, erp, excel in r.costos[:8]:
                w(f"    {sku}: kardex ₡{erp:,.2f} · factura ₡{excel:,.2f}")
            if len(r.costos) > 8:
                w(f"    … y {len(r.costos) - 8} más.")
            if con_existencias:
                w("    Con la compra recibida, el costo promedio queda en el promedio")
                w("    ponderado de lo que ya había y lo que entró. Eso es lo correcto:")
                w("    nadie 'corrige' un costo a mano, lo mueve la mercadería.")

        if r.duplicados:
            w(self.style.WARNING(f"\n  SKU repetidos en el Excel (se usó el primero): {', '.join(r.duplicados)}"))
        if r.inconsistencias:
            w(self.style.WARNING(f"\n  {len(r.inconsistencias)} inconsistencia(s) entre 'Estado' y la base real:"))
            for x in r.inconsistencias:
                w(f"    {x}")
        if r.errores:
            w(self.style.ERROR(f"\n  {len(r.errores)} error(es):"))
            for e in r.errores:
                w(f"    {e}")

        if seco:
            w(self.style.WARNING("\n  Nada de esto se guardó. Quitá --dry-run para aplicarlo.\n"))
        else:
            w(self.style.SUCCESS(
                "\n  Listo. Siguiente paso: cargar las fotos editadas "
                "(`manage.py cargar_fotos_por_sku <carpeta> --reemplazar`) y luego "
                "`manage.py exportar_catalogo_web`.\n"
            ))


class _Resultado:
    def __init__(self):
        self.creados = 0
        self.actualizados = 0
        self.saltados = 0
        self.vueltos = []
        self.precios = []
        self.costos = []
        self.errores = []
        self.duplicados = []
        self.inconsistencias = []
        self.sin_categoria = []
        self.sin_mascota = []
        self.pendiente_recibir = []
        self.categoria_asignada_a_existente = []
        self.categoria_vieja_no_encontrada = []
        # Datos de la compra con la que entran las existencias.
        self.compra_numero = ""
        self.compra_total = Decimal("0")
        self.compra_lineas = 0
        self.compra_unidades = Decimal("0")
        self.compra_forma_pago = ""
        self.compra_factura = ""
        self.proveedor = ""
        self.proveedor_creado = False
        self.puestos_en_cero = []
        self.ventas_ignoradas = []
