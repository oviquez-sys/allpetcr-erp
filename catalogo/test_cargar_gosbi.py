"""Pruebas de `cargar_compra_gosbi` (26/09/2026).

Lo que no se puede romper:
1. El código de barras es un EAN-8 interno (el código de Vecevet no sirve de
   nada para escanear), igual que Belina.
2. Se carga el precio MÍNIMO de mercado, no el máximo ni el costo.
3. Un producto agotado en las dos tiendas (sin precio) toma el mínimo de
   otro producto del MISMO costo unitario, y si no hay ninguno es un error
   — nunca se inventa un precio de la nada.
4. La categoría: presentación en kg → Alimento seco; "Gosbits" → Snacks y
   premios; el resto (Natsbi, Fresko, Delicat) → Alimento húmedo.
5. La misma factura no entra dos veces, y --dry-run no guarda nada.
6. Dos presentaciones del mismo sabor no quedan con el mismo nombre.
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

ENCABEZADOS = ["Código proveedor", "Foto", "Especie", "Marca", "Producto", "Presentación",
               "Cantidad comprada", "Costo unitario sin IVA", "Costo unitario con IVA",
               "Venta mínimo CR", "Tienda mínimo", "URL mínimo", "Venta máximo CR", "Tienda máximo",
               "URL máximo", "Diferencia máximo − mínimo", "Margen vs mínimo", "Margen vs máximo",
               "Tiendas disponibles", "Estado coincidencia", "Fecha consulta", "Observaciones",
               "Archivo imagen", "Fuente foto", "URL imagen original"]

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
        Categoria.objects.create(nombre="Alimento seco", padre=alimento, orden=11)
        Categoria.objects.create(nombre="Alimento húmedo", padre=alimento, orden=12)
        Categoria.objects.create(nombre="Snacks y premios", orden=20)

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.carpeta = Path(self.dir.name)

    def excel(self, filas):
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "Comparativo"
        hoja.append(["Gosbi · precios de tiendas Costa Rica"])
        hoja.append([])
        hoja.append(["Nota cualquiera del comparativo."])
        hoja.append(ENCABEZADOS)
        for f in filas:
            hoja.append(f)
        ruta = self.carpeta / "gosbi.xlsx"
        libro.save(ruta)
        return str(ruta)

    def correr(self, filas, **extra):
        opciones = {"excel": self.excel(filas), "factura": "F-1", "verbosity": 0}
        opciones.update(extra)
        call_command("cargar_compra_gosbi", **opciones)


def _fila(codigo, especie, marca, producto, presentacion, cantidad, costo, vmin, vmax, tiendas=1):
    costo = Decimal(str(costo))
    return [codigo, None, especie, marca, producto, presentacion, cantidad, float(costo), 0.13,
            vmin, "Tienda A", "https://x", vmax, "Tienda B", "https://x", 0, 0, 0, tiendas,
            "Coincidencia alta", None, "", f"{codigo}.png", "https://x", "https://x"]


FILAS = [
    _fila("71020", "Perro", "Gosbi", "Gosbi Exclusive Grain Free Adult Duck Medium", "3 kg", 1, "14495.58",
          22000, 22440, 2),
    _fila("932", "Perro", "Gosbi", "Gosbi Exclusive Chicken Mini", "2 kg", 2, "10221.24", None, None, 0),
    _fila("938", "Perro", "Gosbi", "Gosbi Exclusive Fish Mini", "2 kg", 1, "10221.24", 15550, 15820, 2),
    _fila("71012", "Perro", "Gosbi", "Gosbits Fish", "300 g", 2, "4442.48", 6750, 6880, 2),
    _fila("71847", "Perro", "Gosbi", "Natsbi Steamed Chicken", "500 g", 2, "3265.49", 5000, 5000, 1),
    _fila("72165", "Perro", "Gosbi", "Natsbi Steamed Chicken", "200 g", 2, "1778.76", 2700, 2700, 1),
]


class CargaGosbi(_Base):
    def test_usa_ean8_interno_no_el_codigo_de_vecevet(self):
        self.correr(FILAS)
        p = Producto.objects.get(sku="GOS-71020")
        self.assertNotEqual(p.codigo_barras, "71020")
        self.assertTrue(p.codigo_barras.startswith("2"))
        self.assertEqual(len(p.codigo_barras), 8)

    def test_carga_el_precio_minimo_no_el_maximo(self):
        self.correr(FILAS)
        self.assertEqual(Producto.objects.get(sku="GOS-71020").precio_venta, Decimal("22000"))

    def test_agotado_toma_el_minimo_del_mismo_costo(self):
        self.correr(FILAS)
        # 932 no tiene precio propio; comparte costo (10221.24) con 938 (vmin 15550).
        self.assertEqual(Producto.objects.get(sku="GOS-932").precio_venta, Decimal("15550"))

    def test_agotado_sin_ningun_comparable_es_error(self):
        filas = FILAS + [_fila("999", "Perro", "Gosbi", "Gosbi Exclusive Rara", "9 kg", 1, "99999.99",
                                None, None, 0)]
        with self.assertRaises(CommandError):
            self.correr(filas)
        self.assertFalse(Producto.objects.exists())

    def test_categoria_por_presentacion_y_nombre(self):
        self.correr(FILAS)
        self.assertEqual(Producto.objects.get(sku="GOS-71020").categoria.nombre, "Alimento seco")
        self.assertEqual(Producto.objects.get(sku="GOS-71012").categoria.nombre, "Snacks y premios")
        self.assertEqual(Producto.objects.get(sku="GOS-71847").categoria.nombre, "Alimento húmedo")

    def test_dos_presentaciones_no_quedan_con_el_mismo_nombre(self):
        self.correr(FILAS)
        n500 = Producto.objects.get(sku="GOS-71847").nombre
        n200 = Producto.objects.get(sku="GOS-72165").nombre
        self.assertNotEqual(n500, n200)
        self.assertIn("500 g", n500)
        self.assertIn("200 g", n200)

    def test_simulacion_no_guarda_nada(self):
        self.correr(FILAS, dry_run=True)
        self.assertFalse(Producto.objects.exists())
        self.assertFalse(Compra.objects.exists())

    def test_la_misma_factura_no_entra_dos_veces(self):
        self.correr(FILAS)
        with self.assertRaises(Exception):
            self.correr(FILAS)
        self.assertEqual(Producto.objects.count(), 6)

    def test_asocia_la_foto_por_codigo(self):
        fotos = self.carpeta / "fotos"
        fotos.mkdir()
        (fotos / "71020.png").write_bytes(PNG)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.correr(FILAS, fotos=str(fotos))
            self.assertEqual(Producto.objects.get(sku="GOS-71020").imagen, "productos/GOS-71020.png")
            self.assertFalse(Producto.objects.get(sku="GOS-71012").imagen)

    def test_categoria_inexistente_en_el_erp_es_error(self):
        Categoria.objects.filter(nombre="Alimento húmedo").delete()
        with self.assertRaises(CommandError):
            self.correr(FILAS)
        self.assertFalse(Producto.objects.exists())
