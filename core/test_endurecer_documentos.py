"""Pruebas de FRA-001: REVOKE UPDATE/DELETE (kardex, libro contable) y
REVOKE DELETE (documentos) sobre las 10 tablas de endurecer_documentos.

Mismo enfoque que test_endurecer_auditlog.py: corre contra la base de
pruebas real de PostgreSQL, sin limpieza manual — TestCase revierte la
transacción de cada prueba, y GRANT/REVOKE es transaccional en Postgres.
"""
from django.core.management import call_command
from django.db import connection
from django.test import TestCase


class EndurecerDocumentosTest(TestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("FRA-001 (REVOKE de permisos) es solo para PostgreSQL.")

    def _permisos(self, tabla):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = %s AND grantee = current_user",
                [tabla],
            )
            return {f[0] for f in cur.fetchall()}

    def test_sin_confirmar_no_cambia_nada(self):
        call_command("endurecer_documentos", verbosity=0)
        self.assertIn("UPDATE", self._permisos("ventas_facturaventa"))
        self.assertIn("DELETE", self._permisos("inventario_movimientoinventario"))

    def test_grupo_append_only_pierde_update_y_delete(self):
        call_command("endurecer_documentos", confirmar=True, verbosity=0)
        for tabla in (
            "inventario_movimientoinventario", "caja_movimientocaja",
            "contabilidad_lineaasiento", "ventas_abono",
        ):
            permisos = self._permisos(tabla)
            self.assertNotIn("UPDATE", permisos, tabla)
            self.assertNotIn("DELETE", permisos, tabla)
            self.assertIn("SELECT", permisos, tabla)
            self.assertIn("INSERT", permisos, tabla)

    def test_grupo_documentos_pierde_solo_delete_conserva_update(self):
        call_command("endurecer_documentos", confirmar=True, verbosity=0)
        for tabla in (
            "ventas_facturaventa", "ventas_devolucionventa",
            "ventas_documentocxc", "compras_compra", "caja_sesioncaja",
            "contabilidad_asiento",
        ):
            permisos = self._permisos(tabla)
            self.assertNotIn("DELETE", permisos, tabla)
            self.assertIn(
                "UPDATE", permisos,
                f"{tabla}: el grupo documentos debe CONSERVAR UPDATE — anular_factura/"
                "recibir_compra/cerrar_caja/el FK de LineaAsiento.asiento lo necesitan.",
            )
            self.assertIn("SELECT", permisos, tabla)
            self.assertIn("INSERT", permisos, tabla)

    def test_anular_factura_sigue_funcionando_tras_el_revoke(self):
        # La preocupación concreta que motivó esta verificación: REVOKE
        # DELETE no debe romper anular_factura, que actualiza (no borra)
        # ventas_facturaventa. Prueba de punta a punta, no solo el grant.
        from decimal import Decimal

        from django.contrib.auth.models import User

        from caja.services import abrir_caja
        from catalogo.models import Producto
        from core.models import Empresa, Sucursal
        from inventario.models import Bodega
        from inventario.services import registrar_movimiento
        from ventas.services import anular_factura, registrar_venta

        call_command("endurecer_documentos", confirmar=True, verbosity=0)

        empresa = Empresa.objects.create(nombre="Prueba REVOKE", identificacion="3-102-999999")
        sucursal = Sucursal.objects.create(empresa=empresa, nombre="Central")
        bodega = Bodega.objects.create(sucursal=sucursal, nombre="Principal")
        usuario = User.objects.create_user("temp", password="x")
        producto = Producto.objects.create(
            empresa=empresa, sku="T-1", nombre="Prueba", precio_venta=Decimal("1000")
        )
        registrar_movimiento(
            producto=producto, bodega=bodega, tipo="INI",
            cantidad=Decimal("5"), costo_unitario=Decimal("500"), referencia="INI",
        )
        sesion = abrir_caja(sucursal=sucursal, usuario=usuario, monto_apertura=Decimal("0"))
        factura = registrar_venta(
            sesion_caja=sesion, medio_pago="EFE", usuario=usuario,
            lineas=[{"producto_id": producto.pk, "cantidad": 1}],
        )

        anular_factura(factura=factura, motivo="prueba", usuario=usuario)  # no debe lanzar excepción

        factura.refresh_from_db()
        self.assertEqual(factura.estado, factura.Estado.ANULADA)

    def test_sqlite_no_hace_nada(self):
        from django.test import override_settings

        with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}):
            call_command("endurecer_documentos", confirmar=True, verbosity=0)  # no debe lanzar excepción
