"""Cierre que compara cada medio, pide explicar lo que no calza, avisa por
correo e imprime el resumen (02/11/2026, pedido de Oscar)."""
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from impresion.cierre import bytes_cierre
from impresion.models import TrabajoImpresion
from ventas.services import registrar_venta

from .models import DiferenciaCaja, SesionCaja
from .resumen import resumen_cierre
from .services import calcular_arqueo, cerrar_caja, esperado_por_medio, sugerir_cruce
from .test_auditoria_2026_09 import Base

URL = reverse("caja:cerrar")


@override_settings(CIERRE_AVISO_DESTINATARIOS=["oscar@x.com", "francisco@x.com"], CIERRE_TOLERANCIA="0")
class CierreJustificado(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.francisco)

    def vender(self, medio, **extra):
        return registrar_venta(sesion_caja=self.sesion, medio_pago=medio, usuario=self.oscar,
                               lineas=[{"producto_id": self.producto.pk, "cantidad": 1}], **extra)

    def contar(self, efectivo_5000=2, tarjeta="0", sinpe="0", **extra):
        return self.client.post(URL, {"den_5000": str(efectivo_5000), "tarjeta_contado": tarjeta,
                                      "sinpe_contado": sinpe, **extra})

    # --- Todo calza ---------------------------------------------------------------
    def test_si_todo_calza_cierra_directo_imprime_y_no_avisa(self):
        self.vender("TAR")
        r = self.contar(efectivo_5000=2, tarjeta="5000")
        self.assertRedirects(r, reverse("caja:abrir"), fetch_redirect_response=False)
        s = SesionCaja.objects.get()
        self.assertEqual(s.estado, SesionCaja.Estado.CERRADA)
        self.assertFalse(s.diferencias.exists())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(s.aviso_diferencia, "")
        trabajo = TrabajoImpresion.objects.get(tipo=TrabajoImpresion.CIERRE)
        self.assertIn(b"CIERRE DE CAJA", bytes(trabajo.contenido))
        self.assertIn(b"CUADRA", bytes(trabajo.contenido))

    def test_datafono_y_sinpe_son_obligatorios(self):
        r = self.client.post(URL, {"den_5000": "2"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "0 si no hubo")
        self.assertEqual(SesionCaja.objects.get().estado, SesionCaja.Estado.ABIERTA)

    # --- No calza: pide explicación ----------------------------------------------
    def test_diferencia_en_efectivo_pide_explicacion_y_no_cierra_sin_ella(self):
        r = self.contar(efectivo_5000=1)                     # abrió con 10.000, hay 5.000
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Faltan ₡5.000")
        self.assertEqual(SesionCaja.objects.get().estado, SesionCaja.Estado.ABIERTA)
        r = self.client.post(URL, {"paso": "justificar", "firma": r.context["firma"], "motivo_EFE": "",
                                   "explicacion_EFE": ""})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Elegí el motivo")
        self.assertEqual(SesionCaja.objects.get().estado, SesionCaja.Estado.ABIERTA)

    def test_con_explicacion_cierra_guarda_la_diferencia_y_avisa(self):
        r = self.contar(efectivo_5000=1)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(URL, {"paso": "justificar", "firma": r.context["firma"], "motivo_EFE": "GAS",
                                       "explicacion_EFE": "Se compró una escoba con plata de la gaveta."})
        self.assertEqual(r.status_code, 302)
        s = SesionCaja.objects.get()
        self.assertEqual(s.estado, SesionCaja.Estado.CERRADA)
        d = s.diferencias.get()
        self.assertEqual((d.medio, d.esperado, d.contado, d.diferencia), ("EFE", Decimal("10000"),
                                                                         Decimal("5000"), Decimal("-5000")))
        self.assertEqual(d.motivo, "GAS")
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ["oscar@x.com", "francisco@x.com"])
        self.assertIn("Efectivo: faltan ₡5.000", correo.subject)
        self.assertIn("escoba", correo.body)
        self.assertIn("enviado", s.aviso_diferencia)
        self.assertIn(b"NO CALZ", bytes(TrabajoImpresion.objects.get(tipo="cierre").contenido))

    def test_la_clienta_iba_con_tarjeta_y_pago_por_sinpe(self):
        self.vender("TAR")                                    # se registró como tarjeta
        r = self.contar(efectivo_5000=2, tarjeta="0", sinpe="5000")   # pero entró por SINPE
        self.assertContains(r, "parece una venta")
        form = r.context["form"]
        self.assertEqual(form["motivo_TAR"].value(), DiferenciaCaja.Motivo.CRUCE)
        self.assertIn("se registró como Tarjeta pero se cobró por SINPE", form["explicacion_SIN"].value())
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(URL, {"paso": "justificar", "firma": r.context["firma"],
                                       "motivo_TAR": "CRU", "explicacion_TAR": form["explicacion_TAR"].value(),
                                       "motivo_SIN": "CRU", "explicacion_SIN": form["explicacion_SIN"].value()})
        self.assertEqual(r.status_code, 302)
        s = SesionCaja.objects.get()
        self.assertEqual(sorted(s.diferencias.values_list("medio", "diferencia")),
                         [("SIN", Decimal("5000")), ("TAR", Decimal("-5000"))])
        self.assertIn("se compensan", mail.outbox[0].body)

    def test_volver_a_contar_deja_el_primer_conteo_guardado(self):
        r = self.contar(efectivo_5000=1)
        r = self.client.post(URL, {"paso": "recontar", "firma": r.context["firma"]})
        self.assertContains(r, "Estás volviendo a contar")
        previos = r.context["previos_firmado"]
        r = self.contar(efectivo_5000=2, previos=previos)    # ahora sí calza
        self.assertEqual(r.status_code, 302)
        s = SesionCaja.objects.get()
        self.assertEqual(s.estado, SesionCaja.Estado.CERRADA)
        self.assertEqual(len(s.conteos_previos), 1)
        self.assertEqual(s.conteos_previos[0]["efectivo"], "5000")

    def test_una_firma_tocada_no_cierra(self):
        r = self.client.post(URL, {"paso": "justificar", "firma": "inventada", "motivo_EFE": "OTR",
                                   "explicacion_EFE": "cualquier cosa"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SesionCaja.objects.get().estado, SesionCaja.Estado.ABIERTA)

    def test_si_entra_una_venta_mientras_se_explica_vuelve_a_mostrar(self):
        r = self.contar(efectivo_5000=1)
        firma = r.context["firma"]
        self.vender("EFE")                                    # lo esperado sube ₡5.000
        r = self.client.post(URL, {"paso": "justificar", "firma": firma, "motivo_EFE": "OTR",
                                   "explicacion_EFE": "explicación vieja"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "las diferencias cambiaron")
        self.assertContains(r, "Faltan ₡10.000")
        self.assertEqual(SesionCaja.objects.get().estado, SesionCaja.Estado.ABIERTA)

    # --- Reglas del servicio --------------------------------------------------------
    def test_el_servicio_no_cierra_sin_explicar_si_se_le_piden_explicaciones(self):
        with self.assertRaises(ValidationError):
            cerrar_caja(sesion=self.sesion, monto_contado=Decimal("9000"), tarjeta_contado=0, sinpe_contado=0,
                        justificaciones={})
        self.assertEqual(SesionCaja.objects.get().estado, SesionCaja.Estado.ABIERTA)

    def test_un_abono_de_fiado_por_sinpe_cuenta_en_lo_esperado(self):
        from ventas.cxc import registrar_abono
        from ventas.models import Cliente, DocumentoCxC

        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Ana", limite_credito=50000)
        self.vender("CRE", cliente=cliente)
        doc = DocumentoCxC.objects.get()
        registrar_abono(documento=doc, monto=Decimal("2000"), medio="SIN", usuario=self.oscar)
        self.assertEqual(esperado_por_medio(self.sesion)["SIN"], Decimal("2000"))

    def test_sugerencia_de_cruce_solo_si_se_compensan(self):
        filas = calcular_arqueo(self.sesion, efectivo=Decimal("10000"), tarjeta=Decimal("0"), sinpe=Decimal("300"))
        self.assertEqual(sugerir_cruce(filas), {})           # sobra SINPE pero no falta nada

    @override_settings(CIERRE_TOLERANCIA="100")
    def test_la_tolerancia_se_puede_configurar(self):
        r = self.client.post(URL, {"den_5000": "1", "den_1000": "4", "den_500": "1", "den_100": "4",
                                   "tarjeta_contado": "0", "sinpe_contado": "0"})   # ₡9.900
        self.assertEqual(r.status_code, 302)
        self.assertFalse(SesionCaja.objects.get().diferencias.exists())

    # --- Tiquete y reimpresión ---------------------------------------------------
    def test_el_tiquete_trae_ventas_por_medio_y_la_explicacion(self):
        self.vender("SIN")
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("9000"), tarjeta_contado=0, sinpe_contado=5000,
                    usuario=self.francisco, justificaciones={"EFE": ("VUE", "Vuelto de más a un cliente")})
        datos = resumen_cierre(SesionCaja.objects.get())
        papel = bytes_cierre(datos).decode("cp850")
        for texto in ("CIERRE DE CAJA", "SINPE Móvil (1)", "Se esperaba", "NO CALZÓ", "Vuelto de más",
                      "Error al dar el vuelto", "Firma de quien cierra"):
            self.assertIn(texto, papel)
        for renglon in papel.split("\n"):
            limpio = "".join(c for c in renglon if c.isprintable())
            self.assertLessEqual(len(limpio), 48 + 8, renglon)   # 8 de margen por los comandos ESC/POS

    def test_reimprimir_el_ultimo_cierre(self):
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("10000"), tarjeta_contado=0, sinpe_contado=0)
        r = self.client.get(reverse("caja:abrir"))
        self.assertContains(r, "Imprimir el resumen de este cierre")
        r = self.client.post(reverse("caja:imprimir_cierre", args=[self.sesion.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TrabajoImpresion.objects.filter(tipo="cierre").count(), 1)

    def test_no_se_reimprime_una_caja_abierta(self):
        r = self.client.post(reverse("caja:imprimir_cierre", args=[self.sesion.pk]))
        self.assertEqual(r.status_code, 404)


class AQuienSeAvisa(Base):
    @override_settings(CIERRE_AVISO_DESTINATARIOS=[], REPORTE_DIARIO_DESTINATARIOS=[])
    def test_sin_configurar_le_llega_a_los_duenos(self):
        self.oscar.email = "oscar@allpetcr.com"
        self.oscar.save()
        with self.captureOnCommitCallbacks(execute=True):
            cerrar_caja(sesion=self.sesion, monto_contado=Decimal("1000"), tarjeta_contado=0, sinpe_contado=0,
                        justificaciones={"EFE": ("NSS", "No sabemos qué pasó")})
        self.assertEqual(mail.outbox[0].to, ["oscar@allpetcr.com"])

    @override_settings(CIERRE_AVISO_DESTINATARIOS=[], REPORTE_DIARIO_DESTINATARIOS=["socios@x.com"])
    def test_usa_los_del_resumen_diario(self):
        with self.captureOnCommitCallbacks(execute=True):
            cerrar_caja(sesion=self.sesion, monto_contado=Decimal("1000"), tarjeta_contado=0, sinpe_contado=0,
                        justificaciones={"EFE": ("NSS", "No sabemos qué pasó")})
        self.assertEqual(mail.outbox[0].to, ["socios@x.com"])

    @override_settings(CIERRE_AVISO_DESTINATARIOS=["a@x.com"],
                       EMAIL_BACKEND="caja.test_cierre_justificado.CorreoQueFalla")
    def test_si_el_correo_falla_la_caja_queda_cerrada_igual(self):
        with self.captureOnCommitCallbacks(execute=True):
            cerrar_caja(sesion=self.sesion, monto_contado=Decimal("1000"), tarjeta_contado=0, sinpe_contado=0,
                        justificaciones={"EFE": ("NSS", "No sabemos qué pasó")})
        s = SesionCaja.objects.get()
        self.assertEqual(s.estado, SesionCaja.Estado.CERRADA)
        self.assertIn("No salió el aviso", s.aviso_diferencia)


class CorreoQueFalla:
    def __init__(self, *a, **k):
        pass

    def send_messages(self, mensajes):
        raise OSError("el servidor de correo no responde")
