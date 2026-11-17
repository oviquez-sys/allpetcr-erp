"""La campaña vista desde afuera: la caja, el comprobante, el pedido web, la
API del sitio, las pantallas y la demostración (16/11/2026).

Las reglas de fondo están en `campanas/tests.py`; acá se prueba que cada
puerta llegue a ellas y diga lo mismo.
"""
import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from impresion.tiquete import bytes_tiquete
from manada.models import PerfilManada, Regalia
from pedidos import por_confirmar
from pedidos.models import PedidoPorConfirmar
from ventas.models import Cliente, FacturaVenta
from ventas.services import anular_factura, registrar_venta

from . import demo, medicion, reglas, sorteo
from .models import Campana, NumerosVenta, Participante
from .tests import ConCampana


class EnLaCaja(ConCampana):
    def setUp(self):
        super().setUp()
        self.client.login(username="oscar", password="clave-test")

    def post(self, nombre, datos):
        return self.client.post(reverse(nombre), json.dumps(datos), content_type="application/json")

    def test_al_identificar_al_cliente_se_ve_si_participa(self):
        r = self.client.get(reverse("ventas:cupon"), {"codigo": "8888-1111"}).json()
        self.assertEqual(r["cliente"]["campana"], {"participa": False, "numeros": 0})
        self.inscribir()
        r = self.client.get(reverse("ventas:cupon"), {"codigo": "8888-1111"}).json()
        self.assertEqual(r["cliente"]["campana"], {"participa": True, "numeros": 1})

    def test_inscribir_a_un_cliente_existente_exige_su_si(self):
        r = self.post("ventas:campana_inscribir", {"cliente_id": self.maria.pk})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Participante.objects.exists())
        r = self.post("ventas:campana_inscribir", {"cliente_id": self.maria.pk, "acepto": True}).json()
        self.assertEqual((r["participa"], r["numeros"], r["ya_participaba"]), (True, 1, False))

    def test_la_inscripcion_no_es_permiso_de_publicidad(self):
        self.post("ventas:campana_inscribir", {"cliente_id": self.maria.pk, "acepto": True})
        self.assertFalse(PerfilManada.objects.get(cliente=self.maria).acepta_promociones)
        juan = Cliente.objects.create(empresa=self.empresa, nombre="Juan", telefono="88883333")
        self.post("ventas:campana_inscribir", {"cliente_id": juan.pk, "acepto": True, "promos": True})
        self.assertTrue(PerfilManada.objects.get(cliente=juan).acepta_promociones)

    def test_no_marcar_publicidad_no_le_quita_el_permiso_que_ya_dio(self):
        PerfilManada.objects.create(cliente=self.maria, origen="CAJ", acepta_promociones=True)
        self.post("ventas:campana_inscribir", {"cliente_id": self.maria.pk, "acepto": True})
        self.assertTrue(PerfilManada.objects.get(cliente=self.maria).acepta_promociones)

    def test_cliente_nuevo_se_inscribe_al_unirse_y_su_compra_ya_cuenta(self):
        r = self.post("ventas:manada_rapido", {"nombre": "Laura", "telefono": "8888-7777", "acepto": True,
                                               "campana": True}).json()
        self.assertEqual(r["cliente"]["campana"], {"participa": True, "numeros": 1})
        self.assertEqual(r["cupon"], "")                      # la campaña reemplaza el 10 %
        p = Participante.objects.get()
        self.assertTrue(p.cliente_nuevo and p.miembro_nuevo)
        venta = self.post("ventas:vender", {"medio_pago": "EFE", "cliente_id": r["cliente"]["id"],
                                            "lineas": [{"producto_id": self.caro.pk, "cantidad": 1}]}).json()
        self.assertEqual(venta["campana"], {"nombre": "Navidad AllPet 2026", "habituales": 1, "bono": 1,
                                            "total": 2, "monto": 20001.0, "lleva": 3})

    def test_unirse_sin_marcar_el_sorteo_no_inscribe(self):
        self.post("ventas:manada_rapido", {"nombre": "Laura", "telefono": "8888-7777", "acepto": True})
        self.assertFalse(Participante.objects.exists())

    def test_si_no_quiere_inscribirse_la_venta_sigue(self):
        venta = self.post("ventas:vender", {"medio_pago": "EFE", "cliente_id": self.maria.pk,
                                            "lineas": [{"producto_id": self.caro.pk, "cantidad": 1}]}).json()
        self.assertTrue(venta["ok"])
        self.assertIsNone(venta["campana"])

    def test_la_pantalla_de_caja_trae_la_campana(self):
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, 'id="campFila"')
        self.assertContains(r, "Navidad AllPet 2026")
        self.assertEqual(r.context["campana"]["umbral"], 20000.0)
        self.assertFalse(r.context["campana"]["bienvenida"])

    def test_sin_campana_la_caja_queda_como_antes(self):
        Campana.objects.all().update(estado=Campana.Estado.BORRADOR)
        r = self.client.get(reverse("ventas:pos"))
        self.assertNotIn("nombre", r.context["campana"])


