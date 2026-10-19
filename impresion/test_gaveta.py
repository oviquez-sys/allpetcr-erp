"""La gaveta de dinero se abre sola SOLO con ventas en efectivo (19/10/2026)."""
import json

from django.test import override_settings
from django.urls import reverse

from caja.test_auditoria_2026_09 import Base

from .models import TrabajoImpresion
from .tiquete import ABRIR_GAVETA


@override_settings(IMPRESION_FORZAR_AGENTE=True, TIQUETE_AUTOMATICO=True, GAVETA_AUTOMATICA=True)
class GavetaDeDinero(Base):
    def vender(self, medio, **extra):
        self.client.force_login(self.oscar)
        r = self.client.post(reverse("ventas:vender"), json.dumps({
            "medio_pago": medio, "lineas": [{"producto_id": self.producto.pk, "cantidad": 1}], **extra,
        }), content_type="application/json")
        self.assertTrue(r.json()["ok"], r.json())
        return bytes(TrabajoImpresion.objects.order_by("-id").first().contenido)

    def test_efectivo_abre(self):
        self.assertTrue(self.vender("EFE").startswith(ABRIR_GAVETA))

    def test_tarjeta_sinpe_no_abren(self):
        self.assertNotIn(ABRIR_GAVETA, self.vender("TAR"))
        self.assertNotIn(ABRIR_GAVETA, self.vender("SIN"))

    def test_mixto_con_efectivo_abre(self):
        datos = self.vender("MIX", pagos=[{"medio": "EFE", "monto": 2000}, {"medio": "TAR", "monto": 3000}])
        self.assertTrue(datos.startswith(ABRIR_GAVETA))

    def test_mixto_sin_efectivo_no_abre(self):
        datos = self.vender("MIX", pagos=[{"medio": "SIN", "monto": 2000}, {"medio": "TAR", "monto": 3000}])
        self.assertNotIn(ABRIR_GAVETA, datos)

    def test_reimprimir_no_abre(self):
        self.vender("EFE")
        from ventas.models import FacturaVenta
        r = self.client.post(reverse("impresion:tiquete", args=[FacturaVenta.objects.get().pk]))
        self.assertTrue(r.json()["ok"])
        self.assertNotIn(ABRIR_GAVETA, bytes(TrabajoImpresion.objects.order_by("-id").first().contenido))

    @override_settings(GAVETA_AUTOMATICA=False)
    def test_se_puede_apagar(self):
        self.assertNotIn(ABRIR_GAVETA, self.vender("EFE"))
