import json
from unittest import mock
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings

from core.models import ChatMensaje, Empresa
from core.chat_tools import ejecutar_herramienta


class ChatSinAPIKeyTest(TestCase):
    """No hay API key -> debe fallar con mensaje claro, sin tronar."""
    @mock.patch.dict("os.environ", {}, clear=True)
    def test_sin_api_key(self):
        user = User.objects.create_user("cajero1", password="x", is_staff=True)
        client = Client()
        client.force_login(user)
        resp = client.post("/api/chat/", data=json.dumps({"message": "hola"}), content_type="application/json")
        print("Sin API key:", resp.status_code, resp.json())
        self.assertEqual(resp.status_code, 500)


class LimiteDiarioTest(TestCase):
    def test_limite_diario_bloquea(self):
        user = User.objects.create_user("cajero2", password="x", is_staff=True)
        for i in range(40):
            ChatMensaje.objects.create(usuario=user, pregunta=f"p{i}", respuesta="r")
        client = Client()
        client.force_login(user)
        resp = client.post("/api/chat/", data=json.dumps({"message": "otra pregunta"}), content_type="application/json")
        print("Límite diario:", resp.status_code, resp.json())
        self.assertEqual(resp.status_code, 429)
        self.assertIn("límite", resp.json()["error"].lower())


class HerramientasTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Test Herramientas")

    def test_indicadores_sin_datos_no_truena(self):
        r = ejecutar_herramienta("indicadores_del_negocio", {})
        print("indicadores_del_negocio:", r)
        self.assertNotIn("error", r)
        self.assertEqual(r["ventas_hoy"], 0.0)

    def test_herramienta_desconocida(self):
        r = ejecutar_herramienta("algo_que_no_existe", {})
        print("herramienta desconocida:", r)
        self.assertIn("error", r)

    def test_productos_menor_margen_con_datos(self):
        from catalogo.models import Producto
        Producto.objects.create(empresa=self.empresa, sku="A1", nombre="Barato",
                                 precio_venta=Decimal("1000"), costo_promedio=Decimal("900"))
        Producto.objects.create(empresa=self.empresa, sku="A2", nombre="Rentable",
                                 precio_venta=Decimal("1000"), costo_promedio=Decimal("300"))
        r = ejecutar_herramienta("productos_menor_margen", {"limite": 2})
        print("productos_menor_margen:", r)
        self.assertEqual(r["productos"][0]["nombre"], "Barato")


class HistorialValidoTest(TestCase):
    def test_historial_sanitiza_basura(self):
        from core.views import _historial_valido
        bruto = [
            {"role": "user", "content": "hola"},
            {"role": "hacker", "content": "malo"},
            {"role": "assistant", "content": 12345},
            "no es un dict",
            {"role": "assistant", "content": "bien"},
        ]
        limpio = _historial_valido(bruto)
        print("historial sanitizado:", limpio)
        self.assertEqual(len(limpio), 2)
        self.assertEqual(limpio[0]["content"], "hola")
        self.assertEqual(limpio[1]["content"], "bien")