class ElComprobante(ConCampana):
    def test_el_tiquete_impreso_separa_habituales_y_bono(self):
        self.inscribir()
        f = self.venta(self.caro)
        papel = bytes_tiquete(f).decode("cp850")
        self.assertIn("NAVIDAD ALLPET 2026", papel)
        self.assertIn("Por la compra", papel)
        self.assertIn("Bono (supera ¢20.000)", papel)
        self.assertIn("Total de esta compra", papel)
        self.assertIn("Lleva en total", papel)

    def test_sin_numeros_el_tiquete_no_cambia(self):
        f = self.venta(self.caro)            # no está inscrita
        self.assertNotIn("sorteo", bytes_tiquete(f).decode("cp850").lower())

    def test_el_tiquete_de_pantalla_y_el_recibo_muestran_la_reversion(self):
        self.client.login(username="oscar", password="clave-test")
        self.inscribir()
        f = self.venta(self.caro)
        anular_factura(factura=f, motivo="Error", usuario=self.usuario)
        for nombre in ("ventas:tiquete", "ventas:factura"):
            r = self.client.get(reverse(nombre, args=[f.pk]))
            self.assertContains(r, "Quitados por devolución")


class PedidoWeb(ConCampana):
    def crear(self, **extra):
        datos = dict(empresa=self.empresa, nombre="María", telefono="8888-1111", clave="carrito-1",
                     entrega="ENV", provincia="Heredia", canton="Heredia", distrito="Mercedes", senas="Casa azul",
                     origen_visita="instagram / navidad", lineas=[{"sku": "P-CARO", "cantidad": 1}])
        datos.update(extra)
        return por_confirmar.crear(**datos)

    def test_recibe_un_numero_corto_y_reconoce_al_cliente_sin_tocar_inventario(self):
        pedido, creado = self.crear()
        self.assertTrue(creado)
        self.assertRegex(pedido.numero, r"^WEB-\d+$")
        self.assertEqual(pedido.cliente, self.maria)
        self.assertEqual(pedido.subtotal_productos, Decimal("20001"))
        self.caro.refresh_from_db()
        self.assertEqual(self.caro.stock_actual, Decimal("10"))

    def test_la_misma_clave_no_crea_dos(self):
        uno, _ = self.crear()
        dos, creado = self.crear()
        self.assertFalse(creado)
        self.assertEqual(uno.pk, dos.pk)

    def test_al_cobrarlo_en_caja_conserva_su_identidad_y_acredita_una_vez(self):
        p = self.inscribir()
        pedido, _ = self.crear()
        f = self.venta(self.caro, pedido_web=pedido.numero, envio_costo=2500)
        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, pedido.factura), ("CON", f))
        self.assertTrue(pedido.envio_gratis)                 # supera el monto y Mercedes está en zona
        self.assertEqual(pedido.envio_costo, Decimal("2500"))
        n = f.numeros_campana
        self.assertEqual((n.canal, n.total), (NumerosVenta.Canal.WEB, 2))
        self.assertEqual(reglas.saldo(p), 3)
        # El mismo número no sirve para una segunda venta: esa queda como de tienda.
        otra = self.venta(self.producto, pedido_web=pedido.numero)
        self.assertEqual(otra.numeros_campana.canal, NumerosVenta.Canal.TIENDA)
        self.assertFalse(hasattr(otra, "pedido_web"))

    def test_fuera_de_zona_el_envio_no_es_gratis(self):
        pedido, _ = self.crear(canton="Barva", distrito="Barva")
        self.venta(self.caro, pedido_web=pedido.numero, envio_costo=3000)
        pedido.refresh_from_db()
        self.assertFalse(pedido.envio_gratis)

    def test_un_numero_que_no_existe_no_tumba_la_venta(self):
        with self.assertLogs("pedidos.por_confirmar", level="WARNING"):
            f = self.venta(self.caro, pedido_web="WEB-999")
        self.assertEqual(f.estado, FacturaVenta.Estado.EMITIDA)

    def test_anular_la_venta_reabre_el_pedido(self):
        self.inscribir()
        pedido, _ = self.crear()
        f = self.venta(self.caro, pedido_web=pedido.numero)
        anular_factura(factura=f, motivo="Se equivocó", usuario=self.usuario)
        pedido.refresh_from_db()
        self.assertEqual((pedido.estado, pedido.factura), ("PEN", None))

    def test_la_caja_lista_los_pendientes_y_puede_cancelar(self):
        self.client.login(username="oscar", password="clave-test")
        pedido, _ = self.crear()
        r = self.client.get(reverse("ventas:pedidos_web")).json()
        self.assertEqual([p["numero"] for p in r["pedidos"]], [pedido.numero])
        self.assertEqual(r["pedidos"][0]["lineas"][0]["producto_id"], self.caro.pk)
        r = self.client.post(reverse("ventas:pedidos_web"), json.dumps({"cancelar": pedido.numero}),
                             content_type="application/json").json()
        self.assertEqual(r["pedidos"], [])


