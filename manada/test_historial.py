"""Historial de compras, reconocimiento cruzado y recordatorios (14/10/2026).

Pedido de Oscar: ver qué compró cada cliente y cuándo, para avisarle cuando se
le acaba la comida y mandarle promociones de las marcas que compra. Lo que
fijan estas pruebas:

- Se reconoce por cédula → teléfono → correo; el nombre nunca une solo.
- Si dos datos apuntan a personas distintas, se avisa y NO se une.
- La casilla dorada del POS liga la venta al cliente aunque ya no tenga cupón.
- Los pedidos del sitio quedan en el mismo historial.
- "Se le acaba" sale del ritmo real; con una sola compra no se inventa.
- Solo se le escribe a quien aceptó (Ley 8968).
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.services import registrar_movimiento
from pedidos.models import Pedido
from pedidos.services import crear_pedido
from ventas.models import Cliente, FacturaVenta
from ventas.test_auditoria_2026_09 import Base

from . import historial as h
from .identificar import avisar_conflictos, identificar, identificar_texto, unir_clientes
from .models import Mascota, PerfilManada, PosibleDuplicado, Regalia
from .services import registrar_miembro


class BaseHistorial(Base):
    def setUp(self):
        super().setUp()
        raiz = Categoria.objects.create(nombre="Alimento", orden=10)
        seco = Categoria.objects.create(nombre="Alimento seco", padre=raiz, orden=11)
        self.comida = Producto.objects.create(
            empresa=self.empresa, sku="TOW-1", nombre="Taste of the Wild High Prairie 2 kg", marca="Taste of the Wild",
            precio_venta=Decimal("15490"), impuesto=self.iva, categoria=seco, mascota="Perro",
            peso_valor=Decimal("2"), peso_unidad="kg",
        )
        registrar_movimiento(producto=self.comida, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("50"), costo_unitario=Decimal("10000"), referencia="INI")
        self.maria = Cliente.objects.create(empresa=self.empresa, nombre="María Rodríguez Solís",
                                            telefono="8888-1234", identificacion="1-1234-0567",
                                            email="maria@correo.com")

    def venta_de_comida(self, cliente, hace_dias, cantidad=1, producto=None):
        f = self.vender(cliente=cliente, lineas=[{"producto_id": (producto or self.comida).pk, "cantidad": cantidad}])
        FacturaVenta.objects.filter(pk=f.pk).update(creado_en=timezone.now() - timedelta(days=hace_dias))
        return f

    def vender(self, medio="EFE", cantidad=1, lineas=None, **extra):
        from ventas.services import registrar_venta
        return registrar_venta(sesion_caja=self.sesion, medio_pago=medio, usuario=self.usuario,
                               lineas=lineas or [{"producto_id": self.producto.pk, "cantidad": cantidad}], **extra)

    def miembro(self, cliente, acepta=True):
        return PerfilManada.objects.create(cliente=cliente, origen=PerfilManada.Origen.CAJA, acepta_promociones=acepta)


class ControlCruzado(BaseHistorial):
    def test_se_reconoce_por_cedula_sin_importar_los_guiones(self):
        r = identificar(self.empresa, cedula="112340567")
        self.assertEqual(r.cliente, self.maria)
        self.assertEqual(r.por, "cédula")

    def test_si_no_hay_cedula_por_telefono_y_si_no_por_correo(self):
        self.assertEqual(identificar(self.empresa, cedula="999999999", telefono="+506 8888 1234").cliente, self.maria)
        self.assertEqual(identificar(self.empresa, telefono="70000000", correo="MARIA@correo.com").cliente, self.maria)

    def test_el_nombre_nunca_une_solo(self):
        self.assertIsNone(identificar_texto(self.empresa, "María Rodríguez Solís").cliente)

    def test_dos_datos_de_personas_distintas_avisan_y_no_unen(self):
        otra = Cliente.objects.create(empresa=self.empresa, nombre="Otra", telefono="7777-0000")
        r = identificar(self.empresa, cedula="1-1234-0567", telefono="77770000")
        self.assertEqual(r.cliente, self.maria)  # gana la cédula
        avisar_conflictos(r, "prueba")
        aviso = PosibleDuplicado.objects.get()
        self.assertEqual({aviso.cliente, aviso.otro}, {self.maria, otra})
        self.assertTrue(Cliente.objects.get(pk=otra.pk).activo, "No se une solo")

    def test_el_mismo_par_se_avisa_una_sola_vez(self):
        otra = Cliente.objects.create(empresa=self.empresa, nombre="Otra", telefono="7777-0000")
        for _ in range(3):
            avisar_conflictos(identificar(self.empresa, cedula="112340567", telefono="77770000"))
        avisar_conflictos(identificar(self.empresa, telefono="77770000", correo="maria@correo.com"))
        self.assertEqual(PosibleDuplicado.objects.count(), 1)


class CasillaDoradaDelPOS(BaseHistorial):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_whatsapp_sin_cupon_liga_la_venta_al_cliente(self):
        self.miembro(self.maria)
        r = self.client.get(reverse("ventas:cupon"), {"codigo": "8888-1234"})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertIsNone(d["codigo"])
        self.assertEqual(d["cliente"]["id"], self.maria.pk)
        self.assertEqual(d["cliente"]["compras"], 0)
        # El POS manda ese cliente con la venta: queda en su historial.
        self.client.post(reverse("ventas:vender"), json.dumps({
            "medio_pago": "EFE", "lineas": [{"producto_id": self.comida.pk, "cantidad": 1}],
            "clave": "k1", "cliente_id": d["cliente"]["id"]}), content_type="application/json")
        self.assertEqual(len(h.compras_de(self.maria)), 1)

    def test_cedula_de_un_miembro_con_regalo_pendiente_aplica_el_cupon(self):
        Regalia.objects.create(empresa=self.empresa, porcentaje=Decimal("10"), texto_cliente="10 %")
        res = registrar_miembro(empresa=self.empresa, telefono="8888-1234", nombre="María")
        self.assertEqual(res.cliente, self.maria)
        r = self.client.get(reverse("ventas:cupon"), {"codigo": "1-1234-0567"})
        self.assertEqual(r.json()["codigo"], res.cupon.codigo)
        self.assertEqual(r.json()["porcentaje"], 10.0)

    def test_regalo_ya_usado_igual_reconoce_y_avisa(self):
        Regalia.objects.create(empresa=self.empresa, porcentaje=Decimal("10"), texto_cliente="10 %")
        res = registrar_miembro(empresa=self.empresa, telefono="88881234", nombre="María")
        self.vender(cupon=res.cupon.codigo)
        d = self.client.get(reverse("ventas:cupon"), {"codigo": "88881234"}).json()
        self.assertIsNone(d["codigo"])
        self.assertEqual(d["cliente"]["compras"], 1)
        self.assertIn("ya se usó", d["aviso"])

    def test_dato_desconocido_da_error_claro(self):
        r = self.client.get(reverse("ventas:cupon"), {"codigo": "60001111"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("No hay ningún cliente", r.json()["error"])

    def test_cliente_nuevo_desde_caja_no_duplica_si_el_telefono_ya_existe(self):
        r = self.client.post(reverse("ventas:cliente_rapido"), json.dumps(
            {"nombre": "Mari", "telefono": "8888 1234"}), content_type="application/json")
        self.assertTrue(r.json()["ya_existia"])
        self.assertEqual(r.json()["cliente"]["id"], self.maria.pk)


class PedidosDelSitio(BaseHistorial):
    def pedido(self, **datos):
        base = {"empresa": self.empresa, "sucursal": self.sucursal, "cliente_nombre": "María R.",
                "cliente_telefono": "88881234", "lineas": [{"producto_id": self.comida.pk, "cantidad": 1}]}
        base.update(datos)
        return crear_pedido(**base)

    def test_el_pedido_se_liga_al_cliente_por_telefono(self):
        p = self.pedido()
        self.assertEqual(p.cliente, self.maria)
        compras = h.compras_de(self.maria)
        self.assertEqual([c.canal for c in compras], ["Sitio web"])

    def test_si_no_lo_reconoce_crea_el_cliente_pero_no_lo_hace_miembro(self):
        p = self.pedido(cliente_nombre="Pedro Mora", cliente_telefono="60001234", cliente_email="pedro@x.com")
        self.assertEqual(p.cliente.nombre, "Pedro Mora")
        self.assertFalse(PerfilManada.objects.filter(cliente=p.cliente).exists())

    def test_cliente_nuevo_que_se_llama_igual_queda_como_posible_duplicado(self):
        p = self.pedido(cliente_nombre="Maria Rodriguez Solis", cliente_telefono="60001234")
        self.assertNotEqual(p.cliente, self.maria)
        self.assertTrue(PosibleDuplicado.objects.filter(cliente=self.maria, otro=p.cliente).exists())

    def test_un_pedido_cancelado_no_cuenta(self):
        p = self.pedido()
        Pedido.objects.filter(pk=p.pk).update(estado=Pedido.Estado.CANCELADO)
        self.assertEqual(h.compras_de(self.maria), [])


class CuandoSeLeAcaba(BaseHistorial):
    def test_con_una_sola_compra_no_se_inventa(self):
        self.venta_de_comida(self.maria, hace_dias=5)
        item = h.consumibles(h.compras_de(self.maria))[0]
        self.assertIsNone(item.se_acaba)

    def test_se_calcula_con_el_ritmo_real(self):
        self.venta_de_comida(self.maria, hace_dias=40)
        self.venta_de_comida(self.maria, hace_dias=20)
        item = h.consumibles(h.compras_de(self.maria))[0]
        # Una bolsa de 2 kg le duró 20 días: la segunda se le acaba hoy.
        self.assertEqual(item.cada_dias, 20)
        self.assertEqual(item.dias_para, 0)

    def test_una_bolsa_mas_grande_de_la_misma_formula_dura_mas(self):
        from catalogo.models import FichaAlimento
        ficha = FichaAlimento.objects.create(clave="tow-high-prairie", nombre="High Prairie", marca="Taste of the Wild",
                                             especie="perro", tipo="seco")
        grande = Producto.objects.create(
            empresa=self.empresa, sku="TOW-6", nombre="Taste of the Wild High Prairie 6 kg",
            precio_venta=Decimal("40000"), impuesto=self.iva, categoria=self.comida.categoria,
            peso_valor=Decimal("6"), peso_unidad="kg", ficha_alimento=ficha)
        Producto.objects.filter(pk=self.comida.pk).update(ficha_alimento=ficha)
        registrar_movimiento(producto=grande, bodega=self.bodega, tipo="INI", cantidad=Decimal("5"),
                             costo_unitario=Decimal("30000"), referencia="INI")
        self.venta_de_comida(self.maria, hace_dias=40)
        self.venta_de_comida(self.maria, hace_dias=20, producto=grande)
        items = h.consumibles(h.compras_de(self.maria))
        self.assertEqual(len(items), 1, "La misma fórmula es un solo alimento")
        # 2 kg en 20 días = 0,1 kg/día → los 6 kg duran 60 días.
        self.assertEqual(items[0].dias_para, 40)

    def test_lo_que_no_es_comida_no_entra(self):
        f = self.vender(cliente=self.maria)  # el arnés
        self.assertEqual(h.consumibles(h.compras_de(self.maria)), [])
        self.assertEqual(len(h.compras_de(self.maria)), 1)
        self.assertTrue(f.pk)


class Recordatorios(BaseHistorial):
    def setUp(self):
        super().setUp()
        self.venta_de_comida(self.maria, hace_dias=40)
        self.venta_de_comida(self.maria, hace_dias=17)   # le dura 23 días: se le acaba en ~6

    def test_aparece_con_boton_de_whatsapp_si_acepto(self):
        self.miembro(self.maria, acepta=True)
        Mascota.objects.create(cliente=self.maria, nombre="Luna", especie="PER")
        fila = h.recordatorios(self.empresa, dias=7)[0]
        self.assertEqual(fila.cliente, self.maria)
        self.assertIn("https://wa.me/50688881234?text=", fila.enlace)
        self.assertIn("Luna", h.mensaje_recordatorio(self.maria, fila.consumible))

    def test_sin_permiso_se_ve_pero_no_se_le_escribe(self):
        self.miembro(self.maria, acepta=False)
        fila = h.recordatorios(self.empresa, dias=7)[0]
        self.assertEqual(fila.enlace, "")

    def test_fuera_del_plazo_no_aparece(self):
        self.assertEqual(h.recordatorios(self.empresa, dias=1), [])


class UnirFichas(BaseHistorial):
    def test_unir_pasa_todo_y_desactiva_la_otra(self):
        otra = Cliente.objects.create(empresa=self.empresa, nombre="Mari R", telefono="7777-0000")
        self.venta_de_comida(otra, hace_dias=3)
        Mascota.objects.create(cliente=otra, nombre="Toby", especie="PER")
        avisar_conflictos(identificar(self.empresa, cedula="112340567", telefono="77770000"))
        unir_clientes(conservar=self.maria, absorber=otra)
        self.assertEqual(len(h.compras_de(self.maria)), 1)
        self.assertTrue(Mascota.objects.filter(cliente=self.maria, nombre="Toby").exists())
        otra.refresh_from_db()
        self.assertFalse(otra.activo)
        self.assertEqual(PosibleDuplicado.objects.get().resolucion, PosibleDuplicado.Resolucion.UNIDOS)


class Pantallas(BaseHistorial):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.miembro(self.maria)
        self.venta_de_comida(self.maria, hace_dias=40)
        self.venta_de_comida(self.maria, hace_dias=23)

    def test_ficha_con_historial_marcas_y_aviso(self):
        r = self.client.get(reverse("manada:ficha", args=[self.maria.pk]))
        self.assertContains(r, "María Rodríguez Solís")
        self.assertContains(r, "Taste of the Wild · 2")
        self.assertContains(r, "Historial de compras")
        self.assertContains(r, "wa.me/50688881234")

    def test_lista_recordatorios_promociones_y_duplicados(self):
        self.assertContains(self.client.get(reverse("manada:clientes")), "María Rodríguez Solís")
        self.assertContains(self.client.get(reverse("manada:recordatorios")), "María Rodríguez Solís")
        r = self.client.get(reverse("manada:promociones"), {"marca": "Taste of the Wild"})
        self.assertContains(r, "María Rodríguez Solís")
        self.assertContains(self.client.get(reverse("manada:duplicados")), "No hay nada pendiente")

    def test_resolver_duplicado_desde_la_ficha(self):
        otra = Cliente.objects.create(empresa=self.empresa, nombre="Otra", telefono="7777-0000")
        aviso = PosibleDuplicado.objects.create(cliente=self.maria, otro=otra, motivo="prueba")
        self.client.post(reverse("manada:resolver_duplicado", args=[aviso.pk]),
                         {"conservar": self.maria.pk, "accion": "distintos"})
        aviso.refresh_from_db()
        self.assertEqual(aviso.resolucion, PosibleDuplicado.Resolucion.DISTINTOS)
        self.assertTrue(Cliente.objects.get(pk=otra.pk).activo)

    def test_esta_en_el_boton_manada_del_inicio_y_no_en_administracion(self):
        # Pedido de Oscar (14/10/2026): todo lo de clientes y mascotas, en Manada.
        self.assertContains(self.client.get("/"), reverse("manada:clientes"))
        self.assertNotContains(self.client.get("/admin/"), reverse("manada:clientes"))

    def test_mascotas_y_excel(self):
        Mascota.objects.create(cliente=self.maria, nombre="Luna", especie="PER", raza="Labrador")
        r = self.client.get(reverse("manada:mascotas"))
        self.assertContains(r, "Luna")
        self.assertContains(r, "María Rodríguez Solís")
        r = self.client.get(reverse("manada:exportar"))
        self.assertEqual(r.status_code, 200)
        from io import BytesIO
        from openpyxl import load_workbook
        hoja = load_workbook(BytesIO(r.content)).active
        fila = [c.value for c in hoja[2]]
        self.assertEqual(fila[0], "María Rodríguez Solís")
        self.assertEqual(fila[11], 2)            # compras
        self.assertIn("Taste of the Wild", fila[14])

    def test_el_cajero_no_entra(self):
        cajero = User.objects.create_user("caja", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        for nombre in ("manada:clientes", "manada:mascotas", "manada:exportar", "manada:recordatorios",
                       "manada:promociones", "manada:duplicados"):
            self.assertNotEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)
        self.assertNotEqual(self.client.get(reverse("manada:ficha", args=[self.maria.pk])).status_code, 200)
