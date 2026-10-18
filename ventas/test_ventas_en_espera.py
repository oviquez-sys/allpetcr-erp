"""Ventas en espera en el POS (17/10/2026): atender a otro cliente sin borrar
la venta del primero. Todo vive en el navegador; acá se verifica que la
pantalla lo traiga y que el cobro siga mandando una sola venta a la vez."""
from caja.test_auditoria_2026_09 import Base
from django.urls import reverse


class VentasEnEspera(Base):
    def test_el_pos_trae_el_boton_y_las_pestanas(self):
        self.client.force_login(self.oscar)
        html = self.client.get(reverse("ventas:pos")).content.decode()
        self.assertIn('id="btnOtraVenta"', html)
        self.assertIn("Atender a otro cliente", html)
        self.assertIn('id="ventasTabs"', html)
        # Lo apartado en otra venta en espera cuenta para el stock disponible.
        self.assertIn("enEspera(p.id)", html)
        # Cada venta conserva su propia clave de cobro (no se duplica al reintentar).
        self.assertIn("clave:null", html)
