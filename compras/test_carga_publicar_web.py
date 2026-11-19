"""Columna «Publicar en web» de la carga desde Excel (18/11/2026).

Sí / No / vacío. Vacío: el nuevo se publica (salvo un NexGard) y el
existente queda como está. Un Sí o No explícito cambia al existente.
"""
from decimal import Decimal
from itertools import count

from django.urls import reverse

from catalogo.models import Producto

from .test_carga_masiva import _excel
from .tests import BaseCompras

_FACTURAS = count(1)
ENCABEZADO = ("Código (SKU)", "Nombre", "Cantidad", "Costo unitario", "Precio de venta", "Publicar en web")


class ColumnaPublicarEnWeb(BaseCompras):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def subir(self, filas, encabezado=ENCABEZADO):
        return self.client.post(reverse("compras:carga_masiva"), {
            "proveedor_id": self.proveedor.pk, "factura_proveedor": f"F-{next(_FACTURAS)}", "forma_pago": "CON",
            "archivo": _excel(filas, encabezado)})

    def confirmar(self, filas, encabezado=ENCABEZADO):
        r = self.subir(filas, encabezado)
        self.assertIn("firma", r.context, r.context.get("revision") and
                      [f.errores for f in r.context["revision"].filas])
        return self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})

    def web(self, sku):
        return Producto.objects.get(sku=sku).publicar_web

    def test_nuevos_si_no_y_vacio(self):
        self.confirmar([["N-1", "Pelota", 2, 500, 1500, "Sí"],
                        ["N-2", "Cuerda", 2, 500, 1500, "no"],
                        ["N-3", "Hueso", 2, 500, 1500, ""]])
        self.assertTrue(self.web("N-1"))
        self.assertFalse(self.web("N-2"))
        self.assertTrue(self.web("N-3"))

    def test_un_nexgard_nuevo_sin_columna_entra_sin_publicar_y_se_avisa(self):
        r = self.subir([["VTM-NEXG-XL", "NexGard XL", 3, 8000, 15000, ""]])
        self.assertContains(r, "Es un NexGard")
        self.assertContains(r, "No se publica en la página web")
        self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})
        self.assertFalse(self.web("VTM-NEXG-XL"))

    def test_un_nexgard_con_si_explicito_se_publica(self):
        self.confirmar([["VTM-NEXS-M", "NexGard Spectra M", 3, 8000, 15000, "Sí"]])
        self.assertTrue(self.web("VTM-NEXS-M"))

    def test_existente_vacio_no_se_toca_y_explicito_si(self):
        Producto.objects.filter(pk=self.producto.pk).update(publicar_web=False)
        self.confirmar([["P-001", "", 1, 10000, "", ""]])
        self.assertFalse(self.web("P-001"))
        r = self.subir([["P-001", "", 1, 10000, "", "Si"]])
        self.assertContains(r, "Pasa a publicarse en la página web")
        self.client.post(reverse("compras:carga_masiva_confirmar"), {"firma": r.context["firma"]})
        self.assertTrue(self.web("P-001"))
        self.confirmar([["P-001", "", 1, 10000, "", "NO"]])
        self.assertFalse(self.web("P-001"))
        self.assertEqual(Producto.objects.get(sku="P-001").stock_actual, Decimal("13"))

    def test_un_valor_raro_es_error(self):
        r = self.subir([["N-9", "Pelota", 2, 500, 1500, "tal vez"]])
        self.assertContains(r, "escriba Sí o No")
        self.assertNotIn("firma", r.context)

    def test_un_excel_sin_la_columna_funciona_igual(self):
        self.confirmar([["N-5", "Pelota", 2, 500, 1500]], encabezado=ENCABEZADO[:5])
        self.assertTrue(self.web("N-5"))

    def test_la_plantilla_trae_la_columna(self):
        import io

        from openpyxl import load_workbook
        r = self.client.get(reverse("compras:carga_masiva_plantilla"))
        encabezado = [c.value for c in load_workbook(io.BytesIO(r.content)).active[1]]
        self.assertIn("Publicar en web", encabezado)
