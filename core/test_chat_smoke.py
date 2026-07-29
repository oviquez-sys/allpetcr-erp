import json
from unittest import mock
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase, Client, override_settings

from core.models import ChatMensaje, Empresa
from core.chat_tools import ejecutar_herramienta, herramientas_para, TOOLS_SCHEMA


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
        # Las herramientas financieras exigen rol: se pasa un gerente.
        self.gerente = User.objects.create_user(
            "gerente_test", password="x", is_staff=True, is_superuser=True
        )

    def test_indicadores_sin_datos_no_truena(self):
        r = ejecutar_herramienta("indicadores_del_negocio", {}, usuario=self.gerente)
        print("indicadores_del_negocio:", r)
        self.assertNotIn("error", r)
        self.assertEqual(r["ventas_hoy"], 0.0)

    def test_herramienta_desconocida(self):
        r = ejecutar_herramienta("algo_que_no_existe", {}, usuario=self.gerente)
        print("herramienta desconocida:", r)
        self.assertIn("error", r)

    def test_productos_menor_margen_con_datos(self):
        from catalogo.models import Producto
        Producto.objects.create(empresa=self.empresa, sku="A1", nombre="Barato",
                                 precio_venta=Decimal("1000"), costo_promedio=Decimal("900"))
        Producto.objects.create(empresa=self.empresa, sku="A2", nombre="Rentable",
                                 precio_venta=Decimal("1000"), costo_promedio=Decimal("300"))
        r = ejecutar_herramienta("productos_menor_margen", {"limite": 2}, usuario=self.gerente)
        print("productos_menor_margen:", r)
        self.assertEqual(r["productos"][0]["nombre"], "Barato")


class PermisosHerramientasTest(TestCase):
    """El chat no debe ser una puerta trasera a los costos (hallazgo SEG-01).

    Un cajero tiene cerradas /precios/ y /reportes/. Si el asistente le
    entrega los mismos datos por conversación, el control de acceso no sirve
    de nada. Estas pruebas fijan esa regla para que no se pierda."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Test Permisos")
        from catalogo.models import Producto
        Producto.objects.create(empresa=self.empresa, sku="X1", nombre="Alimento",
                                precio_venta=Decimal("10000"), costo_promedio=Decimal("4000"),
                                stock_actual=Decimal("10"))
        self.cajero = User.objects.create_user("cajero_perm", password="x", is_staff=True)
        Group.objects.get_or_create(name="Cajero")[0].user_set.add(self.cajero)
        self.gerente = User.objects.create_user("gerente_perm", password="x",
                                                is_staff=True, is_superuser=True)
        self.contador = User.objects.create_user("contador_perm", password="x", is_staff=True)
        Group.objects.get_or_create(name="Contador")[0].user_set.add(self.contador)

    def test_cajero_no_obtiene_costos_ni_margenes(self):
        for nombre in ["valor_inventario", "productos_menor_margen",
                       "indicadores_del_negocio", "productos_mas_vendidos"]:
            r = ejecutar_herramienta(nombre, {}, usuario=self.cajero)
            self.assertIn("error", r, f"{nombre} no bloqueó al cajero")
            texto = str(r)
            self.assertNotIn("costo_promedio", texto)
            self.assertNotIn("margen_pct", texto)
            self.assertNotIn("valor_total", texto)

    def test_cajero_conserva_la_ayuda_util(self):
        r = ejecutar_herramienta("productos_stock_bajo", {}, usuario=self.cajero)
        self.assertNotIn("error", r)

    def test_al_cajero_no_se_le_ofrecen_las_financieras(self):
        nombres = {t["name"] for t in herramientas_para(self.cajero)}
        self.assertEqual(nombres, {"productos_stock_bajo"})

    def test_gerente_y_contador_conservan_acceso(self):
        for usuario in (self.gerente, self.contador):
            r = ejecutar_herramienta("productos_menor_margen", {}, usuario=usuario)
            self.assertNotIn("error", r)
            self.assertEqual(r["productos"][0]["costo_promedio"], 4000.0)
            self.assertEqual(len(herramientas_para(usuario)), len(TOOLS_SCHEMA))

    def test_sin_usuario_falla_cerrado(self):
        """Si alguien agrega una llamada y olvida pasar el usuario, debe
        bloquear, no abrir."""
        r = ejecutar_herramienta("valor_inventario", {})
        self.assertIn("error", r)


class HistorialValidoTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User

        self.user = User.objects.create_user("cajero_hist", password="x", is_staff=True)

    def test_historial_se_reconstruye_desde_la_base(self):
        """El historial ya no se sanitiza: se ignora y se reconstruye.

        Auditoría 2026-07-28, hallazgo SEG-07. Antes el navegador mandaba la
        conversación previa y el servidor la limpiaba (esta prueba verificaba
        esa limpieza). El problema no era la limpieza sino el origen: el
        cliente controlaba CUÁNTO contexto se le mandaba al modelo, hasta
        ~80 000 caracteres por pregunta, y ahí es donde está el costo real.

        Ahora el servidor arma el historial desde ChatMensaje, que ya guardaba
        cada pregunta y respuesta. No hay nada que sanitizar porque no viene
        nada de afuera.
        """
        from core.models import ChatMensaje
        from core.views import _historial_del_usuario

        ChatMensaje.objects.create(
            usuario=self.user, pregunta="¿cuánto vendí?", respuesta="₡24 000."
        )
        # Sin respuesta (la llamada falló): no aporta contexto, se omite.
        ChatMensaje.objects.create(usuario=self.user, pregunta="¿y ayer?", respuesta="")

        historial = _historial_del_usuario(self.user)
        self.assertEqual(len(historial), 2, "Un intercambio completo = 2 mensajes")
        self.assertEqual(historial[0], {"role": "user", "content": "¿cuánto vendí?"})
        self.assertEqual(historial[1], {"role": "assistant", "content": "₡24 000."})

    def test_el_historial_de_un_usuario_no_se_le_da_a_otro(self):
        """Cada quien ve su propia conversación."""
        from django.contrib.auth.models import User

        from core.models import ChatMensaje
        from core.views import _historial_del_usuario

        otro = User.objects.create_user("otro_cajero", password="x", is_staff=True)
        ChatMensaje.objects.create(usuario=otro, pregunta="secreto", respuesta="dato")
        self.assertEqual(_historial_del_usuario(self.user), [])
