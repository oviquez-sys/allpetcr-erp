import json
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, Client

from core.models import ChatMensaje


def _bloque_texto(txt):
    return SimpleNamespace(type="text", text=txt)


def _bloque_tool_use(nombre, entrada, tool_id="tool_1"):
    return SimpleNamespace(type="tool_use", name=nombre, input=entrada, id=tool_id)


def _usage(i=50, o=20):
    return SimpleNamespace(input_tokens=i, output_tokens=o)


class ChatLoopHerramientasMockTest(TestCase):
    """Simula las respuestas de Anthropic para probar el loop de tool-use
    sin pegarle a la red real (el sandbox no tiene salida a api.anthropic.com)."""

    def setUp(self):
        self.user = User.objects.create_user("mockuser", password="x", is_staff=True)
        self.client_django = Client()
        self.client_django.force_login(self.user)

    @mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-fake-para-test"})
    @mock.patch("core.views.anthropic.Anthropic")
    def test_una_ronda_de_herramienta_luego_texto(self, MockAnthropic):
        # Primera llamada: el modelo pide usar una herramienta.
        resp1 = SimpleNamespace(
            stop_reason="tool_use",
            usage=_usage(),
            content=[_bloque_tool_use("indicadores_del_negocio", {})],
        )
        # Segunda llamada: ya con el resultado de la herramienta, responde texto.
        resp2 = SimpleNamespace(
            stop_reason="end_turn",
            usage=_usage(),
            content=[_bloque_texto("Vendiste ₡0 hoy.")],
        )
        cliente_mock = MockAnthropic.return_value
        cliente_mock.messages.create.side_effect = [resp1, resp2]

        r = self.client_django.post("/api/chat/", data=json.dumps({"message": "¿cuánto vendí hoy?"}),
                                     content_type="application/json")
        print("STATUS:", r.status_code, "BODY:", r.json())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["response"], "Vendiste ₡0 hoy.")
        self.assertEqual(cliente_mock.messages.create.call_count, 2)

        log = ChatMensaje.objects.get(usuario=self.user)
        print("Log:", log.pregunta, "->", log.respuesta, "tokens_in=", log.tokens_entrada, "tokens_out=", log.tokens_salida)
        self.assertEqual(log.respuesta, "Vendiste ₡0 hoy.")
        self.assertEqual(log.tokens_entrada, 100)  # 50 + 50
        self.assertEqual(log.tokens_salida, 40)    # 20 + 20

    @mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-fake-para-test"})
    @mock.patch("core.views.anthropic.Anthropic")
    def test_respuesta_directa_sin_herramientas(self, MockAnthropic):
        resp = SimpleNamespace(
            stop_reason="end_turn",
            usage=_usage(),
            content=[_bloque_texto("Para vender, andá a Vender en Acceso Rápido.")],
        )
        cliente_mock = MockAnthropic.return_value
        cliente_mock.messages.create.return_value = resp

        r = self.client_django.post("/api/chat/", data=json.dumps({"message": "¿cómo vendo?"}),
                                     content_type="application/json")
        print("STATUS:", r.status_code, "BODY:", r.json())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(cliente_mock.messages.create.call_count, 1)

    @mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-fake-para-test"})
    @mock.patch("core.views.anthropic.Anthropic")
    def test_memoria_manda_historial_a_claude(self, MockAnthropic):
        resp = SimpleNamespace(
            stop_reason="end_turn", usage=_usage(),
            content=[_bloque_texto("Sí, ese fue el total de hoy.")],
        )
        cliente_mock = MockAnthropic.return_value
        cliente_mock.messages.create.return_value = resp

        historial = [
            {"role": "user", "content": "¿cuánto vendí hoy?"},
            {"role": "assistant", "content": "Vendiste ₡24000 hoy."},
        ]
        r = self.client_django.post("/api/chat/", data=json.dumps({
            "message": "¿ese es el total correcto?", "history": historial,
        }), content_type="application/json")
        self.assertEqual(r.status_code, 200)

        # El historial + el mensaje nuevo se le mandaron a Claude en la llamada.
        _, kwargs = cliente_mock.messages.create.call_args
        mensajes_enviados = kwargs["messages"]
        print("Mensajes enviados a Claude:", mensajes_enviados)
        self.assertEqual(len(mensajes_enviados), 3)
        self.assertEqual(mensajes_enviados[0]["content"], "¿cuánto vendí hoy?")
        self.assertEqual(mensajes_enviados[2]["content"], "¿ese es el total correcto?")

    @mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-fake-para-test"})
    @mock.patch("core.views.anthropic.Anthropic")
    def test_loop_infinito_de_herramientas_no_cuelga(self, MockAnthropic):
        # El modelo insiste en pedir herramientas sin parar -> debe frenar
        # después de CHAT_MAX_RONDAS_HERRAMIENTAS y no reventar.
        resp_tool = SimpleNamespace(
            stop_reason="tool_use", usage=_usage(),
            content=[_bloque_tool_use("indicadores_del_negocio", {})],
        )
        cliente_mock = MockAnthropic.return_value
        cliente_mock.messages.create.return_value = resp_tool

        r = self.client_django.post("/api/chat/", data=json.dumps({"message": "insistí"}),
                                     content_type="application/json")
        print("STATUS loop:", r.status_code, "BODY:", r.json())
        self.assertEqual(r.status_code, 200)
        self.assertIn("no pude", r.json()["response"].lower())
        # No debió llamar infinitas veces, se frena en el tope.
        self.assertEqual(cliente_mock.messages.create.call_count, 4)
