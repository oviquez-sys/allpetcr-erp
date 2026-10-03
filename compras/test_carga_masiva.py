"""INV-01 (auditoría 26/09/2026): carga masiva de mercadería desde Excel/CSV.

Lo que fijan estas pruebas: subir NO guarda nada; con un error no se puede
confirmar; al confirmar entra todo junto (productos nuevos, compra, stock,
costo, asiento y precios) y lo que se confirma es lo que se mostró.
"""
import io
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from catalogo.codigos import es_interno
from catalogo.models import CambioPrecio, Categoria, Producto
from impresion.models import TrabajoImpresion

from .models import Compra
from .tests import BaseCompras


def _excel(filas, encabezado=("Código de barras", "Nombre", "Cantidad", "Costo unitario", "Precio de venta",
                              "Bonificadas", "Marca", "Categoría", "Presentación", "Mascota")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(encabezado))
    for f in filas:
        ws.append(list(f))
    salida = io.BytesIO()
    wb.save(salida)
    return SimpleUploadedFile("mercaderia.xlsx", salida.getvalue())


class CargaMasiva(BaseCompras):
    def setUp(self):
        super().setUp()
        self.producto.codigo_barras = "7501234567895"
        self.producto.save()
        Categoria.objects.create(nombre="Juguetes")
        self.client.force_login(self.usuario)

    def subir(self, archivo, **extra):
        datos = {"proveedor_id": self.proveedor.pk, "factura_proveedor": "F-900", "forma_pago": "CON",
                 "archivo": archivo, **extra}
        return self.client.post(reverse("compras:carga_masiva"), datos)

    def test_la_plantilla_se_descarga_y_se_abre(self):
        r = self.client.get(reverse("compras:carga_masiva_plantilla"))
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.active["A1"].value, "Código de barras")

    def test_subir_no_guarda_nada(self):
        r = self.subir(_excel([["7501234567895", "", 5, 9000, "", 0],
                               ["", "Pelota nueva", 10, 500, 1500, 2, "", "Juguetes", "", "perro"]]))
        self.assertContains(r, "Todo en orden")
        self.assertEqual(Compra.objects.count(), 0)
        self.assertFalse(Producto.objects.filter(nombre="Pelota nueva").exists())

    def test_con_errores_no_se_puede_confirmar(self):
        r = self.subir(_excel([["", "Sin precio", 3, 100, "", 0],
                               ["7501234567895", "", "tres", 100, "", 0],
                               ["", "Otra", 1, 1, 100, 0, "", "No existe"]]))
        self.assertContains(r, "falta el precio de venta")
        self.assertContains(r, "no es un número")
        self.assertContains(r, "no existe en el ERP")
        self.assertNotIn("firma", r.context)

    def confirmar(self, archivo):
        r = self.subir(archivo)
        return self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})

    def test_confirmar_carga_todo(self):
        r = self.confirmar(_excel([
            ["7501234567895", "", 5, 9000, 19500, 1],
            ["", "Pelota nueva", 10, 500, 1500, 2, "Kong", "Juguetes", "Talla S", "Perro"],
        ]))
        self.assertEqual(r.status_code, 200)
        compra = Compra.objects.get()
        self.assertEqual(compra.estado, Compra.Estado.RECIBIDA)
        self.assertEqual(compra.factura_proveedor, "F-900")
        self.assertEqual(compra.total, Decimal("50000"))            # 5×9000 + 10×500
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("16"))   # 10 + 5 + 1 bonificada
        self.assertEqual(self.producto.precio_venta, Decimal("19500"))
        self.assertTrue(CambioPrecio.objects.filter(producto=self.producto).exists())
        nuevo = Producto.objects.get(nombre="Pelota nueva")
        self.assertEqual(nuevo.stock_actual, Decimal("12"))
        self.assertTrue(es_interno(nuevo.codigo_barras))
        self.assertEqual((nuevo.marca, nuevo.mascota, nuevo.categoria.nombre), ("Kong", "Perro", "Juguetes"))

    def test_la_misma_factura_no_entra_dos_veces(self):
        self.confirmar(_excel([["7501234567895", "", 5, 9000, "", 0]]))
        self.confirmar(_excel([["7501234567895", "", 5, 9000, "", 0]]))
        self.assertEqual(Compra.objects.count(), 1)

    def test_si_algo_falla_al_confirmar_no_queda_nada(self):
        r = self.subir(_excel([["", "Pelota nueva", 10, 500, 1500, 0]]))
        with mock.patch("compras.services.recibir_compra", side_effect=Exception("se cayó")):
            with self.assertRaises(Exception):
                self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})
        self.assertFalse(Producto.objects.filter(nombre="Pelota nueva").exists())
        self.assertEqual(Compra.objects.count(), 0)

    def test_la_vista_previa_no_se_puede_alterar(self):
        r = self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": "inventada"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Compra.objects.count(), 0)

    def test_acepta_csv_con_punto_y_coma_y_montos_con_puntos(self):
        csv = "Código de barras;Nombre;Cantidad;Costo unitario;Precio de venta\n7501234567895;;2;2.500;\n"
        r = self.subir(SimpleUploadedFile("m.csv", csv.encode("utf-8")))
        self.assertContains(r, "Todo en orden")
        self.assertEqual(r.context["revision"].filas[0].costo_unitario, "2500.00")

    def test_nombre_ambiguo_es_error(self):
        Producto.objects.create(empresa=self.empresa, sku="X1", nombre="Alimento", precio_venta=1)
        r = self.subir(_excel([["", "Alimento", 1, 1, "", 0]]))
        self.assertContains(r, "productos que se llaman")


