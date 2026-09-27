"""El agente de impresión como programa de Windows (27/09/2026).

No prueban Windows de verdad (registro, tareas, bandeja): prueban las
decisiones que, si se rompen, dejan a la tienda sin papel sin que nadie note.
"""
import ssl
import sys
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

sys.path.insert(0, str(Path(settings.BASE_DIR)))
import _agente_escritorio as escritorio  # noqa: E402
import _agente_impresion as motor  # noqa: E402


class CicloDelAgente(SimpleTestCase):
    def correr(self, vueltas):
        """Corre `atender` con una lista de resultados de una_vuelta
        (None = bien, Exception = falla) y devuelve el estado final."""
        pendientes = list(vueltas)
        estado = motor.Estado()
        cambios = []

        def vuelta(estado_, al_imprimir):
            r = pendientes.pop(0)
            if isinstance(r, Exception):
                raise r

        with mock.patch.object(motor, "una_vuelta", vuelta), mock.patch.object(motor, "anotar"):
            motor.atender(lambda s: not pendientes, estado, al_cambiar=lambda: cambios.append(estado.resumen()))
        return estado, cambios

    def test_se_detiene_cuando_se_lo_piden(self):
        estado, _ = self.correr([None, None])
        self.assertTrue(estado.conectado)

    def test_una_falla_de_red_no_lo_tumba_y_se_recupera(self):
        estado, cambios = self.correr([OSError("sin internet"), None])
        self.assertTrue(estado.conectado)
        self.assertEqual(cambios[0], "Sin conexión con el ERP (reintentando)")

    def test_avisa_solo_cuando_cambia_algo(self):
        # El icono se redibuja al cambiar, no cada 3 segundos.
        _, cambios = self.correr([None, None, None])
        self.assertEqual(len(cambios), 1)

    def test_cuenta_los_impresos_del_dia(self):
        estado = motor.Estado(conectado=True, impresoras=["Caysn 80mm"])
        estado.contar(True)
        estado.contar(False)
        self.assertEqual(estado.resumen(), "Conectado · 1 impresos hoy")


class ConexionSegura(SimpleTestCase):
    def test_sigue_verificando_el_certificado(self):
        # Se afloja SOLO la exigencia que rompe con Avast; lo demás no.
        contexto = motor._contexto_tls()
        self.assertEqual(contexto.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(contexto.check_hostname)
        self.assertFalse(contexto.verify_flags & getattr(ssl, "VERIFY_X509_STRICT", 0))


class TareaDeRespaldo(SimpleTestCase):
    def test_no_se_frena_con_bateria_ni_a_las_72_horas(self):
        xml = escritorio.xml_tarea(Path(r"C:\x\AllPetCR-Impresion.exe"))
        self.assertIn("<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>", xml)
        self.assertIn("<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>", xml)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", xml)
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", xml)
        self.assertIn('"C:\\x\\AllPetCR-Impresion.exe"', xml)
