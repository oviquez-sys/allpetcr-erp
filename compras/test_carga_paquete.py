"""Carga masiva con paquete .zip (27/10/2026): fotos, descuento, CABYS y margen mínimo.

Lo que fijan estas pruebas:
- Las fotos del .zip llegan al producto por su código, se VEN en la vista
  previa y no tocan nada hasta confirmar. Una foto sin fila es un error.
- A un producto que ya tiene foto no se le cambia.
- El descuento de la factura llega a la compra y al costo real.
- El CABYS se valida y no pisa uno ya puesto.
- Un margen bajo el mínimo NO bloquea: se avisa (amarillo) con el precio que
  dejaría el mínimo.
"""
import io
import os
import tempfile
import zipfile
from datetime import timedelta
from decimal import Decimal

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from openpyxl import Workbook
from PIL import Image

from catalogo.models import Categoria, Producto
from core.models import Empresa

from . import carga_masiva as cm
from .models import Compra
from .tests import BaseCompras

ENCABEZADO = ("Código (SKU)", "Código de barras", "Nombre", "Cantidad", "Costo unitario", "Precio de venta",
              "Bonificadas", "Categoría", "CABYS")


def _png(color=(200, 30, 30)):
    salida = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(salida, "PNG")
    return salida.getvalue()


