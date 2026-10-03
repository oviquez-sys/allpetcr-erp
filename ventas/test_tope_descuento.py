"""Tope de descuento en el POS (02/10/2026).

El gerente ve, disfrazado de código interno, hasta qué % puede descontar sin
vender bajo costo. Si alguna falla: o el tope dejó de ser el margen real, o
se le empezó a mandar el costo (disfrazado) al navegador del cajero.
"""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.urls import reverse

from catalogo.models import Producto
from inventario.services import registrar_movimiento

from .test_auditoria_2026_09 import Base
from .views import _filas_pos


class TopeDeDescuento(Base):
    def setUp(self):
        super().setUp()
        self.cajero = User.objects.create_user("maria", password="c", is_staff=True)
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.producto.refresh_from_db()   # el kardex le puso el costo después de crearlo

    def fila(self, producto):
        return _filas_pos(Producto.objects.filter(pk=producto.pk), con_tope=True)[0]

    def test_es_el_margen_sin_iva_redondeado_hacia_abajo(self):
        # ₡5.300 con IVA = ₡4.690,27 sin IVA; costo ₡1.500 → margen 68,02 %.
        self.assertEqual(self.producto.margen_pct, Decimal("68.02"))
        self.assertEqual(self.fila(self.producto)["tope"], 68)

    def test_descontar_el_tope_nunca_deja_la_venta_bajo_costo(self):
        tope = Decimal(self.fila(self.producto)["tope"])
        precio_sin_iva_con_descuento = self.producto.precio_sin_iva * (1 - tope / 100)
        self.assertGreaterEqual(precio_sin_iva_con_descuento, self.producto.costo_promedio)

    def test_bajo_costo_el_tope_es_cero(self):
        caro = Producto.objects.create(empresa=self.empresa, sku="B1", nombre="Bajo costo",
                                       precio_venta=Decimal("1000"), impuesto=self.iva)
        registrar_movimiento(producto=caro, bodega=self.bodega, tipo="INI", cantidad=Decimal("2"),
                             costo_unitario=Decimal("2000"), referencia="INI")
        self.assertEqual(self.fila(caro)["tope"], 0)

    def test_el_gerente_lo_recibe_en_el_pos_y_al_escanear(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("ventas:pos"))
        self.assertEqual(r.context["productos"][0]["tope"], 68)
        d = self.client.get(reverse("ventas:producto_por_codigo"),
                            {"q": self.producto.codigo_barras}).json()
        self.assertEqual(d["producto"]["tope"], 68)

    def test_el_cajero_no_lo_recibe(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("ventas:pos"))
        self.assertNotIn("tope", r.context["productos"][0])
        d = self.client.get(reverse("ventas:producto_por_codigo"),
                            {"q": self.producto.codigo_barras}).json()
        self.assertNotIn("tope", d["producto"])
