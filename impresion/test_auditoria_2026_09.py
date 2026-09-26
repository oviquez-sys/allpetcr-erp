"""TIQ-02 (auditoría 26/09/2026): el POS se entera si el tiquete no salió."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from impresion import cola, servicio
from impresion.models import TrabajoImpresion
from impresion.tests import _Factura, _Linea, _Producto


@override_settings(IMPRESION_FORZAR_AGENTE=True, IMPRESORA_RECIBOS="Recibos de prueba")
class EstadoDelTiquete(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(self.usuario)

    def estado(self, trabajo):
        return self.client.get(reverse("impresion:estado_trabajo", args=[trabajo.pk])).json()

    def test_imprimir_devuelve_el_trabajo_encolado(self):
        trabajo = servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))
        self.assertIsInstance(trabajo, TrabajoImpresion)
        d = self.estado(trabajo)
        self.assertEqual(d["estado"], TrabajoImpresion.PENDIENTE)
        self.assertFalse(d["terminado"])

    def test_si_el_agente_falla_el_pos_lo_sabe(self):
        trabajo = servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))
        cola.reportar(trabajo.pk, ok=False, detalle="La impresora está sin conexión")
        d = self.estado(trabajo)
        self.assertTrue(d["terminado"])
        self.assertFalse(d["ok"])
        self.assertIn("sin conexión", d["detalle"])

    def test_si_imprime_queda_ok(self):
        trabajo = servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))
        cola.reportar(trabajo.pk, ok=True)
        self.assertTrue(self.estado(trabajo)["ok"])

    def test_no_entrega_el_contenido(self):
        trabajo = servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))
        self.assertNotIn("contenido", self.estado(trabajo))
