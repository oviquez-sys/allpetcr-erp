"""Correcciones de la auditoría del 26/09/2026 en compras (INV-02, INV-03, INV-04)."""
import json
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.urls import reverse

from catalogo.codigos import es_interno
from catalogo.models import Producto

from .models import Compra
from .services import crear_compra
from .tests import BaseCompras


class CodigoDeBarrasDelProductoNuevo(BaseCompras):
    """INV-02: el producto creado en «Recibir mercadería» lleva el EAN-8 interno."""

    def crear(self, **extra):
        self.client.force_login(self.usuario)
        return self.client.post(reverse("compras:producto_nuevo"),
                                json.dumps({"nombre": "Juguete X", "precio_venta": 3000, **extra}),
                                content_type="application/json").json()

    def test_sin_codigo_de_fabrica_recibe_ean8_interno(self):
        cb = self.crear()["producto"]["codigo_barras"]
        self.assertEqual(len(cb), 8)
        self.assertTrue(es_interno(cb), cb)

    def test_conserva_el_codigo_de_fabrica(self):
        cb = self.crear(codigo_barras="7501234567895")["producto"]["codigo_barras"]
        self.assertEqual(cb, "7501234567895")

    def test_no_duplica_un_codigo_existente(self):
        self.producto.codigo_barras = "7501234567895"
        self.producto.save()
        r = self.crear(codigo_barras="7501234567895")
        self.assertFalse(r["ok"])
        self.assertEqual(Producto.objects.filter(codigo_barras="7501234567895").count(), 1)


class CompraEnUnSoloPaso(BaseCompras):
    """INV-03: si la recepción falla, no queda una compra borrador suelta."""

    def test_si_falla_recibir_no_queda_nada(self):
        self.client.force_login(self.usuario)
        cuerpo = {"proveedor_id": self.proveedor.pk,
                  "lineas": [{"producto_id": self.producto.pk, "cantidad": 2, "costo_unitario": 9000}]}
        with mock.patch("compras.services.recibir_compra", side_effect=ValidationError("falla simulada")):
            r = self.client.post(reverse("compras:registrar"), json.dumps(cuerpo), content_type="application/json")
        self.assertFalse(r.json()["ok"])
        self.assertEqual(Compra.objects.count(), 0)


class FacturaDeProveedorRepetida(BaseCompras):
    """INV-04: la misma factura del mismo proveedor no entra dos veces."""

    def compra(self, factura):
        return crear_compra(proveedor=self.proveedor, sucursal=self.sucursal, usuario=self.usuario,
                            factura_proveedor=factura,
                            lineas=[{"producto": self.producto, "cantidad": Decimal("1"), "costo_unitario": Decimal("1")}])

    def test_rechaza_la_segunda(self):
        self.compra("F-100")
        with self.assertRaises(ValidationError):
            self.compra(" f-100 ")

    def test_si_la_primera_se_anulo_se_puede_volver_a_ingresar(self):
        primera = self.compra("F-200")
        Compra.objects.filter(pk=primera.pk).update(estado=Compra.Estado.ANULADA)
        self.compra("F-200")

    def test_sin_numero_de_factura_no_se_compara(self):
        self.compra("")
        self.compra("")
        self.assertEqual(Compra.objects.count(), 2)
