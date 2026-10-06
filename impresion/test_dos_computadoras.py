"""Dos computadoras en la tienda, en horarios distintos (06/10/2026).

Pedido de Oscar: las impresoras se pasan de una computadora a la otra según
el turno. Las dos tienen las colas instaladas, y Windows las sigue listando
aunque el cable esté en la otra. Antes, la computadora sin cable se llevaba el
trabajo y avisaba un error; la que tenía la impresora no recibía nada.

Lo que fijan estas pruebas:
- el agente solo anuncia las impresoras CONECTADAS (no las instaladas);
- si igual le toca un trabajo y la impresora no está, lo devuelve a la cola
  sin mostrar error, y la otra computadora lo imprime.
"""
import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

import _agente_impresion as motor
from impresion import cola, windows
from impresion.models import TrabajoImpresion


def _trabajo(impresora="Caysn 80mm"):
    return cola.encolar_crudo(impresora, b"FE-0001", "Venta FE-0001", TrabajoImpresion.TIQUETE)


class SoloLasConectadas(TestCase):
    def _con(self, instaladas, desconectadas):
        return (mock.patch.object(windows, "listar_impresoras", return_value=instaladas),
                mock.patch.object(windows, "sin_conexion", side_effect=lambda n: n in desconectadas))

    def test_la_cola_sin_cable_no_se_anuncia(self):
        a, b = self._con(["Caysn 80mm", "Xprinter XP-360B", "Microsoft Print to PDF"],
                         {"Caysn 80mm", "Xprinter XP-360B"})
        with a, b:
            self.assertEqual(windows.impresoras_conectadas(), ["Microsoft Print to PDF"])

    def test_la_conectada_si(self):
        a, b = self._con(["Caysn 80mm", "Xprinter XP-360B"], set())
        with a, b:
            self.assertEqual(windows.impresoras_conectadas(), ["Caysn 80mm", "Xprinter XP-360B"])

    def test_la_copia_viva_cuenta_como_la_original(self):
        # Windows deja la original muerta y crea «(Copiar 1)» en el puerto nuevo.
        a, b = self._con(["Xprinter XP-360B", "Xprinter XP-360B (Copiar 1)"], {"Xprinter XP-360B"})
        with a, b:
            self.assertIn("Xprinter XP-360B", windows.impresoras_conectadas())

    def test_el_agente_manda_las_conectadas(self):
        with mock.patch.object(windows, "impresoras_conectadas", return_value=["Caysn 80mm"]):
            self.assertEqual(motor.impresoras_de_esta_maquina(), ["Caysn 80mm"])


class DevolverALaCola(TestCase):
    def test_devuelto_lo_toma_la_otra_computadora(self):
        _trabajo()
        tomado = cola.tomar_pendientes(impresoras=["Caysn 80mm"])[0]
        cola.reportar(tomado.pk, ok=False, detalle="sin conexión", devolver=True)
        tomado.refresh_from_db()
        self.assertEqual(tomado.estado, TrabajoImpresion.PENDIENTE)
        self.assertIsNone(tomado.tomado_en)
        self.assertEqual(len(cola.tomar_pendientes(impresoras=["Caysn 80mm"])), 1)

    def test_un_trabajo_vencido_no_revive(self):
        t = _trabajo()
        TrabajoImpresion.objects.filter(pk=t.pk).update(
            estado=TrabajoImpresion.VENCIDO, terminado_en=timezone.now())
        cola.reportar(t.pk, ok=False, detalle="x", devolver=True)
        t.refresh_from_db()
        self.assertEqual(t.estado, TrabajoImpresion.VENCIDO)

    def test_un_error_de_verdad_sigue_siendo_error(self):
        _trabajo()
        tomado = cola.tomar_pendientes()[0]
        cola.reportar(tomado.pk, ok=False, detalle="Sin papel")
        tomado.refresh_from_db()
        self.assertEqual(tomado.estado, TrabajoImpresion.ERROR)

    @override_settings(IMPRESION_AGENTE_TOKEN="llave-de-prueba")
    def test_la_puerta_del_agente_acepta_devolver(self):
        _trabajo()
        tomado = cola.tomar_pendientes()[0]
        r = self.client.post(
            reverse("impresion:agente_resultado"),
            data=json.dumps({"id": tomado.pk, "ok": False, "detalle": "x", "devolver": True}),
            content_type="application/json", headers={"x-agente-token": "llave-de-prueba"},
        )
        self.assertEqual(r.status_code, 200)
        tomado.refresh_from_db()
        self.assertEqual(tomado.estado, TrabajoImpresion.PENDIENTE)


class ElAgenteNoMuestraError(TestCase):
    def test_impresora_no_disponible_se_devuelve_sin_aviso(self):
        trabajo = {"id": 7, "titulo": "Venta FE-0001", "tipo": "TIQ", "formato": "crudo",
                   "impresora": "Caysn 80mm", "contenido_b64": "RkUtMDAwMQ=="}
        avisos, enviados = [], []

        def pedir(ruta, datos=None, metodo="GET"):
            if ruta.startswith("/impresion/agente/pendientes/"):
                return {"trabajos": [trabajo]}
            enviados.append(datos)
            return {"ok": True}

        with mock.patch.object(motor, "_pedir", side_effect=pedir), \
                mock.patch.object(motor, "impresoras_de_esta_maquina", return_value=["Caysn 80mm"]), \
                mock.patch.object(windows, "enviar_crudo",
                                  side_effect=windows.ImpresoraNoDisponible("sin conexión")), \
                mock.patch.object(motor, "anotar"):
            motor.una_vuelta(al_imprimir=lambda *a: avisos.append(a))

        self.assertEqual(avisos, [], "La computadora sin cable no debe mostrar error")
        self.assertEqual(enviados[0]["devolver"], True)
        self.assertEqual(enviados[0]["ok"], False)

    def test_otro_error_si_se_avisa(self):
        trabajo = {"id": 8, "titulo": "Venta", "tipo": "TIQ", "formato": "crudo",
                   "impresora": "Caysn 80mm", "contenido_b64": "RkU="}
        avisos = []
        with mock.patch.object(motor, "_pedir",
                               side_effect=lambda r, d=None, metodo="GET": {"trabajos": [trabajo]}
                               if r.startswith("/impresion/agente/pendientes/") else {"ok": True}), \
                mock.patch.object(motor, "impresoras_de_esta_maquina", return_value=["Caysn 80mm"]), \
                mock.patch.object(windows, "enviar_crudo",
                                  side_effect=windows.ErrorDeImpresion("Sin papel")), \
                mock.patch.object(motor, "anotar"):
            motor.una_vuelta(al_imprimir=lambda *a: avisos.append(a))
        self.assertEqual(len(avisos), 1)