def _hoja(filas, encabezado=ENCABEZADO):
    wb = Workbook()
    ws = wb.active
    ws.append(list(encabezado))
    for f in filas:
        ws.append(list(f))
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _zip(filas, fotos=None, hojas=1):
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as zf:
        for i in range(hojas):
            zf.writestr(f"factura/mercaderia{i or ''}.xlsx", _hoja(filas))
        for nombre, contenido in (fotos or {}).items():
            zf.writestr(f"factura/fotos/{nombre}", contenido)
        zf.writestr("__MACOSX/._TOW-1.png", b"basura de Mac")
    return SimpleUploadedFile("compra.zip", salida.getvalue())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CargaConPaquete(BaseCompras):
    def setUp(self):
        super().setUp()
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL
        self.empresa.save()
        alimento = Categoria.objects.create(nombre="Alimento")
        Categoria.objects.create(nombre="Alimento seco", padre=alimento)
        Categoria.objects.create(nombre="Juguetes")
        self.producto.codigo_barras = "7501234567895"
        self.producto.save()
        self.client.force_login(self.usuario)

    def subir(self, archivo, **extra):
        datos = {"proveedor_id": self.proveedor.pk, "factura_proveedor": "F-77", "forma_pago": "CON",
                 "archivo": archivo, **extra}
        return self.client.post(reverse("compras:carga_masiva"), datos)

    def confirmar(self, r):
        return self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})

    # ── fotos ───────────────────────────────────────────────────────────
    def test_la_foto_del_zip_llega_al_producto_nuevo(self):
        r = self.subir(_zip([["TOW-1", "", "Taste of the Wild 2 kg", 4, 10000, 16900, 0, "Alimento seco", ""]],
                            {"TOW-1.png": _png()}))
        self.assertContains(r, "Todo en orden")
        self.assertContains(r, "1 foto(s)")
        fila = r.context["revision"].filas[0]
        self.assertTrue(fila.foto_se_pone)
        self.assertTrue(fila.foto_url, "la vista previa tiene que mostrar la foto")
        self.assertFalse(Producto.objects.filter(sku="TOW-1").exists(), "subir no crea nada")
        self.confirmar(r)
        p = Producto.objects.get(sku="TOW-1")
        self.assertTrue(p.imagen.startswith("productos/TOW-1-"))
        self.assertTrue(default_storage.exists(p.imagen))
        self.assertFalse(default_storage.exists(fila.foto), "la foto en espera se borra al confirmar")

    def test_la_foto_se_reconoce_tambien_por_codigo_de_barras(self):
        r = self.subir(_zip([["", "7501234567895", "", 2, 10000, "", 0, "", ""]],
                            {"7501234567895.webp": _png()}))
        self.assertTrue(r.context["revision"].filas[0].foto_se_pone)
        self.confirmar(r)
        self.producto.refresh_from_db()
        self.assertTrue(self.producto.imagen.startswith("productos/P-001-"))

    def test_foto_sin_fila_es_error_y_no_se_sube_nada(self):
        r = self.subir(_zip([["TOW-1", "", "Taste of the Wild 2 kg", 4, 10000, 16900, 0, "", ""]],
                            {"TOW-1.png": _png(), "TOW-9.png": _png()}))
        self.assertContains(r, "TOW-9.png")
        self.assertNotIn("firma", r.context)
        self.assertEqual(r.context["revision"].filas[0].foto, "", "con errores no se sube ninguna foto")

    def test_no_se_cambia_la_foto_de_un_producto_que_ya_tiene(self):
        self.producto.imagen = "productos/P-001.png"
        self.producto.save()
        r = self.subir(_zip([["P-001", "", "", 1, 10000, "", 0, "", ""]], {"P-001.png": _png()}))
        fila = r.context["revision"].filas[0]
        self.assertFalse(fila.foto_se_pone)
        self.assertTrue(any("Ya tiene foto" in a for a in fila.avisos))
        self.confirmar(r)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.imagen, "productos/P-001.png")

    def test_un_archivo_que_no_es_imagen_se_rechaza(self):
        r = self.subir(_zip([["TOW-1", "", "Taste of the Wild 2 kg", 4, 10000, 16900, 0, "", ""]],
                            {"TOW-1.png": b"esto no es una foto"}))
        self.assertNotIn("firma", r.context)
        self.assertContains(r, "TOW-1.png")

    def test_el_zip_trae_un_solo_excel(self):
        r = self.subir(_zip([["TOW-1", "", "X", 1, 100, 500, 0, "", ""]], hojas=2))
        self.assertContains(r, "UN solo Excel")
        self.assertNotIn("firma", r.context)

    def test_un_excel_suelto_sigue_funcionando(self):
        archivo = SimpleUploadedFile("m.xlsx", _hoja([["TOW-1", "", "X", 1, 100, 500, 0, "", ""]]))
        r = self.subir(archivo)
        self.assertContains(r, "Todo en orden")

    # ── descuento ───────────────────────────────────────────────────────
    def test_el_descuento_llega_a_la_compra_y_al_costo(self):
        # Caso real de Belina: ₡29.260 − ₡878 = ₡28.382.
        r = self.subir(_zip([["BEL-1", "", "Balance 2 kg", 7, 4180, 5990, 0, "Alimento seco", ""]]),
                       descuento="878")
        self.assertContains(r, "28.382")
        self.confirmar(r)
        compra = Compra.objects.get(factura_proveedor="F-77")
        self.assertEqual(compra.descuento, Decimal("878.00"))
        p = Producto.objects.get(sku="BEL-1")
        self.assertEqual(p.costo_promedio.quantize(Decimal("0.01")), (Decimal("28382") / 7).quantize(Decimal("0.01")))

    def test_descuento_mayor_que_la_factura_no_se_acepta(self):
        r = self.subir(_zip([["BEL-1", "", "Balance 2 kg", 1, 1000, 5990, 0, "", ""]]), descuento="2000")
        self.assertNotIn("firma", r.context)

    # ── CABYS ───────────────────────────────────────────────────────────
    def test_cabys_se_pone_al_nuevo_y_no_pisa_el_existente(self):
        self.producto.cabys = "2399100000000"
        self.producto.save()
        r = self.subir(_zip([["TOW-1", "", "X", 1, 100, 500, 0, "", "2399100000100"],
                             ["P-001", "", "", 1, 10000, "", 0, "", "2399100000200"]]))
        self.confirmar(r)
        self.assertEqual(Producto.objects.get(sku="TOW-1").cabys, "2399100000100")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.cabys, "2399100000000")

    def test_cabys_invalido_es_error(self):
        r = self.subir(_zip([["TOW-1", "", "X", 1, 100, 500, 0, "", "12345"]]))
        self.assertNotIn("firma", r.context)
        self.assertContains(r, "13 dígitos")

    # ── margen mínimo ───────────────────────────────────────────────────
    def test_margen_bajo_el_minimo_avisa_pero_deja_cargar(self):
        # Alimento: costo 10.000, precio 12.900 con IVA → 11.415,93 sin IVA → 12,4 % < 15 %.
        r = self.subir(_zip([["TOW-1", "", "Taste of the Wild 2 kg", 1, 10000, 12900, 0, "Alimento seco", ""]]))
        fila = r.context["revision"].filas[0]
        self.assertEqual(fila.margen, "12.4")
        self.assertTrue(any("debajo del mínimo de 15 %" in a for a in fila.avisos), fila.avisos)
        # Precio con el mínimo: 10.000 / 0,85 × 1,13 = 13.294,12 → ₡13.295.
        self.assertTrue(any("₡13.295" in a for a in fila.avisos), fila.avisos)
        self.assertIn("firma", r.context, "el aviso no bloquea")
        self.assertContains(r, "amarillo")

    def test_accesorio_usa_el_minimo_de_accesorios(self):
        # Juguete: costo 1.000, precio 1.990 → 1.761 sin IVA → 43,2 % ≥ 30 %: sin aviso.
        r = self.subir(_zip([["J-1", "", "Pelota", 3, 1000, 1990, 0, "Juguetes", ""],
                             # 1.000 de costo a ₡1.490 → 1.318,58 sin IVA → 24,2 % < 30 %.
                             ["J-2", "", "Pelota 2", 3, 1000, 1490, 0, "Juguetes", ""]]))
        a, b = r.context["revision"].filas
        self.assertEqual(a.avisos, [])
        self.assertEqual(b.margen_minimo, "30")
        self.assertTrue(b.avisos)

    def test_el_margen_cuenta_regalias_y_descuento(self):
        # 10 facturadas + 2 de regalo, ₡1.000 c/u, descuento ₡1.000 → costo real 9.000/12 = ₡750.
        r = self.subir(_zip([["J-1", "", "Pelota", 10, 1000, 1130, 2, "Juguetes", ""]]), descuento="1000")
        self.assertEqual(cm.costo_real(r.context["revision"].filas[0], r.context["revision"]), Decimal("750"))
        # 1.130 con IVA = 1.000 sin IVA → (1.000 − 750) / 1.000 = 25 %.
        self.assertEqual(r.context["revision"].filas[0].margen, "25.0")


