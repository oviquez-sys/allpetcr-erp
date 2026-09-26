"""Pruebas de `cargar_compra_zeedog` (26/09/2026).

Lo que no se puede romper:
1. El código de barras que se guarda es el UPC real del proveedor, no uno
   inventado — así el producto queda reconocible por su empaque original.
2. La categoría se deduce del nombre y nunca se inventa una nueva.
3. Todo lo que trae la hoja se cobra (no hay bonificación acá): cantidad ×
   costo tiene que cuadrar con el total de la factura.
4. La misma factura no entra dos veces, y --dry-run no guarda nada.
5. Dos variantes (color o talla) del mismo modelo no quedan con el mismo
   nombre, y cada producto nuevo sale con su foto si está en la carpeta.
6. Un UPC que ya usa OTRO producto en el ERP no se acepta en silencio.
"""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import openpyxl
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from catalogo.models import Categoria, Producto
from compras.models import Compra
from core.models import Empresa, Sucursal
from inventario.models import Bodega

ENCABEZADOS = ["UPC proveedor", "Foto", "Marca", "Especie", "Producto en documento", "Talla / presentación",
               "Cantidad", "Costo bruto sin IVA", "Descuento", "Costo neto sin IVA", "Costo neto con IVA",
               "Precio oficial CR", "Diferencia unitaria", "Margen potencial", "Recargo sobre costo",
               "Disponibilidad web", "Fuente oficial / URL", "Fecha consulta", "Nombre oficial",
               "Variante verificada", "SKU interno web", "Archivo de imagen", "URL imagen original", "Notas"]

# Un PNG de 1x1 válido: alcanza para que se guarde y se haga la miniatura.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000105fe02d0a90000000049454e44ae426082"
)


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="ALLPETCR.COM", regimen=Empresa.Regimen.TRADICIONAL)
        cls.sucursal = Sucursal.objects.create(empresa=cls.empresa, nombre="Central")
        Bodega.objects.create(sucursal=cls.sucursal, nombre="Principal")
        Categoria.objects.create(nombre="Juguetes", orden=30)
        Categoria.objects.create(nombre="Paseo", orden=40)
        Categoria.objects.create(nombre="Ropa y accesorios", orden=50)
        Categoria.objects.create(nombre="Comederos y bebederos", orden=60)

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.carpeta = Path(self.dir.name)

    def excel(self, filas, con_relleno=True):
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "Comparativo"
        if con_relleno:
            hoja.append(["Zee.Dog · precios oficiales Costa Rica"])
            hoja.append([])
            hoja.append(["Nota cualquiera del comparativo."])
        hoja.append(ENCABEZADOS)
        for f in filas:
            hoja.append(f)
        ruta = self.carpeta / "zeedog.xlsx"
        libro.save(ruta)
        return str(ruta)

    def correr(self, filas, **extra):
        opciones = {"excel": self.excel(filas), "factura": "OV-1", "verbosity": 0}
        opciones.update(extra)
        call_command("cargar_compra_zeedog", **opciones)


def _fila(upc, marca, especie, producto, talla, cantidad, costo_neto, precio_oficial, nombre_oficial, variante):
    return [upc, None, marca, especie, producto, talla, cantidad, float(costo_neto), 0.05, float(costo_neto),
            float(costo_neto * Decimal("1.13")), precio_oficial, 0, 0, 0, "Disponible", "https://x", None,
            nombre_oficial, variante, "0", f"{upc}.png", "https://x", ""]