_CON_SKU = ("Código de barras", "Nombre", "Cantidad", "Costo unitario", "Precio de venta", "Bonificadas",
            "Marca", "Categoría", "Presentación", "Mascota", "Código (SKU)", "Descripción")


class CargaMasivaConSkuYDescripcion(BaseCompras):
    """02/10/2026: columnas opcionales «Código (SKU)» y «Descripción».

    Sin el SKU, un producto nuevo recibía un código inventado y la foto —que se
    asocia por SKU— no se podía preparar antes; sin la descripción, salía sin
    texto en la web."""

    def setUp(self):
        super().setUp()
        self.producto.codigo_barras = "7501234567895"
        self.producto.save()
        self.client.force_login(self.usuario)

    def subir(self, archivo):
        return self.client.post(reverse("compras:carga_masiva"), {
            "proveedor_id": self.proveedor.pk, "factura_proveedor": "F-901", "forma_pago": "CON", "archivo": archivo})

    def confirmar(self, archivo):
        r = self.subir(archivo)
        self.assertIn("firma", r.context, msg=[f.errores for f in r.context["revision"].filas])
        return self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})

    def test_producto_nuevo_se_crea_con_el_sku_y_la_descripcion_de_la_fila(self):
        self.confirmar(_excel([["7852052752085", "Collar estampado", 12, 304.17, 850, 0, "", "", "", "Perro",
                                "75208", "Collar ajustable de 1 cm de ancho."]], _CON_SKU))
        nuevo = Producto.objects.get(sku="75208")
        self.assertEqual(nuevo.codigo_barras, "7852052752085")
        self.assertEqual(nuevo.descripcion, "Collar ajustable de 1 cm de ancho.")
        self.assertEqual(nuevo.stock_actual, Decimal("12"))

    def test_la_descripcion_conserva_los_renglones_de_las_vinetas(self):
        texto = "Collar básico.\n• Largo: 20 a 35 cm\n• Ancho: 1 cm"
        self.confirmar(_excel([["", "Collar", 1, 100, 500, 0, "", "", "", "", "C-1", texto]], _CON_SKU))
        self.assertEqual(Producto.objects.get(sku="C-1").descripcion, texto)

    def test_el_sku_reconoce_al_producto_existente_aunque_no_traiga_codigo_de_barras(self):
        self.confirmar(_excel([["", "", 3, 1520, "", 0, "", "", "", "", self.producto.sku, ""]], _CON_SKU))
        self.producto.refresh_from_db()
        self.assertEqual(Producto.objects.count(), 1)
        self.assertEqual(self.producto.stock_actual, Decimal("13"))

    def test_la_descripcion_solo_completa_la_vacia(self):
        self.producto.descripcion = "Texto puesto a mano"
        self.producto.save()
        self.confirmar(_excel([["", "", 1, 100, "", 0, "", "", "", "", self.producto.sku, "Otro texto"]], _CON_SKU))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.descripcion, "Texto puesto a mano")

    def test_sku_nuevo_con_codigo_de_barras_de_otro_producto_es_error(self):
        r = self.subir(_excel([["7501234567895", "Otra cosa", 1, 100, 500, 0, "", "", "", "", "NUEVO-1", ""]],
                              _CON_SKU))
        self.assertContains(r, "ya es del producto")
        self.assertNotIn("firma", r.context)

    def test_sku_de_un_producto_inactivo_es_error_en_la_vista_previa(self):
        Producto.objects.create(empresa=self.empresa, sku="VIEJO", nombre="Viejo", precio_venta=1, activo=False)
        r = self.subir(_excel([["", "Nuevo", 1, 100, 500, 0, "", "", "", "", "VIEJO", ""]], _CON_SKU))
        self.assertContains(r, "producto inactivo")
        self.assertNotIn("firma", r.context)

    def test_con_sku_no_se_confunde_con_otro_del_mismo_nombre(self):
        self.confirmar(_excel([["", self.producto.nombre, 2, 100, 500, 0, "", "", "", "", "VAR-2", ""]], _CON_SKU))
        self.assertTrue(Producto.objects.filter(sku="VAR-2").exists())
        self.assertEqual(Producto.objects.count(), 2)

    def test_descripcion_sin_columna_nombre_sigue_siendo_el_nombre(self):
        r = self.subir(_excel([["", "Pelota roja", 2, 100, 500]],
                              ("Código de barras", "Descripción", "Cantidad", "Costo unitario", "Precio de venta")))
        self.assertEqual(r.context["revision"].filas[0].nombre, "Pelota roja")
        self.assertEqual(r.context["revision"].filas[0].descripcion, "")

    def test_la_plantilla_trae_las_columnas_nuevas(self):
        r = self.client.get(reverse("compras:carga_masiva_plantilla"))
        encabezado = [c.value for c in load_workbook(io.BytesIO(r.content)).active[1]]
        self.assertIn("Código (SKU)", encabezado)
        self.assertIn("Descripción", encabezado)


