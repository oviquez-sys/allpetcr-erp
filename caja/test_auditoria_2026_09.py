"""Caja compartida (CAJ-03) y arqueo de tarjeta y SINPE (CAJ-02), auditoría 26/09/2026."""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from catalogo.models import Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta
from ventas.services import registrar_venta

from .models import SesionCaja
from .services import abrir_caja, cerrar_caja, sesion_abierta_de


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        self.oscar = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.francisco = User.objects.create_user("francisco", password="x", is_staff=True)
        self.francisco.groups.add(Group.objects.get(name="Cajero"))
        self.producto = Producto.objects.create(empresa=self.empresa, sku="P1", nombre="Arnés", precio_venta=5000)
        registrar_movimiento(producto=self.producto, bodega=Bodega.objects.get(), tipo="INI",
                             cantidad=Decimal("10"), costo_unitario=Decimal("2000"), referencia="INI")
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.oscar, monto_apertura=Decimal("10000"))


class CajaCompartida(Base):
    def test_el_otro_vende_en_la_caja_abierta(self):
        self.assertEqual(sesion_abierta_de(self.francisco), self.sesion)
        self.client.force_login(self.francisco)
        r = self.client.post(reverse("ventas:vender"),
                             '{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":1}]}' % self.producto.pk,
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        venta = FacturaVenta.objects.get()
        self.assertEqual(venta.sesion_caja, self.sesion)
        self.assertEqual(venta.usuario, self.francisco)        # la venta queda firmada por quien la hizo

    def test_no_se_abre_una_segunda_caja(self):
        with self.assertRaises(ValidationError):
            abrir_caja(sucursal=self.sucursal, usuario=self.francisco, monto_apertura=Decimal("0"))
        self.assertEqual(SesionCaja.objects.count(), 1)

    def test_cualquiera_la_cierra_y_queda_quien(self):
        sesion = cerrar_caja(sesion=self.sesion, monto_contado=Decimal("10000"), usuario=self.francisco)
        self.assertEqual(sesion.cerrada_por, self.francisco)
        self.assertIsNone(sesion_abierta_de(self.oscar))

    @override_settings(CAJA_COMPARTIDA=False)
    def test_con_la_variable_en_cero_cada_uno_la_suya(self):
        self.assertIsNone(sesion_abierta_de(self.francisco))


class ArqueoTarjetaYSinpe(Base):
    def vender(self, medio, **extra):
        return registrar_venta(sesion_caja=self.sesion, medio_pago=medio, usuario=self.oscar,
                               lineas=[{"producto_id": self.producto.pk, "cantidad": 1}], **extra)

    def test_calcula_lo_esperado_y_guarda_lo_del_comprobante(self):
        self.vender("TAR")
        self.vender("SIN")
        self.vender("MIX", pagos=[{"medio": "EFE", "monto": 2000}, {"medio": "TAR", "monto": 3000}])
        sesion = cerrar_caja(sesion=self.sesion, monto_contado=Decimal("12000"), usuario=self.oscar,
                             tarjeta_contado=Decimal("8000"), sinpe_contado=Decimal("4000"))
        self.assertEqual(sesion.tarjeta_esperado, Decimal("8000"))
        self.assertEqual(sesion.sinpe_esperado, Decimal("5000"))
        self.assertEqual(sesion.tarjeta_contado, Decimal("8000"))
        self.assertEqual(sesion.sinpe_contado, Decimal("4000"))         # falta un SINPE: se ve
        self.assertEqual(sesion.monto_esperado, Decimal("12000"))

    def test_vacio_no_es_cero(self):
        sesion = cerrar_caja(sesion=self.sesion, monto_contado=Decimal("10000"), usuario=self.oscar)
        self.assertIsNone(sesion.tarjeta_contado)
        self.assertIsNone(sesion.sinpe_contado)

    def test_la_pantalla_pide_datafono_y_sinpe(self):
        self.client.force_login(self.oscar)
        r = self.client.get(reverse("caja:cerrar"))
        self.assertContains(r, "datáfono")
        self.assertContains(r, "SINPE")
