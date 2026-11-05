"""Fase 1 del encargo v3 (05/11/2026): medir.

Lo que no se puede romper: ninguna venta sin cliente queda sin razón; el
tablero cuenta igual que la caja; el punto de equilibrio sale de los gastos
fijos configurados; lo recién llegado no cuenta como «plata parada»; y la
compra avisa de lo que no se vende sin bloquear.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Producto
from compras.control import avisos as avisos_compra
from inventario.models import MovimientoInventario
from inventario.services import registrar_movimiento
from ventas.models import Cliente, FacturaVenta
from ventas.services import registrar_venta
from ventas.test_auditoria_2026_09 import Base

from . import tablero as tb
from .models import MetaNegocio

HOY = timezone.localdate


class ConDatos(Base):
    def setUp(self):
        super().setUp()
        Group.objects.get_or_create(name="Gerente")[0].user_set.add(self.usuario)
        raiz = Categoria.objects.create(nombre="Alimento")
        self.saco = Producto.objects.create(
            empresa=self.empresa, sku="A1", nombre="Saco 2 kg", precio_venta=Decimal("11300"),
            impuesto=self.iva, cabys="2331000000000", categoria=raiz)
        registrar_movimiento(producto=self.saco, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("20"), costo_unitario=Decimal("8000"), referencia="INI")
        self.ana = Cliente.objects.create(empresa=self.empresa, nombre="Ana", telefono="88881111")

    def venta(self, *productos, cliente=None, **extra):
        return registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario, cliente=cliente,
                               lineas=[{"producto_id": p.pk, "cantidad": 1} for p in productos], **extra)

    def hace(self, factura, dias):
        FacturaVenta.objects.filter(pk=factura.pk).update(creado_en=timezone.now() - timedelta(days=dias))


class SinClienteSiempreConRazon(ConDatos):
    def test_sin_razon_queda_como_no_se_le_pregunto(self):
        self.assertEqual(self.venta(self.producto).sin_cliente, "SP")

    def test_no_quiso(self):
        self.assertEqual(self.venta(self.producto, sin_cliente="NQ").sin_cliente, "NQ")

    def test_con_cliente_no_lleva_razon(self):
        self.assertEqual(self.venta(self.producto, cliente=self.ana, sin_cliente="NQ").sin_cliente, "")

    def test_el_pos_manda_la_razon(self):
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("ventas:vender"), json.dumps({
            "medio_pago": "EFE", "lineas": [{"producto_id": self.producto.pk, "cantidad": 1}],
            "clave": "q1", "sin_cliente": "NQ"}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(FacturaVenta.objects.get().sin_cliente, "NQ")
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, 'id="dlgQuien"')
        self.assertContains(r, "No quiso dar datos")
        self.assertContains(r, "Pasaba por aquí")

    def test_como_nos_conocio_al_crear_en_caja(self):
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("ventas:cliente_rapido"), json.dumps({
            "nombre": "Luis", "telefono": "8777-2222", "como_nos_conocio": "INS"}),
            content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(Cliente.objects.get(nombre="Luis").como_nos_conocio, "INS")
        # Un valor que no está en la lista no se guarda.
        self.client.post(reverse("ventas:cliente_rapido"), json.dumps({
            "nombre": "Eva", "telefono": "8777-3333", "como_nos_conocio": "TIKTOK"}),
            content_type="application/json")
        self.assertEqual(Cliente.objects.get(nombre="Eva").como_nos_conocio, "")


class Tablero(ConDatos):
    def test_numeros_del_dia(self):
        self.venta(self.producto, self.saco, cliente=self.ana)        # 5.300 + 11.300
        self.venta(self.producto, sin_cliente="NQ")                     # 5.300
        r = tb.calcular(self.empresa, HOY(), HOY())
        self.assertEqual(r["ventas"], 2)
        self.assertEqual(r["venta"], Decimal("21900.00"))
        self.assertEqual(r["con_cliente"]["pct"], 50)
        self.assertEqual(r["con_cliente"]["cajeros"][0]["no_quiso"], 1)
        self.assertEqual(r["clientes"]["nuevos"], 1)
        self.assertEqual(r["activos"], 1)                               # Ana compró alimento
        self.assertEqual(r["alimento"], {"con_alimento": 1, "con_otra": 1, "pct": 100})
        self.assertEqual(r["tiquete_mediano"], Decimal("10950"))
        # Ganancia bruta = sin IVA − costo: (5300+11300+5300)/1,13 − (1500+8000+1500).
        sin_iva = sum(l.subtotal for f in FacturaVenta.objects.all() for l in f.lineas.all())
        self.assertEqual(r["ganancia"], sin_iva - Decimal("11000"))

    def test_volvio(self):
        vieja = self.venta(self.saco, cliente=self.ana)
        self.hace(vieja, 10)
        self.venta(self.producto, cliente=self.ana)
        r = tb.calcular(self.empresa, HOY(), HOY())
        self.assertEqual((r["clientes"]["nuevos"], r["clientes"]["volvieron"]), (0, 1))

    def test_punto_de_equilibrio_con_los_gastos_configurados(self):
        meta = MetaNegocio.de(self.empresa)
        self.assertEqual(tb.gasto_fijo_dia(meta), Decimal("32885"))   # 855.000 × 12 / 52 / 6
        meta.save()
        lunes = HOY() - timedelta(days=HOY().weekday())
        self.assertEqual(tb.dias_abiertos(meta, lunes, lunes + timedelta(days=6)), 6)   # domingo cerrado
        r = tb.calcular(self.empresa, HOY(), HOY())                    # sin ventas: margen de respaldo 25 %
        if meta.abre(HOY()):
            self.assertEqual(r["equilibrio"], Decimal("131540"))

    def test_periodos(self):
        hoy = HOY()
        self.assertEqual(tb.periodo({"periodo": "mes"}, hoy)[0], hoy.replace(day=1))
        self.assertEqual(tb.periodo({"periodo": "semana"}, hoy)[0].weekday(), 0)
        d, h, k = tb.periodo({"periodo": "rango", "desde": "2026-10-01", "hasta": "2999-01-01"}, hoy)
        self.assertEqual((d, h, k), (hoy - timedelta(days=(hoy - d).days), hoy, "rango"))
        self.assertEqual(tb.periodo({"periodo": "rango", "desde": "x"}, hoy), (hoy, hoy, "hoy"))

    def test_plata_parada_no_cuenta_lo_recien_llegado(self):
        viejo = Producto.objects.create(empresa=self.empresa, sku="V1", nombre="Peluche", precio_venta=Decimal("3000"),
                                        impuesto=self.iva, cabys="2921001000000")
        registrar_movimiento(producto=viejo, bodega=self.bodega, tipo="INI", cantidad=Decimal("4"),
                             costo_unitario=Decimal("1000"), referencia="INI")
        MovimientoInventario.objects.filter(producto=viejo).update(fecha=timezone.now() - timedelta(days=65))
        inv = tb.inventario_parado(self.empresa, HOY())
        tramos = {t["dias"]: t for t in inv["tramos"]}
        self.assertEqual(tramos[60]["costo"], Decimal("4000"))
        self.assertEqual(tramos[90]["costo"], 0)
        self.assertEqual(inv["lista"][0]["producto"], self.saco)        # el saco nunca vendido pesa más
        self.assertTrue(all(f["dias"] < 30 for f in inv["lista"] if f["producto"] != viejo))

    def test_pantalla(self):
        self.venta(self.producto, sin_cliente="NQ")
        self.client.force_login(self.usuario)
        for periodo in ("hoy", "semana", "mes", "rango"):
            r = self.client.get(reverse("core:tablero"), {"periodo": periodo})
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Clientes activos de alimento")
        cajero = User.objects.create_user("maria", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        self.assertNotEqual(self.client.get(reverse("core:tablero")).status_code, 200)


class ControlAntesDeComprar(ConDatos):
    def test_avisos(self):
        nuevo = Producto.objects.create(empresa=self.empresa, sku="N1", nombre="Nuevo", precio_venta=Decimal("1000"),
                                        impuesto=self.iva, cabys="2921001000000")
        self.venta(self.producto)                                        # 1 vendida en 30 días, quedan 9
        self.producto.refresh_from_db(); self.saco.refresh_from_db()
        textos = avisos_compra(self.empresa, [self.producto, self.saco, nuevo])
        self.assertEqual(textos[self.saco.pk], "Nunca se ha vendido (hay 20 en existencia).")
        self.assertNotIn(nuevo.pk, textos)                               # lo nuevo no avisa
        self.assertEqual(textos[self.producto.pk],
                         "Ya hay 9 meses de inventario: 9 en existencia y se venden 1 al mes.")

    def test_la_pantalla_de_compras_trae_el_aviso(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("compras:nueva"))
        self.assertContains(r, "Nunca se ha vendido")
