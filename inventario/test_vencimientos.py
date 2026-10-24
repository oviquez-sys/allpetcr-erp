"""Fechas de vencimiento (pedido de Oscar, 24/10/2026)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Categoria, Producto
from core.models import Empresa

from . import vencimientos as venc
from .models import LoteVencimiento

HOY = date(2026, 10, 24)


class FechasTests(TestCase):
    def test_interpretar_fecha(self):
        self.assertEqual(venc.interpretar_fecha("15/08/2027", HOY), date(2027, 8, 15))
        self.assertEqual(venc.interpretar_fecha("15-08-27", HOY), date(2027, 8, 15))
        self.assertEqual(venc.interpretar_fecha("2027-08-15", HOY), date(2027, 8, 15))
        self.assertEqual(venc.interpretar_fecha("08/2027", HOY), date(2027, 8, 31))
        self.assertEqual(venc.interpretar_fecha("2/28", HOY), date(2028, 2, 29))
        self.assertEqual(venc.interpretar_fecha("ago 2027", HOY), date(2027, 8, 31))
        for malo in ["", "hola", "31/02/2027", "15/08/2050", "01/01/2020"]:
            with self.assertRaises(ValidationError, msg=malo):
                venc.interpretar_fecha(malo, HOY)


class LotesTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        raiz = Categoria.objects.create(nombre="Alimento")
        self.cat = Categoria.objects.create(nombre="Alimento seco", padre=raiz)
        self.p = Producto.objects.create(empresa=self.empresa, sku="B1", nombre="Balance Puppy 2 kg", categoria=self.cat,
                                         codigo_barras="20004200", precio_venta=Decimal("5000"), stock_actual=Decimal("5"))

    def test_lo_que_queda_sale_de_lo_que_vence_mas_tarde(self):
        venc.registrar(self.p, "08/2027", 3)
        venc.registrar(self.p, "15/01/2027", 4)
        self.p.stock_actual = Decimal("5")   # se vendieron 2: las que vencían primero
        lotes, sin_fecha = venc.repartir(self.p, list(self.p.lotes_vencimiento.all()))
        self.assertEqual([(l.fecha_vencimiento, q) for l, q in lotes],
                         [(date(2027, 1, 15), Decimal("2")), (date(2027, 8, 31), Decimal("3"))])
        self.assertEqual(sin_fecha, 0)
        self.p.stock_actual = Decimal("9")
        _, sin_fecha = venc.repartir(self.p, list(self.p.lotes_vencimiento.all()))
        self.assertEqual(sin_fecha, Decimal("2"))

    def test_misma_fecha_suma_y_cantidad_valida(self):
        venc.registrar(self.p, "08/2027", 2)
        venc.registrar(self.p, "31/08/2027", 1)
        self.assertEqual(LoteVencimiento.objects.get().cantidad, Decimal("3"))
        with self.assertRaises(ValidationError):
            venc.registrar(self.p, "08/2027", 0)

    def test_listas(self):
        LoteVencimiento.objects.create(producto=self.p, fecha_vencimiento=date(2026, 10, 1), cantidad=1)
        LoteVencimiento.objects.create(producto=self.p, fecha_vencimiento=date(2027, 6, 1), cantidad=2)
        filas = venc.proximos(self.empresa, 30, hoy=HOY)
        self.assertEqual([f["estado"][0] for f in filas], ["vencido"])
        self.assertEqual(len(venc.proximos(self.empresa, None, hoy=HOY)), 2)
        self.assertEqual([f["faltan"] for f in venc.sin_fecha(self.empresa)], [Decimal("2")])

    def test_pantalla_escanear_guardar_y_borrar(self):
        cajero = User.objects.create_user("c", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(cajero)
        url = reverse("inventario:vencimientos")
        r = self.client.get(url, {"codigo": "20004200"})
        self.assertRedirects(r, f"{url}?ver=30&p={self.p.pk}", fetch_redirect_response=False)
        r = self.client.get(url, {"p": self.p.pk})
        self.assertContains(r, "Balance Puppy 2 kg")
        r = self.client.post(url, {"producto": self.p.pk, "fecha": "08/2027", "cantidad": "3"})
        self.assertEqual(r.status_code, 302)
        lote = LoteVencimiento.objects.get()
        self.assertEqual((lote.fecha_vencimiento, lote.creado_por), (date(2027, 8, 31), cajero))
        r = self.client.post(url, {"producto": self.p.pk, "fecha": "nada", "cantidad": "1"}, follow=True)
        self.assertContains(r, "No entendí la fecha")
        self.client.post(url, {"accion": "borrar", "lote": lote.pk})
        self.assertFalse(LoteVencimiento.objects.exists())
        r = self.client.get(url, {"ver": "sin"})
        self.assertContains(r, "Balance Puppy 2 kg")
