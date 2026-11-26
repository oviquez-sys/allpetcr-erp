"""Costo de reposición (25/11/2026, catalogo/costos.py).

Caso real: NutriSource Cat-Kitten 12 lb, pagado 1 + 1 de regalo. El costo
promedio quedó a la mitad y el POS ofrecía un descuento máximo que la próxima
compra no aguanta. Estas pruebas fijan que el regalo no se cuele en las
decisiones de precio y descuento, y que la contabilidad siga igual.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from catalogo import promociones
from catalogo.costos import costo_para_decidir, costo_reposicion, revision
from catalogo.models import Producto, Promocion, PromocionProducto
from compras.models import Proveedor
from compras.services import crear_y_recibir_compra
from ventas.services import registrar_venta
from ventas.tests import BaseVentas
from ventas.views import _filas_pos


class CostoDeReposicion(BaseVentas):
    def setUp(self):
        super().setUp()
        self.proveedor = Proveedor.objects.create(empresa=self.empresa, nombre="Distribuidora")
        self.saco = Producto.objects.create(empresa=self.empresa, sku="NS-CK12", nombre="NutriSource Cat-Kitten 12 lb",
                                            precio_venta=Decimal("24375"))
        self.comprar(self.saco, 1, "22000", regalo=1)

    def comprar(self, producto, cantidad, costo, regalo=0, factura="F-1"):
        crear_y_recibir_compra(proveedor=self.proveedor, sucursal=self.sucursal, usuario=self.usuario,
                               factura_proveedor=factura,
                               lineas=[{"producto": producto, "cantidad": Decimal(cantidad),
                                        "cantidad_bonificada": Decimal(regalo), "costo_unitario": Decimal(costo)}])
        producto.refresh_from_db()

    def test_la_contabilidad_no_cambia_pero_se_decide_con_lo_que_cuesta_reponer(self):
        self.assertEqual(self.saco.costo_promedio, Decimal("11000"))     # 22.000 entre 2 sacos
        self.assertEqual(costo_reposicion(self.saco), Decimal("22000"))
        self.assertEqual(costo_para_decidir(self.saco), Decimal("22000"))

    def test_el_tope_del_pos_ya_no_cuenta_el_regalo(self):
        # Sin IVA (régimen de la prueba): (24.375 − 22.000) / 24.375 = 9,7 % → 9. Con el promedio daba 54.
        fila = _filas_pos(Producto.objects.filter(pk=self.saco.pk), con_tope=True)[0]
        self.assertEqual(fila["tope"], 9)

    def vender(self, **linea):
        return registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                               lineas=[{"producto_id": self.saco.pk, "cantidad": 1, **linea}],
                               permitir_descuento_alto=True)

    def test_la_caja_frena_el_descuento_que_no_alcanza_para_reponer(self):
        with self.assertRaisesMessage(ValidationError, "reponerlo"):
            self.vender(descuento_pct=12)      # con el promedio pasaba: 21.450 > 11.000
        self.assertEqual(self.vender(descuento_pct=9).estado, "EMI")

    def test_sin_descuento_el_precio_de_lista_se_vende_aunque_no_alcance(self):
        # El precio de lista lo decide el gerente; la lista «Se venden perdiendo» lo avisa.
        Producto.objects.filter(pk=self.saco.pk).update(precio_venta=Decimal("20000"))
        self.saco.refresh_from_db()
        self.assertEqual(self.vender().total, Decimal("20000"))

    def test_una_compra_solo_de_regalo_no_cambia_la_reposicion(self):
        self.comprar(self.saco, 0, "0", regalo=1, factura="F-2")
        self.assertEqual(costo_reposicion(self.saco), Decimal("22000"))

    def test_sin_compras_manda_el_promedio(self):
        self.producto.refresh_from_db()     # el de BaseVentas: entró por inventario inicial
        self.assertIsNone(costo_reposicion(self.producto))
        self.assertEqual(costo_para_decidir(self.producto), self.producto.costo_promedio)

    def test_la_unidad_suelta_usa_la_caja(self):
        sobre = Producto.objects.create(empresa=self.empresa, sku="NS-CK12-U", nombre="Sobre", precio_venta=1)
        Producto.objects.filter(pk=self.saco.pk).update(unidad_suelta=sobre, unidades_por_empaque=4)
        self.assertEqual(costo_reposicion(sobre), Decimal("5500"))

    def test_la_promocion_no_se_activa_si_no_alcanza_para_reponer(self):
        hoy = timezone.localdate()
        promo = Promocion.objects.create(empresa=self.empresa, nombre="Black Friday", descuento_pct=20,
                                         inicio=hoy, fin=hoy + timedelta(days=3))
        item = PromocionProducto.objects.create(promocion=promo, producto=self.saco)
        with self.assertRaises(ValidationError):
            promociones.activar(promo)
        # 6 y no 9: el precio de oferta se redondea hacia abajo a precio bonito.
        self.assertEqual(promociones.fila(item)["max_pct"], 6)

    def test_la_revision_lo_encuentra(self):
        barato = Producto.objects.create(empresa=self.empresa, sku="X-1", nombre="Arena", precio_venta=Decimal("5000"))
        self.comprar(barato, 2, "6000", factura="F-3")
        datos = revision(self.empresa)
        fila = next(f for f in datos["rebajados"] if f["producto"] == self.saco)
        self.assertEqual((fila["tope_antes"], fila["tope_ahora"]), (54, 9))
        self.assertEqual(fila["regalo"].cantidad_bonificada, 1)
        self.assertEqual([f["producto"] for f in datos["perdiendo"]], [barato])
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("inventario:costos_regalias"))
        self.assertContains(r, "NutriSource Cat-Kitten")
        self.assertContains(r, "Arena")


class PantallasNoInducenAError(CostoDeReposicion):
    """Oscar (25/11/2026): «todo debe estar corregido de forma que no induzca
    a ningún error». Cada pantalla que muestra margen o propone un costo usa
    lo que cuesta reponer y avisa cuando el promedio vino rebajado."""

    def test_el_margen_del_producto_es_con_lo_que_cuesta_reponer(self):
        self.assertTrue(self.saco.costo_rebajado)
        self.assertEqual(self.saco.costo_decision, Decimal("22000"))
        self.assertEqual(self.saco.margen_pct, Decimal("9.74"))
        self.assertEqual(self.saco.ganancia_unitaria, Decimal("2375"))

    def test_precios_ajustes_y_admin_lo_muestran(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("catalogo:precios"), {"q": "NutriSource"})
        self.assertContains(r, "por regalo")
        self.assertContains(r, "9,7%")
        r = self.client.get(reverse("catalogo:precio_producto", args=[self.saco.pk]))
        self.assertContains(r, "Rebajado por unidades regaladas")
        r = self.client.get(reverse("inventario:ajuste_producto", args=[self.saco.pk]))
        self.assertContains(r, "Cuesta reponerlo")
        r = self.client.get(reverse("admin:catalogo_producto_changelist"))
        self.assertContains(r, "9.74%")

    def test_recibir_mercaderia_propone_lo_que_costo_una_unidad_pagada(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("compras:nueva"))
        p = next(x for x in r.context["productos"] if x["id"] == self.saco.pk)
        self.assertEqual((p["costo_promedio"], p["costo_reposicion"], p["costo_decidir"]), (11000, 22000, 22000))
