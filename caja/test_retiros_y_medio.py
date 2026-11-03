"""Sacar efectivo para depositar y corregir el medio de pago de una venta
(02/11/2026, pedido de Oscar)."""
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from contabilidad.models import Asiento, LineaAsiento
from impresion.cierre import bytes_retiro
from impresion.models import TrabajoImpresion
from impresion.tiquete import ABRIR_GAVETA
from ventas.medio_pago import cambiar_medio_pago
from ventas.models import CambioMedioPago, FacturaVenta
from ventas.services import registrar_venta

from .models import MovimientoCaja, RetiroCaja, SesionCaja
from .retiros import registrar_deposito, registrar_retiro
from .services import calcular_arqueo, cerrar_caja, esperado_por_medio, monto_esperado
from .test_auditoria_2026_09 import Base


class Retiros(Base):
    """Abre con ₡10.000; se vende en efectivo para tener plata que sacar."""

    def setUp(self):
        super().setUp()
        for _ in range(6):     # 6 × ₡5.000 → ₡40.000 en la gaveta
            registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.oscar,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])

    def test_el_retiro_descuenta_lo_esperado_y_el_cierre_calza(self):
        r = registrar_retiro(sesion=self.sesion, usuario=self.oscar, conteo={"20000": 1, "10000": 1})
        self.assertEqual(r.monto, Decimal("30000"))
        self.assertEqual(r.estado, RetiroCaja.Estado.POR_DEPOSITAR)
        self.assertEqual(monto_esperado(self.sesion), Decimal("10000"))
        mov = MovimientoCaja.objects.get(tipo=MovimientoCaja.Tipo.RETIRO)
        self.assertEqual((mov.monto, mov.referencia), (Decimal("-30000"), r.referencia))
        filas = calcular_arqueo(self.sesion, efectivo=Decimal("10000"), tarjeta=0, sinpe=0)
        self.assertTrue(all(f["calza"] for f in filas))
        self.assertFalse(Asiento.objects.filter(origen="DEP").exists())   # todavía no llegó al banco

    def test_no_se_saca_mas_de_lo_que_deberia_haber(self):
        with self.assertRaises(ValidationError):
            registrar_retiro(sesion=self.sesion, usuario=self.oscar, monto=Decimal("50000"))

    def test_el_deposito_hace_el_asiento_banco_contra_caja(self):
        r1 = registrar_retiro(sesion=self.sesion, usuario=self.oscar, conteo={"10000": 2})
        r2 = registrar_retiro(sesion=self.sesion, usuario=self.oscar, monto=Decimal("5000"))
        registrar_deposito(retiros=[r1, r2], usuario=self.oscar, comprobante="BN-778899")
        r1.refresh_from_db()
        self.assertEqual((r1.estado, r1.comprobante), (RetiroCaja.Estado.DEPOSITADO, "BN-778899"))
        asiento = Asiento.objects.get(origen="DEP")
        lineas = {l.cuenta.codigo: (l.debe, l.haber) for l in LineaAsiento.objects.filter(asiento=asiento)}
        self.assertEqual(lineas["1102"], (Decimal("25000"), Decimal("0")))     # Bancos
        self.assertEqual(lineas["1101"], (Decimal("0"), Decimal("25000")))     # Caja general
        with self.assertRaises(ValidationError):                               # no se deposita dos veces
            registrar_deposito(retiros=[r1], usuario=self.oscar, comprobante="otra")

    def test_el_deposito_pide_comprobante(self):
        r = registrar_retiro(sesion=self.sesion, usuario=self.oscar, monto=Decimal("5000"))
        with self.assertRaises(ValidationError):
            registrar_deposito(retiros=[r], usuario=self.oscar, comprobante="")

    def test_pantalla_de_retiro_imprime_comprobante_que_abre_la_gaveta(self):
        self.client.force_login(self.oscar)
        r = self.client.post(reverse("caja:retiro"), {"accion": "retirar", "den_20000": "1", "den_10000": "1",
                                                      "nota": "para el BN"})
        self.assertRedirects(r, reverse("caja:retiro"), fetch_redirect_response=False)
        retiro = RetiroCaja.objects.get()
        self.assertEqual(retiro.conteo, {"20000": 1, "10000": 1})
        papel = bytes(TrabajoImpresion.objects.get().contenido)
        self.assertTrue(papel.startswith(ABRIR_GAVETA))
        self.assertIn(b"RETIRO DE CAJA", papel)
        r = self.client.post(reverse("caja:retiro"), {"accion": "depositar", "retiro": [retiro.pk],
                                                      "comprobante": "12345", "fecha": "2026-11-02"})
        retiro.refresh_from_db()
        self.assertEqual(retiro.estado, RetiroCaja.Estado.DEPOSITADO)

    def test_el_cajero_no_saca_efectivo(self):
        self.client.force_login(self.francisco)          # grupo Cajero
        r = self.client.get(reverse("caja:retiro"))
        self.assertNotEqual(r.status_code, 200)

    def test_al_cerrar_el_gerente_registra_el_retiro_que_no_anoto(self):
        # Sacó ₡30.000 para el banco y no lo anotó: en la gaveta hay 10.000.
        self.client.force_login(self.oscar)
        r = self.client.post(reverse("caja:cerrar"), {"den_10000": "1", "tarjeta_contado": "0", "sinpe_contado": "0"})
        self.assertContains(r, "¿Sacaste efectivo para depositar?")
        r = self.client.post(reverse("caja:cerrar"), {"paso": "retiro", "firma": r.context["firma"],
                                                      "monto": "30000", "nota": "billetes de 20 y 10 mil"})
        self.assertEqual(r.status_code, 302)
        s = SesionCaja.objects.get()
        self.assertEqual(s.estado, SesionCaja.Estado.CERRADA)
        self.assertFalse(s.diferencias.exists())          # calzó: el faltante era el retiro
        self.assertEqual(RetiroCaja.objects.get().monto, Decimal("30000"))

    def test_el_cajero_no_puede_tapar_un_faltante_con_un_retiro(self):
        self.client.force_login(self.francisco)
        r = self.client.post(reverse("caja:cerrar"), {"den_10000": "1", "tarjeta_contado": "0", "sinpe_contado": "0"})
        self.assertNotContains(r, "¿Sacaste efectivo para depositar?")
        r = self.client.post(reverse("caja:cerrar"), {"paso": "retiro", "firma": r.context["firma"], "monto": "30000"})
        self.assertContains(r, "Solo un gerente")
        self.assertFalse(RetiroCaja.objects.exists())

    def test_el_resumen_y_el_tiquete_muestran_el_retiro(self):
        from .resumen import resumen_cierre
        from impresion.cierre import bytes_cierre

        registrar_retiro(sesion=self.sesion, usuario=self.oscar, conteo={"20000": 1})
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("20000"), tarjeta_contado=0, sinpe_contado=0)
        datos = resumen_cierre(SesionCaja.objects.get())
        self.assertIn(("Retiros para depositar", Decimal("-20000")), datos["efectivo"])
        papel = bytes_cierre(datos).decode("cp850")
        self.assertIn("Retiros para depositar", papel)
        self.assertIn("por depositar", papel)
        self.assertIn("RETIRO DE CAJA", bytes_retiro(datos["retiros"][0], abrir_gaveta=False).decode("cp850"))


