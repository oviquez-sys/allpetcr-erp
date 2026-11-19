"""«Publicar en la página web» (18/11/2026).

Pedido de Oscar: un producto sin publicar se sigue vendiendo en caja y sigue
en inventario, pero el sitio no lo muestra, no lo encuentra, no lo abre y no
lo deja comprar. Estas pruebas recorren TODAS las puertas de la API; si
mañana se agrega una nueva sin pasar por `catalogo.consultas.publicados_en_web`,
la que corresponda tiene que sumarse acá.
"""
import importlib
from decimal import Decimal

from django.apps import apps
from django.urls import reverse

from caja.services import abrir_caja
from catalogo import redes
from catalogo.consultas import publicados_en_web
from catalogo.models import Producto
from inventario.services import registrar_movimiento
from pedidos.models import AvisoDisponibilidad, Pedido, PedidoPorConfirmar, ReservaStock

from .tests import BaseAPI


class SinPublicar(BaseAPI):
    def setUp(self):
        super().setUp()
        self.oculto = Producto.objects.create(
            empresa=self.empresa, sku="VTM-NEXG-S", nombre="NexGard pelota", categoria=self.cat,
            mascota="Perro", precio_venta=Decimal("9000"), publicar_web=False, destacado_home=True,
        )
        registrar_movimiento(producto=self.oculto, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("10"), costo_unitario=Decimal("4000"), referencia="INI")

    def get(self, nombre, *args, **params):
        return self.client_autenticado.get(reverse(f"api:{nombre}", args=args), params)

    def post(self, nombre, datos):
        return self.client_autenticado.post(reverse(f"api:{nombre}"), datos, format="json")

    def skus(self, r):
        datos = r.json()
        filas = datos["results"] if isinstance(datos, dict) and "results" in datos else datos
        return {p["sku"] for p in filas}

    def test_por_defecto_se_publica(self):
        self.assertTrue(self.producto.publicar_web)

    def test_no_sale_en_el_catalogo_ni_en_la_busqueda_ni_en_la_vitrina(self):
        self.assertEqual(self.skus(self.get("catalogo_productos")), {"API-1"})
        self.assertNotIn("VTM-NEXG-S", self.skus(self.get("catalogo_productos", q="pelota")))
        self.assertNotIn("VTM-NEXG-S", self.skus(self.get("catalogo_productos", incluir_agotados="1")))

    def test_su_pagina_da_404(self):
        self.assertEqual(self.get("catalogo_producto_detalle", "VTM-NEXG-S").status_code, 404)
        self.assertEqual(self.get("catalogo_producto_detalle", "API-1").status_code, 200)

    def test_disponibilidad_da_404(self):
        self.assertEqual(self.get("disponibilidad", "VTM-NEXG-S").status_code, 404)

    def test_no_se_puede_apartar_ni_pedir_aviso(self):
        r = self.post("reservar_stock", {"sku": "VTM-NEXG-S", "cantidad": "1", "token_carrito": "c-1"})
        self.assertIn(r.status_code, (400, 404))
        self.assertFalse(ReservaStock.objects.exists())
        r = self.post("aviso_disponibilidad", {"sku": "VTM-NEXG-S", "email": "a@x.com"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(AvisoDisponibilidad.objects.exists())

    def test_no_se_puede_pedir_en_el_carrito(self):
        r = self.post("pedidos", {"cliente_nombre": "Ana", "cliente_telefono": "8888-1234",
                                  "direccion_texto": "Heredia", "lineas": [{"sku": "VTM-NEXG-S", "cantidad": "1"}]})
        self.assertIn(r.status_code, (400, 404))
        self.assertFalse(Pedido.objects.exists())
        r = self.post("pedido_por_confirmar", {"clave": "k-1", "nombre": "Ana", "telefono": "8888-1234",
                                               "entrega": "RET", "lineas": [{"sku": "VTM-NEXG-S", "cantidad": 1}]})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PedidoPorConfirmar.objects.exists())

    def test_la_caja_lo_sigue_vendiendo(self):
        from ventas.services import registrar_venta

        sesion = abrir_caja(sucursal=self.sucursal, usuario=self._gerente(), monto_apertura=Decimal("0"))
        factura = registrar_venta(sesion_caja=sesion, medio_pago="EFE", usuario=sesion.usuario,
                                  lineas=[{"producto_id": self.oculto.pk, "cantidad": Decimal("2")}])
        self.assertEqual(factura.estado, "EMI")
        self.oculto.refresh_from_db()
        self.assertEqual(self.oculto.stock_actual, Decimal("8"))

    def test_no_entra_al_catalogo_de_redes(self):
        # El PDF lleva QR y Facebook un enlace a su página, que daría 404.
        self.assertEqual(list(publicados_en_web(self.empresa)), [self.producto])
        Producto.objects.filter(pk=self.producto.pk).update(imagen="x.webp")
        Producto.objects.filter(pk=self.oculto.pk).update(imagen="y.webp")
        items, _ = redes.productos(self.empresa)
        self.assertEqual([i.producto.sku for i in items], ["API-1"])

    def _gerente(self):
        from django.contrib.auth.models import User
        return User.objects.create_user("gerente", is_staff=True, is_superuser=True)


class MigracionNexgard(BaseAPI):
    def test_desmarca_nexgard_y_spectra_y_nada_mas(self):
        for sku in ("VTM-NEXG-001", "vtm-nexs-xl", "VTM-NEXA-1", "VTM-OTRO"):
            Producto.objects.create(empresa=self.empresa, sku=sku, nombre=sku, precio_venta=Decimal("1"))
        migracion = importlib.import_module("catalogo.migrations.0016_producto_publicar_web")
        migracion.despublicar_nexgard(apps, None)
        sin_web = set(Producto.objects.filter(publicar_web=False).values_list("sku", flat=True))
        self.assertEqual(sin_web, {"VTM-NEXG-001", "vtm-nexs-xl"})
