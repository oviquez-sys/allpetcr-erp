"""Pruebas de `cargar_compra_belina` (26/09/2026) y de las líneas de compra
que traen solo bonificadas.

Lo que no se puede romper:
1. Un producto que vino SOLO de regalo entra a bodega a costo cero, y la
   factura no lo cobra.
2. Uno que vino pagado y con regalo (1 + 1) reparte el costo: la unidad de
   regalo no suma costo.
3. Presentaciones distintas del mismo alimento no quedan con el mismo nombre.
4. La misma factura no entra dos veces, y --dry-run no guarda nada.
5. Cada producto nuevo sale con código de barras interno (para etiquetarlo)
   y con su foto.
"""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import openpyxl
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from catalogo.models import Categoria, Producto
from compras.models import Compra, Proveedor
from compras.services import crear_y_recibir_compra
from core.models import Empresa, Sucursal
from inventario.models import Bodega

ENCABEZADOS = ["Código de proveedor", "Nombre", "Cantidad", "Costo unitario", "Precio de venta",
               "Bonificadas", "Marca", "Categoría", "Presentación", "Mascota", "Alerta de precio"]

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
        alimento = Categoria.objects.create(nombre="Alimento", orden=10)
        Categoria.objects.create(nombre="Alimento seco", padre=alimento)
        Categoria.objects.create(nombre="Alimento húmedo", padre=alimento)
        Categoria.objects.create(nombre="Snacks y premios", orden=20)

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.carpeta = Path(self.dir.name)

    def excel(self, filas):
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "Inventario (subir)"
        hoja.append(ENCABEZADOS)
        for f in filas:
            hoja.append(f)
        ruta = self.carpeta / "belina.xlsx"
        libro.save(ruta)
        return str(ruta)

    def correr(self, filas, **extra):
        opciones = {"excel": self.excel(filas), "factura": "F-1", "verbosity": 0}
        opciones.update(extra)
        call_command("cargar_compra_belina", **opciones)


FILAS = [
    ["17704", "PV GF DOG Salmon", 2, 8230, 11475, 0, "PureVita", "Alimento seco", "4 lb", "Perro", "ok"],
    ["21258", "NS Weight Dog", 1, 6940, 9775, 1, "NutriSource", "Alimento seco", "4 lb", "Perro", "ok"],
    ["40006", "PV DOG Hip-Joint Treat", 0, 0, 2975, 29, "PureVita", "Premios", "179 g", "Perro", "regalo"],
    ["53228", "Balance Puppy", 2, 3290, 4175, 0, "Balance", "Alimento seco", "2 kg", "Perro", "ok"],
    ["53229", "Balance Puppy", 1, 7790, 9775, 0, "Balance", "Alimento seco", "5 kg", "Perro", "ok"],
]


class CargaBelina(_Base):
    def test_regalo_entra_a_costo_cero_y_la_factura_no_lo_cobra(self):
        self.correr(FILAS)
        regalo = Producto.objects.get(sku="BEL-40006")
        self.assertEqual(regalo.stock_actual, 29)
        self.assertEqual(regalo.costo_promedio, 0)
        self.assertEqual(regalo.precio_venta, Decimal("2975"))
        compra = Compra.objects.get()
        # 2×8230 + 1×6940 + 2×3290 + 1×7790 — el regalo no suma.
        self.assertEqual(compra.total, Decimal("37770.00"))
        self.assertEqual(compra.iva, Decimal("4910.10"))
        linea = compra.lineas.get(producto=regalo)
        self.assertEqual((linea.cantidad, linea.cantidad_bonificada), (0, 29))

    def test_pagado_mas_regalo_reparte_el_costo(self):
        self.correr(FILAS)
        p = Producto.objects.get(sku="BEL-21258")
        self.assertEqual(p.stock_actual, 2)
        self.assertEqual(p.costo_promedio, Decimal("3470.00"))

    def test_presentaciones_con_nombre_propio_y_marca(self):
        self.correr(FILAS)
        self.assertEqual(Producto.objects.get(sku="BEL-53228").nombre, "Balance Puppy 2 kg")
        self.assertEqual(Producto.objects.get(sku="BEL-53229").nombre, "Balance Puppy 5 kg")
        self.assertEqual(Producto.objects.get(sku="BEL-17704").nombre, "PureVita GF DOG Salmon 4 lb")
        p = Producto.objects.get(sku="BEL-40006")
        self.assertEqual(p.categoria.nombre, "Snacks y premios")
        self.assertEqual(p.mascota, "Perro")

    def test_cada_producto_nuevo_sale_con_codigo_de_barras_interno(self):
        self.correr(FILAS)
        codigos = list(Producto.objects.values_list("codigo_barras", flat=True))
        self.assertEqual(len(codigos), 5)
        self.assertTrue(all(c.startswith("2") and len(c) == 8 for c in codigos))
        self.assertEqual(len(set(codigos)), 5)

    def test_simulacion_no_guarda_nada(self):
        self.correr(FILAS, dry_run=True)
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(Compra.objects.exists())

    def test_la_misma_factura_no_entra_dos_veces(self):
        self.correr(FILAS)
        with self.assertRaises(ValidationError):
            self.correr(FILAS)
        self.assertEqual(Producto.objects.get(sku="BEL-17704").stock_actual, 2)

    def test_excel_con_errores_no_carga_nada(self):
        malas = FILAS + [["99999", "Sin unidades", 0, 0, 1000, 0, "X", "Alimento seco", "1 kg", "Perro", ""]]
        with self.assertRaises(CommandError):
            self.correr(malas)
        self.assertFalse(Producto.objects.exists())

    def test_categoria_desconocida_es_error(self):
        with self.assertRaises(CommandError):
            self.correr([["1", "Algo", 1, 100, 200, 0, "X", "Juguetes raros", "1 u", "Perro", ""]])

    def test_asocia_la_foto_por_codigo(self):
        fotos = self.carpeta / "fotos"
        fotos.mkdir()
        (fotos / "17704.png").write_bytes(PNG)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.correr(FILAS, fotos=str(fotos))
            self.assertEqual(Producto.objects.get(sku="BEL-17704").imagen, "productos/BEL-17704.png")
            self.assertFalse(Producto.objects.get(sku="BEL-21258").imagen)


class LineaSoloBonificada(_Base):
    """La regla vale para cualquier compra, no solo para esta carga."""

    def test_linea_solo_bonificada_se_acepta(self):
        p = Producto.objects.create(empresa=self.empresa, sku="X1", nombre="Muestra", precio_venta=100)
        prov = Proveedor.objects.create(empresa=self.empresa, nombre="P")
        crear_y_recibir_compra(proveedor=prov, sucursal=self.sucursal,
                               lineas=[{"producto": p, "cantidad": 0, "cantidad_bonificada": 3,
                                        "costo_unitario": 0}])
        p.refresh_from_db()
        self.assertEqual((p.stock_actual, p.costo_promedio), (3, 0))

    def test_linea_vacia_se_rechaza(self):
        p = Producto.objects.create(empresa=self.empresa, sku="X2", nombre="Nada", precio_venta=100)
        prov = Proveedor.objects.create(empresa=self.empresa, nombre="P")
        with self.assertRaises(ValidationError):
            crear_y_recibir_compra(proveedor=prov, sucursal=self.sucursal,
                                   lineas=[{"producto": p, "cantidad": 0, "costo_unitario": 0}])
