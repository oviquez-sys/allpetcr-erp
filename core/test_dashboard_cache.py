"""La caché del dashboard no debe mentir ni ocultar alertas.

Auditoría 2026-07-28, hallazgo PERF-03. Cachear indicadores es fácil; lo que
hay que demostrar es que la caché no introduce dos errores clásicos:

  1. Que muestre cifras viejas cuando el llamador pidió cifras frescas.
  2. Que congele una ALERTA. Un aviso de "el inventario no cuadra" cacheado
     dos minutos es un aviso que llega tarde, y las alertas son justamente lo
     que no puede llegar tarde.
"""
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings

from core.dashboard import indicadores
from core.models import ChequeoIntegridad, Empresa

# La suite corre con DummyCache para que ninguna prueba contamine a la
# siguiente (ver config/settings.py). Estas pruebas, que son justamente sobre
# la caché, activan LocMemCache a propósito y la limpian en cada método.
CACHE_REAL = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pruebas-dashboard",
    }
}


@override_settings(CACHES=CACHE_REAL)
class CacheDelDashboardTest(TestCase):
    def setUp(self):
        cache.clear()
        self.empresa = Empresa.objects.create(nombre="AllPetCR", identificacion="3-102-000000")

    def tearDown(self):
        cache.clear()

    def test_la_segunda_carga_usa_la_cache(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        indicadores(self.empresa)  # calienta
        with CaptureQueriesContext(connection) as ctx:
            indicadores(self.empresa)
        # Solo debería quedar la consulta del estado de integridad, que a
        # propósito no se cachea.
        self.assertLessEqual(
            len(ctx.captured_queries), 3,
            "La segunda carga recalculó los indicadores: la caché no está actuando.",
        )

    def test_se_puede_pedir_el_calculo_sin_cache(self):
        r = indicadores(self.empresa, usar_cache=False)
        self.assertIn("ventas_hoy", r)

    def test_la_alerta_de_integridad_no_se_cachea(self):
        """El caso que importa: la alerta aparece aunque los indicadores estén
        cacheados de antes."""
        ChequeoIntegridad.objects.create(revisados=10, descuadres=0)
        primera = indicadores(self.empresa)
        self.assertEqual(primera["integridad_descuadres"], 0)

        # Aparece un descuadre DESPUÉS de que los indicadores quedaran en caché.
        ChequeoIntegridad.objects.create(revisados=10, descuadres=3)
        segunda = indicadores(self.empresa)
        self.assertEqual(
            segunda["integridad_descuadres"], 3,
            "La alerta quedó congelada en la caché: el gerente no se enteraría "
            "del descuadre hasta que expire, y las alertas no pueden esperar.",
        )

    def test_sin_chequeos_avisa_que_esta_vencido(self):
        r = indicadores(self.empresa)
        self.assertTrue(r["integridad_vencida"])
        self.assertIsNone(r["integridad_ultimo"])

    def test_un_chequeo_reciente_y_limpio_no_genera_alerta(self):
        ChequeoIntegridad.objects.create(revisados=50, descuadres=0)
        r = indicadores(self.empresa)
        self.assertFalse(r["integridad_vencida"])
        self.assertEqual(r["integridad_descuadres"], 0)

    def test_cada_empresa_tiene_su_propia_entrada_de_cache(self):
        """Si compartieran clave, una empresa vería las ventas de la otra."""
        otra = Empresa.objects.create(nombre="Otra", identificacion="3-102-111111")
        indicadores(self.empresa)
        r = indicadores(otra)
        self.assertEqual(r["ventas_hoy"], Decimal("0"))
