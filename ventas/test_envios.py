"""Envío pagado junto con la compra (26/11/2026, ventas/envios.py).

El caso: el cliente paga producto + Uber en el mismo SINPE y el cierre salía
con sobrante todos los días. Estas pruebas fijan que el envío no es venta,
que entra al cierre por el medio con que se pagó y que la contabilidad cuadra.
"""
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.urls import reverse

from caja.models import MovimientoCaja
from caja.resumen import resumen_cierre
from caja.services import cerrar_caja, esperado_por_medio, monto_esperado
from contabilidad.models import LineaAsiento
from contabilidad.services import cuenta

from .medio_pago import se_puede_cambiar
from .services import anular_factura, registrar_venta
from .tests import BaseVentas


class EnvioConLaCompra(BaseVentas):
    def venta(self, medio="SIN", envio=2500, pago="TIE", **kw):
        return registrar_venta(sesion_caja=self.sesion, medio_pago=medio, usuario=self.usuario,
                               lineas=[{"producto_id": self.producto.pk, "cantidad": 1}],
                               envio={"monto": envio, "pago": pago} if envio else None, **kw)

    def saldo(self, logico):
        c = cuenta(self.empresa, logico)
        s = LineaAsiento.objects.filter(cuenta=c).aggregate(d=Sum("debe"), h=Sum("haber"))
        return (s["d"] or 0) - (s["h"] or 0)

    def test_sinpe_producto_mas_uber_cuadra_el_cierre(self):
        f = self.venta()
        self.assertEqual((f.total, f.envio, f.envio_medio, f.total_pagado),
                         (Decimal("5000"), Decimal("2500"), "SIN", Decimal("7500")))
        self.assertEqual(esperado_por_medio(self.sesion)["SIN"], Decimal("7500"))
        self.assertFalse(MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.ENVIO).exists())
        self.assertEqual(self.saldo("envios"), 0)                 # entra y sale el mismo día
        self.assertEqual(self.saldo("ventas"), Decimal("-5000"))  # la venta no cambia
        sesion = cerrar_caja(sesion=self.sesion, monto_contado=Decimal("20000"), usuario=self.usuario,
                             tarjeta_contado=Decimal("0"), sinpe_contado=Decimal("7500"))
        self.assertEqual(sesion.sinpe_esperado, Decimal("7500"))
        r = resumen_cierre(sesion)
        self.assertEqual(r["envios"]["total"], Decimal("2500"))
        self.assertEqual(r["ventas_total"], Decimal("5000"))

    def test_efectivo_y_pagado_de_la_gaveta(self):
        f = self.venta(medio="EFE", pago="CAJ", monto_recibido=10000)
        self.assertEqual(f.vuelto, Decimal("2500"))               # 10.000 − (5.000 + 2.500)
        self.assertEqual(monto_esperado(self.sesion), Decimal("25000"))   # apertura + venta; el envío entra y sale
        self.assertEqual(MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.ENVIO).count(), 2)

    def test_sinpe_y_mensajero_pagado_de_la_gaveta(self):
        self.venta(pago="CAJ")
        self.assertEqual(monto_esperado(self.sesion), Decimal("17500"))   # salieron 2.500 para el Uber
        self.assertEqual(esperado_por_medio(self.sesion)["SIN"], Decimal("7500"))

    def test_tarjeta_personal_de_un_socio(self):
        self.venta(pago="SOC")
        self.assertEqual(self.saldo("socios"), Decimal("-2500"))   # la tienda le debe al socio

    def test_mixto_el_envio_sale_del_sinpe(self):
        f = self.venta(medio="MIX", pagos=[{"medio": "EFE", "monto": 4000}, {"medio": "SIN", "monto": 3500}])
        self.assertEqual(f.envio_medio, "SIN")
        self.assertEqual(sorted((m, x) for m, x in f.desglose_pagos()), [("EFE", Decimal("4000")), ("SIN", Decimal("1000"))])
        self.assertEqual(esperado_por_medio(self.sesion)["SIN"], Decimal("3500"))

    def test_mixto_que_sin_envio_queda_de_un_solo_medio(self):
        f = self.venta(medio="MIX", pagos=[{"medio": "EFE", "monto": 5000}, {"medio": "SIN", "monto": 2500}])
        self.assertEqual((f.medio_pago, f.envio_medio), ("EFE", "SIN"))

    def test_no_se_fia_ni_va_sin_decir_como_se_pago(self):
        from ventas.models import Cliente
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Ana", limite_credito=Decimal("50000"))
        with self.assertRaises(ValidationError):
            self.venta(medio="CRE", cliente=cliente)
        with self.assertRaises(ValidationError):
            self.venta(pago="")

    def test_anular_deshace_todo(self):
        f = self.venta(medio="EFE", pago="CAJ")
        anular_factura(factura=f, motivo="error de prueba", usuario=self.usuario)
        self.assertEqual(monto_esperado(self.sesion), Decimal("20000"))
        self.assertEqual(self.saldo("envios"), 0)
        self.assertEqual(self.saldo("caja"), 0)

    def test_no_se_cambia_el_medio_de_una_venta_con_envio(self):
        self.assertIn("envío", se_puede_cambiar(self.venta()))

    def test_tiquete_dice_lo_que_pago(self):
        from impresion.tiquete import bytes_tiquete
        datos = bytes_tiquete(self.venta())
        self.assertIn(b"TOTAL PAGADO", datos)
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("ventas:tiquete", args=[self.venta().pk]))
        self.assertContains(r, "Total pagado")

    def test_desde_la_caja(self):
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("ventas:vender"), content_type="application/json", data=json.dumps({
            "medio_pago": "SIN", "lineas": [{"producto_id": self.producto.pk, "cantidad": 1}],
            "sin_cliente": "NQ", "envio": {"monto": 2500, "pago": "CAJ"}}))
        d = r.json()
        self.assertTrue(d["ok"], d)
        self.assertEqual((d["total"], d["envio"], d["envio_pago"]), (5000.0, 2500.0, "CAJ"))
