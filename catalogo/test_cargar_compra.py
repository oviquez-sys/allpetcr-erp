"""Pruebas del comando `cargar_compra_19_09`.

Se prueban las cosas que, si se rompen, cuestan plata o datos:

1. **No se inventan categorías raíz.** La columna "Categoría" del Excel de
   precios agrupa por margen ("Equipos electrónicos y muebles"), no por el
   árbol del sitio. Si el comando la usara tal cual, crearía raíces paralelas
   a las oficiales y ensuciaría el menú del sitio — es exactamente el error
   documentado en `arbol-de-categorias.md` (01/09/2026).
2. **Un producto que ya existía no pierde lo que tenía.** El Excel trae
   mascota y descripción vacías en decenas de filas; sobrescribir con vacío
   borraría trabajo hecho a mano.
3. **La misma factura no entra dos veces.** Duplicar existencias es el error
   más caro posible acá, y el único que no se nota hasta que alguien cuenta
   la bodega.
4. **Las existencias entran por el kardex, valoradas al costo de la
   factura**, y un código repetido en dos líneas suma las dos con su costo
   promedio ponderado (la factura trae 4 códigos así: 3 unidades a un precio
   y 12 al precio de volumen).
5. **`--igualar-al-excel` deja la cantidad de la hoja, no la que traía el
   sistema**, y el costo queda el de la factura sin arrastrar el viejo.
6. **Esa bandera se niega a correr si ya hubo ventas.** Ahí la hoja ya no
   sabe la verdad —no sabe lo que salió por caja— y el ajuste borraría
   inventario real sin que nada fallara.
"""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import openpyxl
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from caja.models import SesionCaja
from catalogo.models import Categoria, Producto
from compras.models import Compra
from core.models import Empresa, Sucursal
from inventario.models import Bodega, MovimientoInventario
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta

ENCABEZADOS = [
    "Código", "Estado", "Código de barras", "Nombre", "Categoría", "Mascota",
    "Descripción", "Cant.", "Costo", "PRECIO SUGERIDO",
]


def _hoja_de_precios(carpeta: Path, filas) -> str:
    """Escribe un Excel con la forma de la hoja "Precios" y devuelve su ruta."""
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Precios"
    hoja.append(ENCABEZADOS)
    for fila in filas:
        hoja.append(fila)
    ruta = carpeta / "precios.xlsx"
    libro.save(ruta)
    return str(ruta)


class CargarCompraTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        cls.sucursal = Sucursal.objects.create(empresa=cls.empresa, nombre="Central")
        Bodega.objects.create(sucursal=cls.sucursal, nombre="Principal")
        # Solo las raíces que estas pruebas necesitan del árbol oficial.
        for nombre, orden in (("Juguetes", 30), ("Comederos y bebederos", 60),
                              ("Rascadores y muebles", 120)):
            Categoria.objects.create(nombre=nombre, orden=orden)

    def setUp(self):
        self.carpeta = TemporaryDirectory()
        self.addCleanup(self.carpeta.cleanup)

    def _correr(self, filas, **opciones):
        ruta = _hoja_de_precios(Path(self.carpeta.name), filas)
        call_command("cargar_compra_19_09", archivo=ruta, archivo_bajas="", verbosity=0, **opciones)

    # ── 1. el árbol de categorías no se toca ─────────────────────────────
    def test_no_crea_categorias_raiz_nuevas_desde_el_excel(self):
        antes = set(Categoria.objects.values_list("nombre", flat=True))
        self._correr([
            # "Juguetes eléctricos" y "Equipos electrónicos y muebles" NO son
            # categorías del árbol: son baldes de margen.
            ["99001", "NUEVO", "", "Pelota", "Juguetes eléctricos", "Perro", "", 2, 1000, 2900],
            ["79534", "NUEVO", "", "Fuente de agua", "Equipos electrónicos y muebles", "", "", 1, 17200, 34900],
        ])
        self.assertEqual(set(Categoria.objects.values_list("nombre", flat=True)), antes)
        self.assertEqual(Producto.objects.get(sku="99001").categoria.nombre, "Juguetes")
        self.assertEqual(
            Producto.objects.get(sku="79534").categoria.nombre, "Comederos y bebederos"
        )

    def test_se_detiene_si_falta_una_raiz_del_arbol(self):
        """Antes de repartir productos en categorías inventadas, para.

        Si la raíz esperada no está, es que la base no tiene el árbol oficial
        (falta correr `asegurar_categorias`), y seguir significaría crearla
        con este comando — justo lo que no debe hacer.
        """
        Categoria.objects.filter(nombre="Juguetes").delete()
        with self.assertRaises(CommandError):
            self._correr([["99001", "NUEVO", "", "Pelota", "Juguetes", "Perro", "", 2, 1000, 2900]])

    # ── 2. lo que ya estaba no se pierde ─────────────────────────────────
    def test_no_borra_mascota_ni_descripcion_con_celdas_vacias(self):
        Producto.objects.create(
            empresa=self.empresa, sku="55801", nombre="Cama vieja",
            categoria=Categoria.objects.get(nombre="Rascadores y muebles"),
            mascota="Perro y gato", descripcion="Cama de peluche lavable",
            precio_venta=Decimal("5000"),
        )
        self._correr([["55801", "YA EN EL ERP", "", "Cama rectangular", "Descanso y rascadores",
                       "", "", 3, 2000, 5900]])
        p = Producto.objects.get(sku="55801")
        self.assertEqual(p.nombre, "Cama rectangular")          # el nombre sí se actualiza
        self.assertEqual(p.mascota, "Perro y gato")             # esto no se toca
        self.assertEqual(p.descripcion, "Cama de peluche lavable")
        # Y tampoco se le cambia la categoría que alguien ya había curado.
        self.assertEqual(p.categoria.nombre, "Rascadores y muebles")
        self.assertEqual(p.precio_venta, Decimal("5900.00"))
        self.assertEqual(p.cambios_precio.count(), 1)           # queda firmado

    # ── 3. la misma factura no entra dos veces ──────────────────────────
    def test_la_misma_factura_no_se_recibe_dos_veces(self):
        filas = [["99001", "NUEVO", "", "Pelota", "Juguetes", "Perro", "", 5, 1000, 2900]]
        self._correr(filas, con_existencias=True, factura="F-1")
        self.assertEqual(Producto.objects.get(sku="99001").stock_actual, Decimal("5"))

        with self.assertRaises(CommandError):
            self._correr(filas, con_existencias=True, factura="F-1")
        # Lo que importa: no se duplicó nada.
        self.assertEqual(Producto.objects.get(sku="99001").stock_actual, Decimal("5"))
        self.assertEqual(Compra.objects.count(), 1)

    def test_sin_con_existencias_no_toca_el_kardex(self):
        self._correr([["99001", "NUEVO", "", "Pelota", "Juguetes", "Perro", "", 5, 1000, 2900]])
        self.assertEqual(Producto.objects.get(sku="99001").stock_actual, Decimal("0"))
        self.assertEqual(MovimientoInventario.objects.count(), 0)
        self.assertEqual(Compra.objects.count(), 0)

    # ── 4. las existencias entran como compra, al costo de la factura ───
    def test_un_codigo_en_dos_lineas_suma_y_promedia_el_costo(self):
        """Los 12+3 del mismo código: 15 unidades y costo promedio ponderado.

        Es el caso de los 4 códigos que la factura trae dos veces (3 unidades
        al precio normal y 12 al de volumen). Sumarlos a mano con un costo
        promediado por fuera sería reescribir la factura; se mandan las dos
        líneas y el kardex calcula el promedio, que es su trabajo.
        """
        self._correr([
            ["82283", "NUEVO", "", "Peluches zorro", "Juguetes", "Perro", "", 3, 1900, 3800],
            ["82283", "NUEVO", "", "Peluches zorro", "Juguetes", "Perro", "", 12, 1520, 3800],
        ], con_existencias=True, factura="F-2")

        p = Producto.objects.get(sku="82283")
        self.assertEqual(p.stock_actual, Decimal("15"))
        # (3 x 1900 + 12 x 1520) / 15
        self.assertEqual(p.costo_promedio, Decimal("1596.00"))
        # Dos movimientos de kardex, los dos de compra: el rastro queda igual
        # al papel de la factura.
        movimientos = MovimientoInventario.objects.filter(producto=p)
        self.assertEqual(movimientos.count(), 2)
        self.assertEqual({m.tipo for m in movimientos}, {"COM"})
        compra = Compra.objects.get()
        self.assertEqual(compra.estado, Compra.Estado.RECIBIDA)
        self.assertEqual(compra.total, Decimal("23940.00"))  # 3x1900 + 12x1520

    # ── 5. --igualar-al-excel: manda la hoja, no lo que traía el sistema ──
    def test_igualar_al_excel_pone_en_cero_lo_que_habia_y_deja_el_costo_de_la_factura(self):
        """Antes de abrir, la cantidad del Excel es la verdad (Oscar, 18/09/2026).

        Lo que traía el sistema salió de una carga anterior, no de una venta:
        se pone en cero con un ajuste y entra la factura. El costo tampoco
        arrastra: queda el de esta factura, porque la entrada cae sobre stock
        cero.
        """
        producto = Producto.objects.create(
            empresa=self.empresa, sku="99001", nombre="Pelota",
            categoria=Categoria.objects.get(nombre="Juguetes"),
            precio_venta=Decimal("2900"),
        )
        bodega = Bodega.objects.get()
        registrar_movimiento(producto=producto, bodega=bodega, tipo="INI",
                             cantidad=Decimal("8"), costo_unitario=Decimal("700"),
                             referencia="CARGA-VIEJA")
        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, Decimal("8"))

        self._correr(
            [["99001", "YA EN EL ERP", "", "Pelota", "Juguetes", "Perro", "", 5, 1000, 2900]],
            con_existencias=True, igualar_al_excel=True, factura="F-3",
        )

        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, Decimal("5"))       # lo del Excel, no 8+5
        self.assertEqual(producto.costo_promedio, Decimal("1000.00"))  # el de la factura
        tipos = list(MovimientoInventario.objects.filter(producto=producto)
                     .order_by("id").values_list("tipo", "cantidad"))
        self.assertEqual(tipos, [("INI", Decimal("8.00")),
                                 ("AJU", Decimal("-8.00")),
                                 ("COM", Decimal("5.00"))])

    def _venta_emitida(self, numero="FV-00000001"):
        """Deja una venta emitida en la base, como la prueba del POS del 12/09."""
        cajero = get_user_model().objects.create_user(username=f"cajero{numero}", password="x")
        sesion = SesionCaja.objects.create(
            sucursal=self.sucursal, usuario=cajero, monto_apertura=Decimal("10000"),
        )
        return FacturaVenta.objects.create(
            empresa=self.empresa, sucursal=self.sucursal, numero=numero,
            total=Decimal("2900"), sesion_caja=sesion,
        )

    def test_ignorar_ventas_nombradas_deja_pasar_la_igualacion(self):
        """Las ventas de prueba se nombran una por una, no se apaga el guardia.

        El 12/09/2026 quedó una venta emitida que fue prueba del punto de
        venta. Nombrarla deja correr la igualación; el guardia sigue vivo para
        cualquier otra que aparezca.
        """
        producto = Producto.objects.create(
            empresa=self.empresa, sku="99001", nombre="Pelota",
            categoria=Categoria.objects.get(nombre="Juguetes"),
            precio_venta=Decimal("2900"),
        )
        registrar_movimiento(producto=producto, bodega=Bodega.objects.get(), tipo="INI",
                             cantidad=Decimal("8"), costo_unitario=Decimal("700"))
        self._venta_emitida("FV-00000036")

        self._correr(
            [["99001", "YA EN EL ERP", "", "Pelota", "Juguetes", "Perro", "", 5, 1000, 2900]],
            con_existencias=True, igualar_al_excel=True, factura="F-5",
            ignorar_ventas=["FV-00000036"],
        )
        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, Decimal("5"))

    def test_una_venta_no_nombrada_sigue_bloqueando(self):
        """La lista explícita no se pudre: una venta nueva vuelve a frenar todo.

        Es la diferencia con un --forzar, que una vez puesto en el script deja
        de proteger para siempre sin que nadie lo note.
        """
        producto = Producto.objects.create(
            empresa=self.empresa, sku="99001", nombre="Pelota",
            categoria=Categoria.objects.get(nombre="Juguetes"),
            precio_venta=Decimal("2900"),
        )
        registrar_movimiento(producto=producto, bodega=Bodega.objects.get(), tipo="INI",
                             cantidad=Decimal("8"), costo_unitario=Decimal("700"))
        self._venta_emitida("FV-00000036")   # la conocida, de prueba
        self._venta_emitida("FV-00000037")   # una nueva, que nadie revisó

        with self.assertRaises(CommandError):
            self._correr(
                [["99001", "YA EN EL ERP", "", "Pelota", "Juguetes", "Perro", "", 5, 1000, 2900]],
                con_existencias=True, igualar_al_excel=True, factura="F-6",
                ignorar_ventas=["FV-00000036"],
            )
        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, Decimal("8"))  # intacto

    def test_una_venta_anulada_no_bloquea(self):
        """Una anulada ya devolvió su mercadería a bodega: no esconde nada."""
        producto = Producto.objects.create(
            empresa=self.empresa, sku="99001", nombre="Pelota",
            categoria=Categoria.objects.get(nombre="Juguetes"),
            precio_venta=Decimal("2900"),
        )
        venta = self._venta_emitida("FV-00000010")
        venta.estado = FacturaVenta.Estado.ANULADA
        venta.save(update_fields=["estado"])

        self._correr(
            [["99001", "NUEVO", "", "Pelota", "Juguetes", "Perro", "", 5, 1000, 2900]],
            con_existencias=True, igualar_al_excel=True, factura="F-7",
        )
        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, Decimal("5"))

    def test_igualar_al_excel_se_niega_si_ya_hubo_ventas(self):
        """Con una venta hecha, igualar a la hoja borraría inventario real.

        La hoja no sabe lo que salió por caja. A partir de ahí el conteo se
        corrige con un ajuste físico, con su motivo — no con una importación.
        """
        producto = Producto.objects.create(
            empresa=self.empresa, sku="99001", nombre="Pelota",
            categoria=Categoria.objects.get(nombre="Juguetes"),
            precio_venta=Decimal("2900"),
        )
        registrar_movimiento(producto=producto, bodega=Bodega.objects.get(), tipo="INI",
                             cantidad=Decimal("8"), costo_unitario=Decimal("700"))
        cajero = get_user_model().objects.create_user(username="cajero", password="x")
        sesion = SesionCaja.objects.create(
            sucursal=self.sucursal, usuario=cajero, monto_apertura=Decimal("10000"),
        )
        FacturaVenta.objects.create(
            empresa=self.empresa, sucursal=self.sucursal, numero="FV-00000001",
            total=Decimal("2900"), sesion_caja=sesion,
        )

        with self.assertRaises(CommandError):
            self._correr(
                [["99001", "YA EN EL ERP", "", "Pelota", "Juguetes", "Perro", "", 5, 1000, 2900]],
                con_existencias=True, igualar_al_excel=True, factura="F-4",
            )
        producto.refresh_from_db()
        self.assertEqual(producto.stock_actual, Decimal("8"))  # intacto
        self.assertEqual(Compra.objects.count(), 0)