@override_settings(IMPRESION_FORZAR_AGENTE=True, IMPRESORA_ETIQUETAS="Etiquetas de prueba")
class EtiquetasDeLaCompra(BaseCompras):
    """INV-08: una etiqueta por unidad recibida, bonificadas incluidas."""

    def test_encola_una_por_unidad(self):
        from .services import crear_y_recibir_compra

        compra = crear_y_recibir_compra(
            proveedor=self.proveedor, sucursal=self.sucursal, usuario=self.usuario,
            lineas=[{"producto": self.producto, "cantidad": Decimal("3"), "cantidad_bonificada": Decimal("1"),
                     "costo_unitario": Decimal("1000")}])
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("impresion:etiquetas_compra", args=[compra.pk]), HTTP_ACCEPT="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(TrabajoImpresion.objects.filter(tipo=TrabajoImpresion.ETIQUETA).count(), 4)


class IvaDeLaFacturaComoSeLee(BaseCompras):
    """02/10/2026: el IVA «39.534,28» (como sale en la factura de Special Care)
    reventaba al confirmar con un «Datos inválidos» sin explicación."""

    def setUp(self):
        super().setUp()
        from core.models import Empresa
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL
        self.empresa.save()
        self.client.force_login(self.usuario)

    def subir(self, iva):
        return self.client.post(reverse("compras:carga_masiva"), {
            "proveedor_id": self.proveedor.pk, "factura_proveedor": "FE-1", "forma_pago": "CON", "iva": iva,
            "archivo": _excel([["", "Saco nuevo", 10, 8517.60, 19290, 0]])})

    def test_iva_con_punto_de_miles_y_coma_decimal(self):
        r = self.subir("39.534,28")
        self.assertIn("firma", r.context)
        self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})
        self.assertEqual(Compra.objects.get().iva, Decimal("39534.28"))

    def test_iva_que_no_es_numero_se_avisa_en_la_vista_previa(self):
        r = self.subir("treinta mil")
        self.assertContains(r, "no es un monto válido")
        self.assertNotIn("firma", r.context)
        self.assertEqual(Compra.objects.count(), 0)
