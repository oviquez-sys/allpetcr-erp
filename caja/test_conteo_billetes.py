"""Cierre contando billete por billete y moneda por moneda (14/10/2026)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from . import denominaciones
from .models import SesionCaja
from .services import cerrar_caja
from .test_auditoria_2026_09 import Base


class DenominacionesVigentes(Base):
    def test_solo_las_que_circulan_segun_el_bccr(self):
        # Sin el billete de ₡50.000 ni la moneda de ₡5 (fuera de circulación).
        self.assertEqual(denominaciones.BILLETES, (20000, 10000, 5000, 2000, 1000))
        self.assertEqual(denominaciones.MONEDAS, (500, 100, 50, 25, 10))

    def test_la_pantalla_pide_cada_una(self):
        self.client.force_login(self.oscar)
        r = self.client.get(reverse("caja:cerrar"))
        for v in denominaciones.TODAS:
            self.assertContains(r, f'name="den_{v}"')
        self.assertNotContains(r, 'name="den_50000"')
        self.assertNotContains(r, 'name="den_5"')
        self.assertNotContains(r, 'name="monto_contado"')


class CierrePorConteo(Base):
    def test_el_servidor_suma_y_guarda_el_desglose(self):
        self.client.force_login(self.oscar)
        r = self.client.post(reverse("caja:cerrar"), {
            "den_5000": "1", "den_1000": "4", "den_500": "1", "den_100": "4", "den_25": "",
            "monto_contado": "999999",          # lo que mande el navegador no cuenta
        })
        self.assertEqual(r.status_code, 302)
        s = SesionCaja.objects.get()
        self.assertEqual(s.estado, SesionCaja.Estado.CERRADA)
        self.assertEqual(s.monto_contado, Decimal("9900"))
        self.assertEqual(s.diferencia, Decimal("-100"))      # abrió con ₡10.000
        self.assertEqual(s.conteo_efectivo, {"5000": 1, "1000": 4, "500": 1, "100": 4})
        self.assertEqual(s.desglose()[0], (5000, 1, 5000))

    def test_todo_vacio_es_cero(self):
        self.client.force_login(self.oscar)
        self.client.post(reverse("caja:cerrar"), {})
        self.assertEqual(SesionCaja.objects.get().monto_contado, Decimal("0"))

    def test_no_acepta_negativos_ni_denominaciones_que_no_existen(self):
        self.client.force_login(self.oscar)
        r = self.client.post(reverse("caja:cerrar"), {"den_1000": "-2"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SesionCaja.objects.get().estado, SesionCaja.Estado.ABIERTA)
        with self.assertRaises(ValidationError):
            cerrar_caja(sesion=self.sesion, conteo={"50000": 1})
        with self.assertRaises(ValidationError):
            cerrar_caja(sesion=self.sesion, conteo={"5": 3})

    def test_el_cierre_viejo_por_monto_sigue_funcionando(self):
        s = cerrar_caja(sesion=self.sesion, monto_contado=Decimal("10000"))
        self.assertIsNone(s.conteo_efectivo)
        self.assertEqual(s.desglose(), [])
