"""Promociones (04/11/2026, pedido de Oscar).

Lo que no se puede romper: la caja aplica la oferta sola y cobra lo mismo que
muestra la web; no se suma al cupón (gana el mayor) y el cupón no se quema si
no rindió; bajo costo solo si un gerente lo marcó; nada aplica fuera de
fechas o en borrador; el % anunciado nunca se queda corto.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from catalogo.models import CambioPrecio, Producto, Promocion, PromocionProducto
from catalogo.promociones import (activar, agregar, oferta_de, precio_oferta, precio_vigente, sugeridos,
                                  terminar, vigentes)
from impresion.tiquete import bytes_tiquete
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta
from ventas.services import registrar_venta
from ventas.test_auditoria_2026_09 import Base

HOY = timezone.localdate


class ConPromo(Base):
    """Producto de ₡5.300 con costo ₡1.500 (margen amplio)."""

    def setUp(self):
        super().setUp()
        self.promo = Promocion.objects.create(empresa=self.empresa, nombre="Black Friday", descuento_pct=40,
                                              inicio=HOY(), fin=HOY() + timedelta(days=3))
        self.item = PromocionProducto.objects.create(promocion=self.promo, producto=self.producto)
        activar(self.promo)
        self.promo.refresh_from_db()
        self.cajero = User.objects.create_user("francisco", password="x", is_staff=True)
        self.cajero.groups.add(Group.objects.get(name="Cajero"))


class PrecioDeOferta(ConPromo):
    def test_redondea_hacia_abajo_a_precio_bonito(self):
        # 5.300 × 60 % = 3.180 exacto → 3.090 (bonito, nunca más caro).
        self.assertEqual(precio_oferta(Decimal("5300"), 40), Decimal("3090"))
        self.assertEqual(precio_oferta(Decimal("26900"), 40), Decimal("16090"))
        for precio in (990, 1250, 5300, 18900, 26900, 59900):
            for pct in (10, 25, 40, 50):
                o = precio_oferta(Decimal(precio), pct)
                self.assertLessEqual(o, Decimal(precio) * (100 - pct) / 100, (precio, pct))

    def test_solo_aplica_activa_y_en_fechas(self):
        self.assertIn(self.producto.pk, vigentes(self.empresa))
        self.assertFalse(vigentes(self.empresa, fecha=HOY() + timedelta(days=4)))
        self.promo.estado = Promocion.Estado.BORRADOR
        self.promo.save()
        self.assertFalse(vigentes(self.empresa))
        self.assertEqual(precio_vigente(self.producto), Decimal("5300"))


class LaCajaLaAplicaSola(ConPromo):
    def test_venta_con_la_promo(self):
        f = registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.cajero,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 2}])
        linea = f.lineas.get()
        self.assertEqual(f.total, Decimal("6180"))                 # 2 × 3.090
        self.assertEqual(linea.descuento_monto, Decimal("4420"))
        self.assertEqual(linea.promocion, self.promo)
        # El cajero (tope 15 %) no frena la promoción: la autorizó el negocio.
        self.assertGreater(linea.descuento_pct, 15)

    def test_gana_el_descuento_mayor_del_cajero(self):
        f = registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 50}],
                            permitir_descuento_alto=True)
        self.assertIsNone(f.lineas.get().promocion)
        self.assertEqual(f.total, Decimal("2650"))

    def test_el_cupon_no_se_quema_si_la_promo_da_mas(self):
        from manada.models import Regalia
        from manada.services import registrar_miembro
        Regalia.objects.create(empresa=self.empresa, porcentaje=Decimal("10"), texto_cliente="10 %")
        cupon = registrar_miembro(empresa=self.empresa, email="ana@x.com", nombre="Ana", verificado=True).cupon
        f = registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.cajero, cupon=cupon.codigo,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])
        cupon.refresh_from_db()
        self.assertIsNone(cupon.usado_en)                            # sigue disponible
        self.assertEqual(f.total, Decimal("3090"))

    def test_bajo_costo_solo_si_el_gerente_lo_marco(self):
        self.item.descuento_pct = 80                                 # 5.300 → 1.050: bajo el costo de 1.500
        self.item.save()
        with self.assertRaises(ValidationError):
            registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.cajero,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])
        self.item.permitir_bajo_costo = True
        self.item.save()
        f = registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.cajero,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])
        self.assertEqual(f.lineas.get().promocion, self.promo)

    def test_el_tiquete_dice_la_promo_y_cuanto_ahorro(self):
        f = self.vender()
        papel = bytes_tiquete(FacturaVenta.objects.get(pk=f.pk)).decode("cp850")
        self.assertIn("Black Friday 41%", papel)                     # 2.210 de 5.300 = 41,7 %
        self.assertIn("Usted ahorró", papel)

    def test_el_pos_recibe_la_oferta(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("ventas:pos"))
        datos = r.context["productos_json"] if "productos_json" in r.context else None
        html = r.content.decode()
        self.assertIn('"oferta": {"precio": 3090.0, "pct": 40, "nombre": "Black Friday"}', html.replace("\\u0022", '"'))


class WebYPedidos(ConPromo):
    def test_la_api_publica_precio_de_oferta_y_tachado(self):
        from api.serializers import ProductoListaSerializer
        datos = ProductoListaSerializer(Producto.objects.get(pk=self.producto.pk)).data
        self.assertEqual(datos["precio_venta"], 3090.0)
        self.assertEqual(datos["precio_antes"], 5300.0)
        self.assertEqual(datos["oferta"]["pct"], 40)
        self.assertEqual(datos["oferta"]["nombre"], "Black Friday")
        self.assertEqual(datos["oferta"]["hasta"], (HOY() + timedelta(days=3)).isoformat())
        self.assertNotIn("stock_actual", datos)

    def test_sin_promo_no_hay_tachado(self):
        terminar(self.promo)
        from api.serializers import ProductoListaSerializer
        datos = ProductoListaSerializer(Producto.objects.get(pk=self.producto.pk)).data
        self.assertEqual((datos["precio_venta"], datos["precio_antes"], datos["oferta"]), (5300.0, None, None))

    def test_el_pedido_web_cobra_la_oferta(self):
        from pedidos.services import crear_pedido
        p = crear_pedido(empresa=self.empresa, sucursal=self.sucursal, cliente_nombre="Ana",
                         cliente_telefono="88888888", lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])
        self.assertEqual(p.lineas.get().precio_unitario, Decimal("3090"))


class Reglas(ConPromo):
    def test_un_producto_no_puede_estar_en_dos_promos_a_la_vez(self):
        otra = Promocion.objects.create(empresa=self.empresa, nombre="Otra", descuento_pct=10,
                                        inicio=HOY(), fin=HOY() + timedelta(days=1))
        agregar(otra, self.producto)
        with self.assertRaises(ValidationError):
            activar(otra)

    def test_no_activa_si_queda_bajo_costo_sin_permiso(self):
        otra = Promocion.objects.create(empresa=self.empresa, nombre="Liquidación", descuento_pct=85,
                                        inicio=HOY() + timedelta(days=10), fin=HOY() + timedelta(days=11))
        agregar(otra, self.producto)
        with self.assertRaisesMessage(ValidationError, "por debajo del costo"):
            activar(otra)

    def test_terminar_ya_devuelve_el_precio_hoy_mismo(self):
        terminar(self.promo)
        self.assertIsNone(oferta_de(Producto.objects.get(pk=self.producto.pk)))

    def test_sugeridos_son_los_que_no_se_venden(self):
        parado = Producto.objects.create(empresa=self.empresa, sku="P2", nombre="Cama vieja",
                                         precio_venta=Decimal("20000"), impuesto=self.iva)
        registrar_movimiento(producto=parado, bodega=self.bodega, tipo="INI", cantidad=Decimal("3"),
                             costo_unitario=Decimal("8000"), referencia="INI")
        from inventario.models import MovimientoInventario
        MovimientoInventario.objects.filter(producto=parado).update(fecha=timezone.now() - timedelta(days=90))
        nombres = [p.nombre for p in sugeridos(self.empresa)]
        self.assertIn("Cama vieja", nombres)
        self.assertNotIn("Arnés", nombres)                           # ya está en oferta


class Pantalla(ConPromo):
    def setUp(self):
        super().setUp()
        self.producto.codigo_barras = "7501234567890"
        self.producto.save()
        self.client.force_login(self.usuario)
        self.nueva = Promocion.objects.create(empresa=self.empresa, nombre="Navidad", descuento_pct=25,
                                              inicio=HOY() + timedelta(days=20), fin=HOY() + timedelta(days=25))
        self.otro = Producto.objects.create(empresa=self.empresa, sku="ZDG-1", nombre="Collar",
                                            precio_venta=Decimal("14900"), impuesto=self.iva,
                                            codigo_barras="7890000000001")

    def url(self):
        return reverse("catalogo:promocion", args=[self.nueva.pk])

    def test_escanear_con_la_pistola_agrega_y_devuelve_la_tabla(self):
        r = self.client.post(self.url(), {"accion": "agregar", "codigo": "7890000000001"},
                             HTTP_ACCEPT="application/json")
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertIn("Collar", d["tabla"])
        self.assertIn("₡11.090", d["tabla"])                          # 14.900 × 75 % = 11.175 → 11.090
        r = self.client.post(self.url(), {"accion": "agregar", "codigo": "no-existe"}, HTTP_ACCEPT="application/json")
        self.assertFalse(r.json()["ok"])

    def test_buscar_por_nombre_y_agregar_con_un_clic(self):
        """09/11/2026: un producto con el código de barras sin registrar no se
        podía agregar. Ahora se busca por nombre y se elige de la lista."""
        buscar = reverse("catalogo:promocion_buscar", args=[self.nueva.pk])
        d = self.client.get(buscar, {"q": "collar"}).json()
        self.assertEqual([x["nombre"] for x in d["resultados"]], ["Collar"])
        self.assertFalse(d["resultados"][0]["ya"])
        self.assertIn("miniatura", d["resultados"][0])
        r = self.client.post(self.url(), {"accion": "agregar_id", "producto": self.otro.pk},
                             HTTP_ACCEPT="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertTrue(self.nueva.items.filter(producto=self.otro).exists())
        self.assertTrue(self.client.get(buscar, {"q": "collar"}).json()["resultados"][0]["ya"])
        self.assertEqual(self.client.get(buscar, {"q": "c"}).json()["resultados"], [])    # 1 letra no busca

    def test_enter_con_un_nombre_muestra_la_lista(self):
        """Oscar escribía «special» y apretaba Enter: salía «No encontré el código»."""
        r = self.client.post(self.url(), {"accion": "agregar", "codigo": "collar"}, HTTP_ACCEPT="application/json")
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertEqual([x["nombre"] for x in d["resultados"]], ["Collar"])
        self.assertFalse(self.nueva.items.exists())                     # no agrega solo: se elige
        r = self.client.post(self.url(), {"accion": "agregar", "codigo": "zzzz"}, HTTP_ACCEPT="application/json")
        self.assertFalse(r.json()["ok"])

    def test_buscar_solo_gerente(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("catalogo:promocion_buscar", args=[self.nueva.pk]), {"q": "collar"})
        self.assertNotEqual(r.status_code, 200)

    def test_cambiar_el_pct_de_un_producto(self):
        item, _ = agregar(self.nueva, self.otro)
        self.client.post(self.url(), {"accion": "pct", "item": item.pk, "valor": "40"}, HTTP_ACCEPT="application/json")
        item.refresh_from_db()
        self.assertEqual(item.pct, 40)

    def test_avisa_si_el_precio_subio_hace_poco(self):
        CambioPrecio.objects.create(producto=self.otro, valor_anterior=Decimal("12900"), valor_nuevo=Decimal("14900"))
        agregar(self.nueva, self.otro)
        r = self.client.get(self.url())
        self.assertContains(r, "El precio subió")

    def test_activar_desde_la_pantalla(self):
        agregar(self.nueva, self.otro)
        r = self.client.post(self.url(), {"accion": "activar"})
        self.assertEqual(r.status_code, 302)
        self.nueva.refresh_from_db()
        self.assertEqual(self.nueva.estado, Promocion.Estado.ACTIVA)
        r = self.client.get(reverse("catalogo:promociones"))
        self.assertContains(r, "Programadas")

    def test_el_cajero_no_entra(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("catalogo:promociones"))
        self.assertNotEqual(r.status_code, 200)

    def test_etiquetas_apagadas_por_defecto(self):
        # Decisión de Oscar (04/11): no reetiquetar la tienda por ahora.
        r = self.client.get(reverse("catalogo:promocion", args=[self.promo.pk]))
        self.assertNotContains(r, "Imprimir etiquetas de oferta")
        self.client.post(reverse("catalogo:promocion", args=[self.promo.pk]), {"accion": "etiquetas"})
        from impresion.models import TrabajoImpresion
        self.assertEqual(TrabajoImpresion.objects.filter(tipo="etiqueta").count(), 0)

    @override_settings(PROMO_ETIQUETAS=True)
    def test_etiqueta_de_oferta(self):
        from impresion.etiqueta import imagen_etiqueta_oferta
        o = oferta_de(Producto.objects.get(pk=self.producto.pk))
        from impresion.etiqueta import imagen_etiqueta
        img = imagen_etiqueta_oferta(self.producto, o)
        self.assertEqual(img.size, imagen_etiqueta(self.producto).size)    # mismo rollo
        r = self.client.post(reverse("catalogo:promocion", args=[self.promo.pk]), {"accion": "etiquetas"})
        self.assertEqual(r.status_code, 302)
        from impresion.models import TrabajoImpresion
        self.assertEqual(TrabajoImpresion.objects.filter(tipo="etiqueta").count(), 1)

    def test_lista_para_marcar(self):
        r = self.client.get(reverse("catalogo:promocion", args=[self.promo.pk]))
        self.assertContains(r, reverse("catalogo:promocion_lista", args=[self.promo.pk]))
        r = self.client.get(reverse("catalogo:promocion_lista", args=[self.promo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.producto.nombre)
        self.assertContains(r, "lista para marcar")
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("catalogo:promocion_lista", args=[self.promo.pk]))
        self.assertNotEqual(r.status_code, 200)
