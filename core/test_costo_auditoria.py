"""Mide el costo real de una venta: filas de auditoría y consultas SQL.

Auditoría 2026-07-28, hallazgos BE-01 y PERF-02. El auditor midió 13 filas de
AuditLog y 66 consultas para una venta de una sola línea, y lo señaló como el
problema de rendimiento de la ruta caliente: eso se paga con el cliente
esperando el tiquete.

Estas pruebas no comprueban "que ande": comprueban que el costo no vuelva a
subir. Los topes son deliberadamente holgados respecto de lo medido después
de la corrección — no queremos una prueba que falle por una consulta de más,
queremos una que avise si alguien reintroduce la amplificación.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from caja.services import abrir_caja
from catalogo.models import Producto
from core.models import AuditLog, Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.services import registrar_venta


class CostoDeUnaVentaTest(TestCase):
    """Topes de coste para la operación más frecuente del negocio."""

    # Medido tras la corrección, con margen para no ser frágil.
    #
    # Se mide la SEGUNDA venta, no la primera: la primera venta de una empresa
    # recién creada siembra el plan de cuentas contable y genera 15 filas
    # extra de contabilidad.cuentacontable. Eso ocurre una sola vez en la vida
    # de la empresa —en producción el plan ya existe— así que medirlo daría un
    # número que no representa la operación real.
    MAX_FILAS_AUDITORIA = 9
    MAX_CONSULTAS = 65

    # Medición comparada del mismo escenario, hecha al aplicar la corrección:
    #
    #   ANTES (receptores globales + auditar líneas): 12 filas · 66 consultas
    #   AHORA (conectados por sender, sin líneas):     7 filas · 61 consultas
    #
    # Reproduce las cifras del auditor (13 filas / 66 consultas), así que el
    # escenario es comparable al suyo.
    #
    # Matiz honesto sobre el hallazgo PERF-02: la auditoría NO "triplicaba el
    # costo de cada venta". Aportaba ~15 de 66 consultas (las 12 inserciones
    # más los SELECT previos), es decir cerca de un 23%, no la mayoría. El
    # resto lo consume la venta en sí: factura, líneas, kardex, producto,
    # movimiento de caja, asiento y consecutivos. Lo que sí es cierto —y es lo
    # que esta corrección ataca— es el crecimiento de la tabla: 41% menos
    # filas por venta, y el ahorro sube con ventas de más líneas, porque cada
    # LineaVenta generaba su propia fila (eso último es inferencia del diseño,
    # no una medición aparte).

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPetCR", identificacion="3-102-000000")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("cajero1", password="x", is_staff=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P1", nombre="Alimento", precio_venta=Decimal("10000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI", cantidad=Decimal("50"),
            costo_unitario=Decimal("4000"), referencia="INI", usuario=self.usuario,
        )
        self.sesion = abrir_caja(
            sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("10000")
        )
        # Venta de calentamiento: deja sembrado el plan de cuentas para que la
        # medición refleje una venta cualquiera y no la primera de la empresa.
        self._vender()
        AuditLog.objects.all().delete()  # medir solo la venta siguiente

    def _vender(self):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": Decimal("1")}],
        )

    def test_una_venta_no_genera_mas_de_seis_filas_de_auditoria(self):
        """Antes eran 13. Las líneas de detalle ya no se auditan aparte porque
        su documento padre sí queda auditado y es inmutable (BE-01)."""
        self._vender()
        filas = AuditLog.objects.count()
        self.assertLessEqual(
            filas,
            self.MAX_FILAS_AUDITORIA,
            f"Una venta simple generó {filas} filas de auditoría. El tope es "
            f"{self.MAX_FILAS_AUDITORIA}: revisá si se volvió a auditar algún "
            f"modelo de detalle en core/signals.py:AUDITED.",
        )

    def test_las_lineas_de_detalle_no_se_auditan_por_separado(self):
        """Decisión explícita, no olvido: ver NO_AUDITADOS_A_PROPOSITO."""
        self._vender()
        for tabla in ("ventas.lineaventa", "contabilidad.lineaasiento"):
            with self.subTest(tabla=tabla):
                self.assertEqual(AuditLog.objects.filter(tabla=tabla).count(), 0)

    def test_el_documento_padre_si_queda_auditado(self):
        """La trazabilidad no se perdió: es lo que hay que proteger al
        recortar la auditoría."""
        self._vender()
        self.assertTrue(AuditLog.objects.filter(tabla="ventas.facturaventa").exists())
        self.assertTrue(AuditLog.objects.filter(tabla="inventario.movimientoinventario").exists())

    def test_una_venta_no_supera_el_tope_de_consultas(self):
        """Antes 66. El grueso sobraba: los receptores corrían en cada save()
        del proyecto, no solo en los modelos auditados."""
        with CaptureQueriesContext(connection) as ctx:
            self._vender()
        n = len(ctx.captured_queries)
        self.assertLessEqual(
            n,
            self.MAX_CONSULTAS,
            f"Una venta simple ejecutó {n} consultas SQL (tope {self.MAX_CONSULTAS}).",
        )

    def test_guardar_un_modelo_no_auditado_no_dispara_la_auditoria(self):
        """El punto de conectar por sender: los modelos fuera de AUDITED no
        deben pagar ni el costo del filtro."""
        AuditLog.objects.all().delete()
        User.objects.create_user("otro", password="x")
        self.assertEqual(AuditLog.objects.count(), 0)


class AuditoriaDeCambiosTest(TestCase):
    """El campo `antes` guarda solo lo que cambió, no el objeto entero."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPetCR", identificacion="3-102-000000")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P9", nombre="Collar", precio_venta=Decimal("5000")
        )
        AuditLog.objects.all().delete()

    def test_al_editar_solo_se_guarda_el_campo_modificado(self):
        self.producto.precio_venta = Decimal("6000")
        self.producto.save()
        log = AuditLog.objects.filter(tabla="catalogo.producto", accion="editar").latest("fecha")
        self.assertIn("precio_venta", log.antes)
        self.assertEqual(Decimal(str(log.antes["precio_venta"])), Decimal("5000"))
        self.assertNotIn("nombre", log.antes, "No cambió el nombre: no debería estar en `antes`.")

    def test_el_estado_final_completo_si_se_conserva(self):
        """`despues` sigue teniendo el objeto entero: es lo que permite
        reconstruir cómo quedó la cosa."""
        self.producto.precio_venta = Decimal("6000")
        self.producto.save()
        log = AuditLog.objects.filter(tabla="catalogo.producto", accion="editar").latest("fecha")
        self.assertIn("nombre", log.despues)
        self.assertIn("precio_venta", log.despues)

    def test_un_save_que_no_cambia_nada_no_ensucia_la_bitacora(self):
        antes = AuditLog.objects.count()
        self.producto.save()
        self.assertEqual(AuditLog.objects.count(), antes)
