from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from catalogo.models import Categoria, Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from pedidos.models import AvisoDisponibilidad, Pedido, ReservaStock


class BaseAPI(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central", activa=True)
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        self.cat = Categoria.objects.create(nombre="Juguetes")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="API-1", nombre="Pelota de goma", categoria=self.cat,
            marca="AllPet", mascota="Perro", precio_venta=Decimal("3500"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("20"), costo_unitario=Decimal("1000"), referencia="INI",
        )
        self.producto.refresh_from_db()

        usuario_sitio = User.objects.create_user("sitio-web")
        self.token = Token.objects.create(user=usuario_sitio)
        self.client = APIClient()
        self.client_autenticado = APIClient()
        self.client_autenticado.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")


class Autenticacion(BaseAPI):
    def test_catalogo_exige_token(self):
        r = self.client.get(reverse("api:catalogo_productos"))
        self.assertEqual(r.status_code, 401)

    def test_token_invalido_se_rechaza(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token no-existe")
        r = self.client.get(reverse("api:catalogo_productos"))
        self.assertEqual(r.status_code, 401)

    def test_con_token_valido_entra(self):
        r = self.client_autenticado.get(reverse("api:catalogo_productos"))
        self.assertEqual(r.status_code, 200)


class CatalogoProductos(BaseAPI):
    def test_lista_paginada(self):
        r = self.client_autenticado.get(reverse("api:catalogo_productos"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("results", r.data)
        self.assertIn("count", r.data)
        self.assertEqual(r.data["count"], 1)

    def test_filtro_por_mascota(self):
        Producto.objects.create(
            empresa=self.empresa, sku="API-2", nombre="Rascador", mascota="Gato", precio_venta=Decimal("8000"),
        )
        r = self.client_autenticado.get(reverse("api:catalogo_productos"), {"mascota": "Gato"})
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["sku"], "API-2")

    def test_filtro_de_busqueda_por_nombre_o_sku(self):
        r = self.client_autenticado.get(reverse("api:catalogo_productos"), {"q": "pelota"})
        self.assertEqual(r.data["count"], 1)

    def test_producto_sin_precio_no_aparece(self):
        Producto.objects.create(empresa=self.empresa, sku="API-3", nombre="Sin precio", precio_venta=Decimal("0"))
        r = self.client_autenticado.get(reverse("api:catalogo_productos"))
        self.assertEqual(r.data["count"], 1)  # sigue siendo solo API-1

    def test_disponible_es_booleano_no_cantidad(self):
        r = self.client_autenticado.get(reverse("api:catalogo_productos"))
        producto = r.data["results"][0]
        self.assertEqual(producto["disponible"], True)
        self.assertNotIn("stock_actual", producto)

    def test_categoria_id_no_categoria_nombre(self):
        """La forma tiene que calzar con la que ya lee allpetcr-web/lib/data.ts
        (misma forma que exportar_catalogo_web.py)."""
        r = self.client_autenticado.get(reverse("api:catalogo_productos"))
        producto = r.data["results"][0]
        self.assertEqual(producto["categoria_id"], self.cat.pk)
        self.assertNotIn("categoria_nombre", producto)


class CategoriasAPI(BaseAPI):
    def test_lista_sin_paginar(self):
        from catalogo.models import Categoria
        hija = Categoria.objects.create(nombre="Pelotas", padre=self.cat)
        r = self.client_autenticado.get(reverse("api:catalogo_categorias"))
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.data, list)  # no es {"results": [...]}
        nombres = {c["nombre"] for c in r.data}
        self.assertIn("Juguetes", nombres)
        self.assertIn("Pelotas", nombres)

    def test_padre_id_es_null_para_categoria_raiz(self):
        r = self.client_autenticado.get(reverse("api:catalogo_categorias"))
        cat = next(c for c in r.data if c["nombre"] == "Juguetes")
        self.assertIsNone(cat["padre_id"])

    def test_padre_id_apunta_a_la_categoria_raiz(self):
        from catalogo.models import Categoria
        hija = Categoria.objects.create(nombre="Pelotas", padre=self.cat)
        r = self.client_autenticado.get(reverse("api:catalogo_categorias"))
        cat = next(c for c in r.data if c["nombre"] == "Pelotas")
        self.assertEqual(cat["padre_id"], self.cat.pk)


class CostoNuncaSaleDelERP(BaseAPI):
    """Regla dura del Bloque 3, ítem 18: si alguien agrega costo_promedio,
    margen_pct o markup_pct a un serializer de la API, ESTA prueba tiene
    que fallar. No depende de que el dato exista en la respuesta hoy — mira
    directo la definición del serializer."""

    CAMPOS_PROHIBIDOS = {"costo_promedio", "margen_pct", "markup_pct", "costo", "margen", "markup"}

    def test_lista_no_expone_costo_ni_margen(self):
        from api.serializers import ProductoListaSerializer
        campos = set(ProductoListaSerializer.Meta.fields)
        self.assertEqual(campos & self.CAMPOS_PROHIBIDOS, set())

    def test_detalle_no_expone_costo_ni_margen(self):
        from api.serializers import ProductoDetalleSerializer
        campos = set(ProductoDetalleSerializer.Meta.fields)
        self.assertEqual(campos & self.CAMPOS_PROHIBIDOS, set())

    def test_respuesta_real_no_trae_esos_campos(self):
        r = self.client_autenticado.get(
            reverse("api:catalogo_producto_detalle", args=[self.producto.sku])
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data.keys()) & self.CAMPOS_PROHIBIDOS, set())

    def test_stock_exacto_tampoco_se_expone(self):
        """No es solo costo: la cantidad exacta en existencia tampoco sale
        (regla ya vigente en exportar_catalogo_web.py, sostenida acá)."""
        r = self.client_autenticado.get(
            reverse("api:catalogo_producto_detalle", args=[self.producto.sku])
        )
        self.assertNotIn("stock_actual", r.data)


class Disponibilidad(BaseAPI):
    def test_disponible_true_con_stock(self):
        r = self.client_autenticado.get(reverse("api:disponibilidad", args=[self.producto.sku]))
        self.assertEqual(r.data, {"sku": "API-1", "disponible": True})

    def test_disponible_false_sin_stock(self):
        agotado = Producto.objects.create(empresa=self.empresa, sku="API-9", nombre="Agotado", precio_venta=Decimal("100"))
        r = self.client_autenticado.get(reverse("api:disponibilidad", args=[agotado.sku]))
        self.assertEqual(r.data["disponible"], False)

    def test_sku_inexistente_da_404(self):
        r = self.client_autenticado.get(reverse("api:disponibilidad", args=["NO-EXISTE"]))
        self.assertEqual(r.status_code, 404)


class AvisosDisponibilidadAPI(BaseAPI):
    def test_crea_aviso(self):
        r = self.client_autenticado.post(
            reverse("api:aviso_disponibilidad"), {"sku": self.producto.sku, "email": "a@x.com"},
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(AvisoDisponibilidad.objects.filter(producto=self.producto, email="a@x.com").exists())

    def test_sku_inexistente_se_rechaza(self):
        r = self.client_autenticado.post(
            reverse("api:aviso_disponibilidad"), {"sku": "NO-EXISTE", "email": "a@x.com"},
        )
        self.assertEqual(r.status_code, 400)

    def test_duplicado_no_falla_como_error_de_servidor(self):
        AvisoDisponibilidad.objects.create(producto=self.producto, email="a@x.com")
        r = self.client_autenticado.post(
            reverse("api:aviso_disponibilidad"), {"sku": self.producto.sku, "email": "a@x.com"},
        )
        self.assertLess(r.status_code, 500)
        self.assertEqual(AvisoDisponibilidad.objects.filter(producto=self.producto, email="a@x.com").count(), 1)


class ReservarStockAPI(BaseAPI):
    def test_reserva_ok(self):
        r = self.client_autenticado.post(reverse("api:reservar_stock"), {
            "sku": self.producto.sku, "cantidad": "2", "token_carrito": "carrito-abc",
        })
        self.assertEqual(r.status_code, 201)
        self.assertTrue(ReservaStock.objects.filter(producto=self.producto, token_carrito="carrito-abc").exists())

    def test_reserva_mayor_al_stock_se_rechaza(self):
        r = self.client_autenticado.post(reverse("api:reservar_stock"), {
            "sku": self.producto.sku, "cantidad": "999", "token_carrito": "carrito-abc",
        })
        self.assertEqual(r.status_code, 400)

    def test_faltan_datos(self):
        r = self.client_autenticado.post(reverse("api:reservar_stock"), {"sku": self.producto.sku})
        self.assertEqual(r.status_code, 400)


class PedidosAPI(BaseAPI):
    def _body(self, **extra):
        datos = {
            "cliente_nombre": "Cliente API", "cliente_telefono": "8888-1234",
            "direccion_texto": "100m norte de la plaza",
            "lineas": [{"sku": self.producto.sku, "cantidad": "2"}],
        }
        datos.update(extra)
        return datos

    def test_crea_pedido_y_descuenta_stock(self):
        r = self.client_autenticado.post(reverse("api:pedidos"), self._body(), format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["numero"].startswith("PED-"))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("18"))

    def test_sku_inexistente_no_crea_nada(self):
        r = self.client_autenticado.post(
            reverse("api:pedidos"),
            self._body(lineas=[{"sku": "NO-EXISTE", "cantidad": "1"}]),
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Pedido.objects.count(), 0)

    def test_idempotente_por_referencia_pago(self):
        body = self._body(referencia_pago="pago-web-1")
        r1 = self.client_autenticado.post(reverse("api:pedidos"), body, format="json")
        r2 = self.client_autenticado.post(reverse("api:pedidos"), body, format="json")
        self.assertEqual(r1.data["numero"], r2.data["numero"])
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("18"))  # una sola vez

    def test_sin_lineas_se_rechaza(self):
        r = self.client_autenticado.post(reverse("api:pedidos"), self._body(lineas=[]), format="json")
        self.assertEqual(r.status_code, 400)