class PaqueteSeguro(BaseCompras):
    def test_zip_danado(self):
        p = cm.abrir_paquete(SimpleUploadedFile("x.zip", b"no soy un zip"))
        self.assertTrue(p.errores)

    def test_basura_de_mac_y_carpetas_se_ignoran(self):
        p = cm.abrir_paquete(_zip([["A", "", "X", 1, 1, 1, 0, "", ""]], {"A.png": _png()}))
        self.assertEqual(p.errores, [])
        self.assertEqual(set(p.fotos), {"a"})
        self.assertTrue(os.path.basename(p.hoja.name).endswith(".xlsx"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class LimpiezaDeFotosEnEspera(BaseCompras):
    def test_se_borran_las_de_vistas_previas_abandonadas_y_no_las_recientes(self):
        from django.core.files.base import ContentFile
        from django.utils import timezone

        vieja = f"{cm.CARPETA_PENDIENTES}/{timezone.now() - timedelta(hours=3):%Y%m%d%H%M}-abc/x.png"
        nueva = f"{cm.CARPETA_PENDIENTES}/{timezone.now():%Y%m%d%H%M}-def/y.png"
        vieja = default_storage.save(vieja, ContentFile(b"1"))
        nueva = default_storage.save(nueva, ContentFile(b"2"))
        cm._limpiar_pendientes_viejos()
        self.assertFalse(default_storage.exists(vieja))
        self.assertTrue(default_storage.exists(nueva))
