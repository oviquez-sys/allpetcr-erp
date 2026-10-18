"""Ver el cierre anterior al abrir y la apertura al cerrar (17/10/2026)."""
from django.urls import reverse

from .services import cerrar_caja
from .test_auditoria_2026_09 import Base


class AperturaYCierre(Base):
    def test_al_cerrar_se_ve_como_se_abrio(self):
        self.client.force_login(self.oscar)
        html = self.client.get(reverse("caja:cerrar")).content.decode()
        self.assertIn("Así se abrió esta caja", html)
        self.assertIn("₡10.000", html)

    def test_al_abrir_se_ve_el_cierre_anterior(self):
        cerrar_caja(sesion=self.sesion, conteo={"5000": 1, "1000": 4}, usuario=self.oscar)
        self.client.force_login(self.oscar)
        html = self.client.get(reverse("caja:abrir")).content.decode()
        self.assertIn("Así se cerró la caja anterior", html)
        self.assertIn("₡9.000", html)          # contado
        self.assertIn("de menos", html)        # faltaron ₡1.000
        self.assertIn("1 × ₡5.000", html)