class EstadoPedidoAPI(BaseAPI):
    def setUp(self):
        super().setUp()
        r = self.client_autenticado.post(reverse("api:pedidos"), {
            "cliente_nombre": "Cliente API", "cliente_telefono": "8888-5555",
            "direccion_texto": "Frente al parque",
            "lineas": [{"sku": self.producto.sku, "cantidad": "1"}],
        }, format="json")
        self.numero = r.data["numero"]

    def test_con_telefono_correcto_devuelve_el_estado(self):
        r = self.client_autenticado.get(
            reverse("api:pedido_estado", args=[self.numero]), {"telefono": "8888-5555"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["numero"], self.numero)
        self.assertEqual(len(r.data["lineas"]), 1)

    def test_sin_telefono_no_muestra_nada(self):
        r = self.client_autenticado.get(reverse("api:pedido_estado", args=[self.numero]))
        self.assertEqual(r.status_code, 404)

    def test_con_telefono_incorrecto_da_404_no_403(self):
        """404 y no 403 a propósito: no le confirma a quien adivina un
        número de pedido que el número SÍ existe."""
        r = self.client_autenticado.get(
            reverse("api:pedido_estado", args=[self.numero]), {"telefono": "0000-0000"},
        )
        self.assertEqual(r.status_code, 404)

    def test_numero_inexistente_da_404(self):
        r = self.client_autenticado.get(
            reverse("api:pedido_estado", args=["PED-99999999"]), {"telefono": "8888-5555"},
        )
        self.assertEqual(r.status_code, 404)


@override_settings(
    # El resto de la suite corre con DummyCache (ver config/settings.py) para
    # que la caché del dashboard no arrastre datos entre pruebas. Pero el
    # límite de tasa de DRF SE GUARDA en la caché — con DummyCache nunca
    # recuerda nada y esta prueba no probaría nada. Se activa una caché real
    # solo acá, donde es justo lo que se quiere verificar.
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class LimiteDeTasa(BaseAPI):
    """Confirma que el límite de tasa (ítem 17) está realmente conectado,
    no solo declarado en settings. Se baja la tasa a 2/min para la prueba —
    esperar a que se agote la de producción haría la suite eterna.

    `SimpleRateThrottle.THROTTLE_RATES` se lee de `api_settings` UNA sola
    vez, al importarse `rest_framework.throttling` — `override_settings`
    sobre `REST_FRAMEWORK` no lo refresca (es un gotcha conocido de DRF).
    Por eso se parchea la clase directamente en vez de la configuración."""

    def test_supera_el_limite_y_responde_429(self):
        from unittest import mock

        from rest_framework.throttling import SimpleRateThrottle

        url = reverse("api:catalogo_productos")
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"anon": "2/min", "user": "2/min"}):
            respuestas = [self.client_autenticado.get(url).status_code for _ in range(3)]
        self.assertIn(429, respuestas)