class ApiDelSitio(ConCampana):
    def setUp(self):
        super().setUp()
        sitio = User.objects.create_user("sitio", password="x")
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=sitio).key}")

    def test_sin_token_no_responde(self):
        self.assertEqual(APIClient().get("/api/campana/").status_code, 401)

    def test_la_campana_vigente(self):
        r = self.api.get("/api/campana/").json()
        self.assertTrue(r["activa"] and r["inscripcion_abierta"])
        self.assertEqual(r["numeros"]["umbral"], "20000.00")
        self.assertIn("Heredia / Mercedes", r["envio_gratis"]["zonas"])
        self.assertEqual(r["bases"], "Bases de prueba.")

    def test_sin_campana_responde_que_no_hay(self):
        Campana.objects.all().update(estado=Campana.Estado.BORRADOR)
        self.assertEqual(self.api.get("/api/campana/").json(), {"activa": False})

    def test_inscribirse_exige_aceptar_las_bases(self):
        r = self.api.post("/api/campana/inscripcion/", {"nombre": "Ana", "telefono": "8888-2222"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Participante.objects.exists())

    def test_inscribirse_y_reconocer_la_inscripcion_previa(self):
        cuerpo = {"nombre": "Ana", "telefono": "8888-2222", "acepta_bases": True, "origen": "qr-tarjeta"}
        r = self.api.post("/api/campana/inscripcion/", cuerpo, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["numeros"], 1)
        self.assertTrue(r.json()["cliente_nuevo"])
        p = Participante.objects.get()
        self.assertEqual((p.canal, p.origen_visita), ("WEB", "qr-tarjeta"))
        self.assertFalse(p.cliente.manada.acepta_promociones)
        otra = self.api.post("/api/campana/inscripcion/", cuerpo, format="json")
        self.assertEqual(otra.status_code, 200)
        self.assertTrue(otra.json()["ya_participaba"])
        self.assertEqual(Participante.objects.count(), 1)
        r = self.api.get("/api/campana/participante/", {"telefono": "+506 8888 2222"}).json()
        self.assertEqual((r["participa"], r["numeros"]), (True, 1))
        self.assertNotIn("nombre", r)
        self.assertFalse(self.api.get("/api/campana/participante/", {"telefono": "70000000"}).json()["participa"])

    def test_beneficios_de_un_carrito(self):
        self.inscribir()
        r = self.api.post("/api/campana/beneficios/", {
            "lineas": [{"sku": "P-CARO", "cantidad": 1}], "entrega": "ENV", "canton": "Heredia",
            "distrito": "Ulloa", "telefono": "88881111"}, format="json").json()
        self.assertEqual(r["monto_evaluado"], "20001.00")
        self.assertTrue(r["supera_umbral"] and r["participa"] and r["envio"]["gratis"])
        self.assertEqual(r["numeros"], {"habituales": 1, "bono": 1, "total": 2})
        r = self.api.post("/api/campana/beneficios/", {
            "lineas": [{"sku": "P-JUSTO", "cantidad": 1}], "entrega": "RET"}, format="json").json()
        self.assertEqual((r["supera_umbral"], r["falta_para_bono"], r["numeros"]["total"]), (False, "1.00", 1))
        self.assertFalse(r["envio"]["aplica"])

    def test_beneficios_con_un_producto_que_no_existe(self):
        r = self.api.post("/api/campana/beneficios/", {"lineas": [{"sku": "NO-HAY", "cantidad": 1}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_pedido_por_confirmar_y_su_estado(self):
        self.inscribir()
        cuerpo = {"clave": "abc-123", "nombre": "María", "telefono": "8888-1111", "entrega": "RET",
                  "lineas": [{"sku": "P-CARO", "cantidad": 1}], "origen": "instagram / navidad"}
        r = self.api.post("/api/pedidos/por-confirmar/", cuerpo, format="json")
        self.assertEqual(r.status_code, 201)
        numero = r.json()["numero"]
        self.assertEqual(r.json()["beneficios"]["numeros"]["total"], 2)
        self.assertEqual(self.api.post("/api/pedidos/por-confirmar/", cuerpo, format="json").status_code, 200)
        self.assertEqual(PedidoPorConfirmar.objects.count(), 1)
        self.assertEqual(self.api.get(f"/api/pedidos/por-confirmar/{numero}/").status_code, 404)   # sin teléfono
        estado = self.api.get(f"/api/pedidos/por-confirmar/{numero}/", {"telefono": "88881111"}).json()
        self.assertEqual((estado["estado"], estado["numeros"]), ("PEN", None))
        self.venta(self.caro, pedido_web=numero)
        estado = self.api.get(f"/api/pedidos/por-confirmar/{numero}/", {"telefono": "88881111"}).json()
        self.assertEqual(estado["estado"], "CON")
        self.assertEqual(estado["numeros"], {"habituales": 1, "bono": 1, "total": 2, "revertidos": 0, "lleva": 3})

    def test_la_regalia_de_bienvenida_sale_apagada_durante_la_campana(self):
        Regalia.objects.create(empresa=self.empresa, porcentaje=Decimal("10"), texto_cliente="10 %")
        self.assertFalse(self.api.get("/api/manada/regalia/").json()["activa"])
        Campana.objects.all().update(estado=Campana.Estado.BORRADOR)
        self.assertTrue(self.api.get("/api/manada/regalia/").json()["activa"])


class Pantallas(ConCampana):
    def setUp(self):
        super().setUp()
        self.client.login(username="oscar", password="clave-test")
        self.url = reverse("campanas:detalle", args=[self.campana.pk])

    def accion(self, **datos):
        return self.client.post(reverse("campanas:accion", args=[self.campana.pk]), datos, follow=True)

    def test_todas_las_pestanas_abren(self):
        self.inscribir()
        self.venta(self.caro)
        for t in ("resumen", "participantes", "sorteo", "canasta", "medicion"):
            self.assertEqual(self.client.get(self.url, {"t": t}).status_code, 200, t)
        self.assertEqual(self.client.get(reverse("campanas:lista")).status_code, 200)
        self.assertContains(self.client.get(reverse("campanas:participantes_csv", args=[self.campana.pk])), "María")

    def test_el_resumen_muestra_que_se_evalua_antes_de_activar(self):
        Campana.objects.all().update(estado=Campana.Estado.BORRADOR)
        r = self.client.get(self.url)
        self.assertContains(r, "Qué monto se mide")
        self.assertContains(r, "exactos no ganan el bono")
        self.assertContains(r, "Heredia / Mercedes")
        self.assertContains(r, "Activar la campaña")

    def test_no_se_activa_sin_marcar_que_se_reviso_ni_con_bases_por_definir(self):
        Campana.objects.all().update(estado=Campana.Estado.BORRADOR)
        self.assertContains(self.accion(accion="activar"), "Marcá la casilla")
        Campana.objects.all().update(bases="Regla [POR DEFINIR: algo]")
        self.assertContains(self.accion(accion="activar", revise="1"), "POR DEFINIR")
        Campana.objects.all().update(bases="Bases completas.")
        self.accion(accion="activar", revise="1")
        self.campana.refresh_from_db()
        self.assertEqual(self.campana.estado, Campana.Estado.ACTIVA)

    def test_el_formulario_de_navidad_viene_lleno_y_guarda_en_borrador(self):
        Campana.objects.all().delete()
        r = self.client.get(reverse("campanas:nueva"), {"plantilla": "navidad"})
        inicial = r.context["form"].initial
        self.assertEqual(inicial["slug"], "navidad-2026")
        self.assertIn("POR DEFINIR", inicial["bases"])
        datos = {"nombre": "Navidad AllPet 2026", "slug": "navidad-2026", "premio": "Canasta",
                 "inicio": "2026-11-20T08:00", "cierre": "2026-12-23T23:59", "sorteo_en": "2026-12-24T12:00",
                 "numeros_inscripcion": 1, "numeros_compra": 1, "numeros_bono": 1, "umbral_bono": "20000",
                 "compra_minima": "0", "envio_gratis": "on", "envio_gratis_hasta": "2026-12-24T23:59",
                 "zonas_envio": "Heredia / Mercedes", "reemplaza_bienvenida": "on", "despues": "NAD",
                 "bases": "Bases.", "suplentes": 2, "plazo_reclamo_dias": 5, "procedimiento_sin_respuesta": "Pasa.",
                 "costo_impresion": "0", "costo_reparto": "0", "otros_costos": "0"}
        self.client.post(reverse("campanas:nueva"), datos)
        c = Campana.objects.get()
        self.assertEqual(c.estado, Campana.Estado.BORRADOR)
        # La hora escrita es la de Costa Rica (UTC−6): 12:00 md = 18:00 UTC.
        self.assertEqual((c.sorteo_en.utctimetuple().tm_hour, c.sorteo_en.utctimetuple().tm_mday), (18, 24))

    def test_congelar_sortear_y_segunda_pulsacion(self):
        self.inscribir()
        self.venta(self.caro)
        self.cerrar_y_pasar_al_sorteo()
        self.assertContains(self.accion(accion="congelar", t="sorteo"), "Lista congelada")
        r = self.accion(accion="sortear", t="sorteo")
        self.assertContains(r, "Sorteo realizado")
        numero = self.campana.sorteo.numero_ganador
        r = self.accion(accion="sortear", t="sorteo")
        self.assertContains(r, "ya se había realizado")
        self.campana.sorteo.refresh_from_db()
        self.assertEqual(self.campana.sorteo.numero_ganador, numero)
        acta = self.client.get(reverse("campanas:acta", args=[self.campana.pk]))
        self.assertContains(acta, "Acta del sorteo")
        self.assertContains(acta, self.campana.sorteo.huella)
        self.assertContains(self.client.get(reverse("campanas:lista_csv", args=[self.campana.pk])), "Huella SHA-256")

    def test_el_cajero_no_entra(self):
        cajero = User.objects.create_user("caja", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_un_gerente_sin_el_permiso_no_sortea(self):
        gerente = User.objects.create_user("fran", password="x", is_staff=True)
        gerente.groups.add(Group.objects.get_or_create(name="Gerente")[0])
        self.inscribir()
        self.cerrar_y_pasar_al_sorteo()
        self.client.force_login(gerente)
        self.assertContains(self.accion(accion="sortear", t="sorteo"), "No tenés permiso")
        self.assertFalse(hasattr(Campana.objects.get(), "sorteo") and Campana.objects.get().sorteo.realizado)

    def test_canasta_y_entrega_desde_la_pantalla(self):
        self.inscribir()
        self.accion(accion="canasta_agregar", version="PER", codigo="P-001", cantidad="2")
        self.assertEqual(self.campana.canasta.get().cantidad, 2)
        self.cerrar_y_pasar_al_sorteo()
        self.accion(accion="sortear")
        r = self.accion(accion="entregar", version="PER", recibe_nombre="María", t="canasta")
        self.assertContains(r, "Entrega registrada")
        self.assertContains(self.client.get(self.url, {"t": "canasta"}), "Premio entregado")


class Medicion(ConCampana):
    def test_resumen_con_una_compra_en_tienda_y_una_web(self):
        self.campana.costo_impresion = Decimal("30000")
        self.campana.save()
        p = self.inscribir(cliente_nuevo=True, miembro_nuevo=True, origen_visita="qr-tarjeta")
        juan = Cliente.objects.create(empresa=self.empresa, nombre="Juan", telefono="88883333")
        self.inscribir(juan, canal="WEB")
        pedido, _ = por_confirmar.crear(empresa=self.empresa, nombre="María", telefono="88881111", entrega="ENV",
                                        canton="Heredia", distrito="Heredia", lineas=[{"sku": "P-CARO", "cantidad": 1}])
        self.venta(self.caro, pedido_web=pedido.numero, envio_costo=2500)
        self.venta(self.producto)
        m = medicion.resumen(self.campana)
        self.assertEqual(m["participantes"], 2)
        self.assertEqual({c["nombre"]: c["cantidad"] for c in m["por_canal_inscripcion"]},
                         {"Sitio web": 1, "En la tienda": 1})
        self.assertEqual({o["nombre"]: o["cantidad"] for o in m["origenes"]},
                         {"qr-tarjeta": 1, "origen desconocido": 1})
        self.assertEqual((m["nuevos_miembros"], m["primeras_compras"], m["con_compra"]), (1, 1, 1))
        canales = {c["nombre"]: c for c in m["por_canal_compra"]}
        self.assertEqual((canales["Web"]["monto"], canales["Tienda"]["monto"]), (Decimal("20001"), Decimal("5000")))
        self.assertEqual(m["numeros"], {"inscripcion": 2, "habituales": 2, "bono": 1, "revertidos": 0,
                                        "ajustes": 0, "vigentes": 5})
        self.assertEqual((m["envios_gratis"], m["costo_envios"]), (1, Decimal("2500")))
        self.assertEqual(m["costo_total"], Decimal("32500"))
        self.assertEqual(m["costo_por_cliente_nuevo"], Decimal("32500"))
        # Ganancia: (20001 − 15000) + (5000 − 2000), en régimen simplificado.
        self.assertEqual(m["ventas_margen"], Decimal("8001.00"))
        self.assertEqual(m["margen_campana"], Decimal("8001.00") - Decimal("32500"))
        self.assertEqual(reglas.saldo(p), 4)

    def test_quien_ya_habia_comprado_no_es_primera_compra(self):
        registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario, cliente=self.maria,
                        lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])
        FacturaVenta.objects.update(creado_en=self.campana.inicio - __import__("datetime").timedelta(days=3))
        self.inscribir()
        self.venta(self.caro)
        self.assertEqual(medicion.resumen(self.campana)["primeras_compras"], 0)


class Demostracion(ConCampana):
    def test_se_crea_se_sortea_y_se_borra_sin_tocar_lo_real(self):
        ventas_antes = FacturaVenta.objects.count()
        self.caro.refresh_from_db()
        campana = demo.crear(self.empresa)
        self.assertTrue(campana.es_demo)
        self.assertEqual(campana.participantes.count(), 14)
        self.assertEqual(reglas.vigente(self.empresa), self.campana)       # la real sigue siendo la vigente
        self.assertFalse(Cliente.objects.filter(nombre__startswith="DEMO", activo=True).exists())
        m = medicion.resumen(campana)
        self.assertGreater(m["ventas_monto"], 0)
        self.assertEqual(m["envios_gratis"], 2)
        s, nuevo = sorteo.sortear(campana, self.usuario)
        self.assertTrue(nuevo)
        self.assertEqual(s.adjudicaciones.count(), 3)                       # ganador + 2 suplentes
        self.assertEqual(FacturaVenta.objects.count(), ventas_antes)
        demo.crear(self.empresa)                                            # volver a crearla la reemplaza
        self.assertEqual(Campana.objects.filter(es_demo=True).count(), 1)
        demo.borrar(self.empresa)
        self.assertFalse(Campana.objects.filter(es_demo=True).exists())
        self.assertFalse(Cliente.objects.filter(nombre__startswith="DEMO").exists())
        self.assertFalse(PedidoPorConfirmar.objects.filter(clave__startswith="demo-").exists())

    def test_en_la_demostracion_no_se_entrega(self):
        from django.core.exceptions import ValidationError
        campana = demo.crear(self.empresa)
        s, _ = sorteo.sortear(campana, self.usuario)
        with self.assertRaises(ValidationError):
            sorteo.entregar(s, version="PER", recibe_nombre="X", usuario=self.usuario, sesion_caja=self.sesion)

    def test_la_pantalla_la_crea_y_la_muestra(self):
        self.client.login(username="oscar", password="clave-test")
        r = self.client.post(reverse("campanas:demostracion"), {"accion": "crear"}, follow=True)
        self.assertContains(r, "Datos ficticios")
        campana = Campana.objects.get(es_demo=True)
        for t in ("participantes", "sorteo", "medicion", "canasta"):
            self.assertEqual(self.client.get(reverse("campanas:detalle", args=[campana.pk]), {"t": t}).status_code, 200)