class CambioDeMedio(Base):
    def vender(self, medio):
        return registrar_venta(sesion_caja=self.sesion, medio_pago=medio, usuario=self.oscar,
                               lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])

    def test_tarjeta_a_sinpe_sin_tocar_la_gaveta(self):
        f = self.vender("TAR")
        cambiar_medio_pago(factura=f, nuevo="SIN", usuario=self.francisco, motivo="Al final hizo un SINPE")
        f.refresh_from_db()
        self.assertEqual(f.medio_pago, "SIN")
        self.assertEqual(esperado_por_medio(self.sesion), {"TAR": Decimal("0"), "SIN": Decimal("5000")})
        self.assertFalse(MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.CORRECCION).exists())
        self.assertFalse(Asiento.objects.filter(origen="COR").exists())   # las dos van a Bancos
        c = CambioMedioPago.objects.get()
        self.assertEqual((c.anterior, c.nuevo, c.usuario), ("TAR", "SIN", self.francisco))

    def test_efectivo_a_tarjeta_saca_la_plata_de_lo_esperado_y_pasa_a_bancos(self):
        f = self.vender("EFE")
        self.assertEqual(monto_esperado(self.sesion), Decimal("15000"))
        cambiar_medio_pago(factura=f, nuevo="TAR", usuario=self.oscar, motivo="Pagó con tarjeta al final")
        self.assertEqual(monto_esperado(self.sesion), Decimal("10000"))
        self.assertEqual(esperado_por_medio(self.sesion)["TAR"], Decimal("5000"))
        lineas = {l.cuenta.codigo: (l.debe, l.haber)
                  for l in LineaAsiento.objects.filter(asiento__origen="COR")}
        self.assertEqual(lineas, {"1102": (Decimal("5000"), Decimal("0")), "1101": (Decimal("0"), Decimal("5000"))})

    def test_reglas(self):
        f = self.vender("TAR")
        with self.assertRaises(ValidationError):           # sin motivo
            cambiar_medio_pago(factura=f, nuevo="SIN", usuario=self.oscar, motivo="")
        with self.assertRaises(ValidationError):           # mismo medio
            cambiar_medio_pago(factura=f, nuevo="TAR", usuario=self.oscar, motivo="no cambia nada")
        with self.assertRaises(ValidationError):           # a fiado no
            cambiar_medio_pago(factura=f, nuevo="CRE", usuario=self.oscar, motivo="lo quiere fiado")
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("10000"), tarjeta_contado=5000, sinpe_contado=0)
        with self.assertRaises(ValidationError):           # caja cerrada
            cambiar_medio_pago(factura=f, nuevo="SIN", usuario=self.oscar, motivo="muy tarde ya")

    def test_al_cerrar_ofrece_corregir_la_venta_y_cierra_solo(self):
        f = self.vender("TAR")
        self.client.force_login(self.francisco)
        r = self.client.post(reverse("caja:cerrar"), {"den_10000": "1", "tarjeta_contado": "0", "sinpe_contado": "5000"})
        self.assertContains(r, "Pasarla a SINPE Móvil")
        self.assertIn(f, r.context["cruce"]["ventas"])
        r = self.client.post(reverse("caja:cerrar"), {"paso": "corregir", "firma": r.context["firma"],
                                                      "factura": f.pk, "nuevo": "SIN"})
        self.assertEqual(r.status_code, 302)
        s = SesionCaja.objects.get()
        self.assertEqual(s.estado, SesionCaja.Estado.CERRADA)
        self.assertFalse(s.diferencias.exists())
        f.refresh_from_db()
        self.assertEqual(f.medio_pago, "SIN")

    def test_pantalla_desde_el_historial(self):
        f = self.vender("SIN")
        self.client.force_login(self.francisco)
        r = self.client.get(reverse("ventas:historial"))
        self.assertContains(r, reverse("ventas:cambiar_medio", args=[f.pk]))
        r = self.client.post(reverse("ventas:cambiar_medio", args=[f.pk]),
                             {"nuevo": "EFE", "motivo": "Pagó en efectivo", "volver": "/ventas/historial/"})
        self.assertRedirects(r, "/ventas/historial/", fetch_redirect_response=False)
        f.refresh_from_db()
        self.assertEqual(f.medio_pago, "EFE")
        self.assertEqual(monto_esperado(self.sesion), Decimal("15000"))

    def test_el_pos_ofrece_el_cambio_en_la_ultima_venta(self):
        self.client.force_login(self.francisco)
        r = self.client.post(reverse("ventas:vender"),
                             '{"medio_pago":"TAR","lineas":[{"producto_id":%d,"cantidad":1}]}' % self.producto.pk,
                             content_type="application/json")
        self.assertIn("/medio-de-pago/", r.json()["cambiar_medio_url"])