FILAS = [
    _fila("7898582508174", "Zee.Dog", "Perro", "ZEE.BOWL BORDEAU", "Única", 1, Decimal("12274.33"),
          21900, "Zee.Bowl - Plato ajustable para perro", "Bordeau"),
    _fila("7898582508198", "Zee.Dog", "Perro", "ZEE.BOWL GOTHAM", "Única", 1, Decimal("12274.33"),
          21900, "Zee.Bowl - Plato ajustable para perro", "Gotham"),
    _fila("7898582475896", "Zee.Dog", "Perro", "PRISMA COLLAR SMALL", "Small", 1, Decimal("6109.15"),
          10900, "Prisma - Collar para perros", "Small"),
    _fila("7908471105985", "Zee.Dog", "Perro", "AIRTAG HOLDER GOTHAM", "Única", 1, Decimal("3867.26"),
          6900, "Airtag Holder", "Gotham"),
    _fila("7898582487875", "Zee.Dog", "Perro", "BRAIN DEAD", "Única", 2, Decimal("5548.68"),
          9900, "Brainies - Juguete para perro", "Brain Dead"),
]


class CargaZeeDog(_Base):
    def test_usa_el_upc_real_como_codigo_de_barras(self):
        self.correr(FILAS)
        p = Producto.objects.get(sku="ZDG-7898582508174")
        self.assertEqual(p.codigo_barras, "7898582508174")

    def test_categoria_se_deduce_del_nombre(self):
        self.correr(FILAS)
        self.assertEqual(Producto.objects.get(sku="ZDG-7898582508174").categoria.nombre, "Comederos y bebederos")
        self.assertEqual(Producto.objects.get(sku="ZDG-7898582475896").categoria.nombre, "Paseo")
        self.assertEqual(Producto.objects.get(sku="ZDG-7908471105985").categoria.nombre, "Ropa y accesorios")
        self.assertEqual(Producto.objects.get(sku="ZDG-7898582487875").categoria.nombre, "Juguetes")

    def test_no_hay_bonificacion_todo_se_cobra(self):
        self.correr(FILAS)
        compra = Compra.objects.get()
        # 12274.33 + 12274.33 + 6109.15 + 3867.26 + 2×5548.68
        self.assertEqual(compra.total, Decimal("45622.43"))
        p = Producto.objects.get(sku="ZDG-7898582487875")
        self.assertEqual(p.stock_actual, 2)
        self.assertEqual(p.costo_promedio, Decimal("5548.68"))

    def test_variantes_no_quedan_con_el_mismo_nombre(self):
        self.correr(FILAS)
        n1 = Producto.objects.get(sku="ZDG-7898582508174").nombre
        n2 = Producto.objects.get(sku="ZDG-7898582508198").nombre
        self.assertNotEqual(n1, n2)
        self.assertIn("Bordeau", n1)
        self.assertIn("Gotham", n2)

    def test_simulacion_no_guarda_nada(self):
        self.correr(FILAS, dry_run=True)
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(Compra.objects.exists())

    def test_la_misma_factura_no_entra_dos_veces(self):
        self.correr(FILAS)
        with self.assertRaises(Exception):
            self.correr(FILAS)
        self.assertEqual(Producto.objects.count(), 5)

    def test_upc_que_ya_usa_otro_producto_es_error(self):
        Producto.objects.create(empresa=self.empresa, sku="OTRO-1", nombre="Otro producto",
                                 precio_venta=100, codigo_barras="7898582508174")
        with self.assertRaises(CommandError):
            self.correr(FILAS)
        self.assertEqual(Producto.objects.count(), 1)

    def test_asocia_la_foto_por_upc(self):
        fotos = self.carpeta / "fotos"
        fotos.mkdir()
        (fotos / "7898582508174.png").write_bytes(PNG)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.correr(FILAS, fotos=str(fotos))
            self.assertEqual(Producto.objects.get(sku="ZDG-7898582508174").imagen, "productos/ZDG-7898582508174.png")
            self.assertFalse(Producto.objects.get(sku="ZDG-7898582508198").imagen)

    def test_categoria_inexistente_en_el_erp_es_error(self):
        Categoria.objects.filter(nombre="Paseo").delete()
        with self.assertRaises(CommandError):
            self.correr(FILAS)
        self.assertFalse(Producto.objects.exists())
