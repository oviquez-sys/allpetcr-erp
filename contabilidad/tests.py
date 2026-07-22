"""Pruebas del motor contable automático (S5).

El corazón de la especificación: toda operación genera su asiento, cuadrado,
sin intervención. Estas pruebas lo garantizan.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from caja.services import abrir_caja
from catalogo.models import Impuesto, Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.cxc import registrar_abono
from ventas.models import Cliente, DocumentoCxC
from ventas.services import anular_factura, registrar_venta

from .models import Asiento, LineaAsiento
from .services import cuenta


class BaseContable(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")  # RTS
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Cama", precio_venta=Decimal("10000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("20"), costo_unitario=Decimal("6000"), referencia="INI",
        )
        self.producto.refresh_from_db()
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))

    def vender(self, cantidad=1, medio="EFE", cliente=None):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago=medio, usuario=self.usuario, cliente=cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": cantidad}],
        )

    def saldo(self, logico):
        c = cuenta(self.empresa, logico)
        agg = LineaAsiento.objects.filter(cuenta=c)
        debe = sum((l.debe for l in agg), Decimal("0"))
        haber = sum((l.haber for l in agg), Decimal("0"))
        return debe, haber


class TodoAsientoCuadra(BaseContable):
    def test_cada_asiento_generado_cuadra(self):
        self.vender(2, "EFE")
        self.vender(1, "TAR")
        cli = Cliente.objects.create(empresa=self.empresa, nombre="X", limite_credito=Decimal("99999"))
        self.vender(1, "CRE", cliente=cli)
        self.assertTrue(Asiento.objects.exists())
        for a in Asiento.objects.all():
            self.assertTrue(a.cuadra, f"{a.numero} no cuadra")

    def test_balance_global_cuadra(self):
        self.vender(3, "EFE")
        debe = sum((l.debe for l in LineaAsiento.objects.all()), Decimal("0"))
        haber = sum((l.haber for l in LineaAsiento.objects.all()), Decimal("0"))
        self.assertEqual(debe, haber)

    def test_numeros_de_asiento_son_unicos_y_correlativos(self):
        """El consecutivo de asientos no repite números (defensa de concurrencia)
        y sigue una secuencia correlativa sin huecos."""
        for _ in range(5):
            self.vender(1, "EFE")
        numeros = list(Asiento.objects.order_by("id").values_list("numero", flat=True))
        self.assertEqual(len(numeros), len(set(numeros)), "hay números de asiento repetidos")
        # Correlativos AS-00000001, AS-00000002, ... sin saltos.
        secuencia = [int(n.split("-")[1]) for n in numeros]
        self.assertEqual(secuencia, list(range(secuencia[0], secuencia[0] + len(secuencia))))


class AsientosDeVenta(BaseContable):
    def test_venta_efectivo_rts_sin_iva(self):
        self.vender(2, "EFE")  # total 20000, RTS: subtotal=total, iva=0
        caja_d, _ = self.saldo("caja")
        _, ventas_h = self.saldo("ventas")
        _, iva_h = self.saldo("iva_por_pagar")
        self.assertEqual(caja_d, Decimal("20000"))
        self.assertEqual(ventas_h, Decimal("20000"))
        self.assertEqual(iva_h, Decimal("0"))

    def test_venta_genera_asiento_de_costo(self):
        self.vender(2, "EFE")  # costo 6000 x 2 = 12000
        costo_d, _ = self.saldo("costo_ventas")
        _, inv_h = self.saldo("inventario")
        self.assertEqual(costo_d, Decimal("12000"))
        self.assertEqual(inv_h, Decimal("12000"))

    def test_venta_tarjeta_va_a_bancos(self):
        self.vender(1, "TAR")
        bancos_d, _ = self.saldo("bancos")
        caja_d, _ = self.saldo("caja")
        self.assertEqual(bancos_d, Decimal("10000"))
        self.assertEqual(caja_d, Decimal("0"))

    def test_regimen_tradicional_desglosa_iva_en_asiento(self):
        iva = Impuesto.objects.create(nombre="IVA", tarifa=Decimal("13"))
        self.producto.impuesto = iva; self.producto.save()
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL; self.empresa.save()
        self.vender(1, "EFE")  # precio 10000 incluye IVA -> sub 8849.56, iva 1150.44
        _, ventas_h = self.saldo("ventas")
        _, iva_h = self.saldo("iva_por_pagar")
        self.assertEqual(ventas_h, Decimal("8849.56"))
        self.assertEqual(iva_h, Decimal("1150.44"))
        self.assertEqual(ventas_h + iva_h, Decimal("10000.00"))


class AsientosDeCredito(BaseContable):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(empresa=self.empresa, nombre="Vet", limite_credito=Decimal("99999"))

    def test_venta_credito_carga_cxc(self):
        self.vender(2, "CRE", cliente=self.cliente)  # 20000
        cxc_d, _ = self.saldo("cxc")
        self.assertEqual(cxc_d, Decimal("20000"))

    def test_abono_efectivo_debita_caja_acredita_cxc(self):
        f = self.vender(2, "CRE", cliente=self.cliente)
        doc = DocumentoCxC.objects.get(factura=f)
        registrar_abono(documento=doc, monto=Decimal("8000"), medio="EFE", usuario=self.usuario)
        caja_d, _ = self.saldo("caja")
        _, cxc_h = self.saldo("cxc")
        self.assertEqual(caja_d, Decimal("8000"))
        self.assertEqual(cxc_h, Decimal("8000"))

    def test_cxc_neto_tras_abono(self):
        f = self.vender(2, "CRE", cliente=self.cliente)  # cxc debe 20000
        doc = DocumentoCxC.objects.get(factura=f)
        registrar_abono(documento=doc, monto=Decimal("5000"), medio="SIN", usuario=self.usuario)
        cxc_d, cxc_h = self.saldo("cxc")
        self.assertEqual(cxc_d - cxc_h, Decimal("15000"))  # saldo contable pendiente


class AsientosDeAnulacion(BaseContable):
    def test_anulacion_deja_todo_en_cero(self):
        f = self.vender(2, "EFE")
        anular_factura(factura=f, motivo="devolución", usuario=self.usuario)
        # Venta + anulación se compensan en cada cuenta.
        for logico in ("caja", "ventas", "costo_ventas", "inventario"):
            debe, haber = self.saldo(logico)
            self.assertEqual(debe, haber, f"{logico} no quedó neto en cero")

    def test_anulacion_genera_asientos_de_reversa(self):
        f = self.vender(2, "EFE")
        n_antes = Asiento.objects.count()
        anular_factura(factura=f, motivo="x", usuario=self.usuario)
        self.assertTrue(Asiento.objects.filter(origen="ANU").exists())
        self.assertGreater(Asiento.objects.count(), n_antes)


class CierreDePeriodo(BaseContable):
    """Sprint C: cerrar un período blinda lo declarado. Todo asiento pasa por
    registrar_asiento, así que el guard cubre ventas, compras, costos, etc."""

    def _asiento(self, fecha):
        """Asiento mínimo y cuadrado en la fecha dada."""
        from datetime import date
        from decimal import Decimal
        from .services import registrar_asiento, cuenta
        if isinstance(fecha, str):
            y, m, d = map(int, fecha.split("-"))
            fecha = date(y, m, d)
        return registrar_asiento(
            empresa=self.empresa, fecha=fecha, descripcion="prueba", origen="MAN",
            lineas=[
                {"cuenta": cuenta(self.empresa, "caja"), "debe": Decimal("100")},
                {"cuenta": cuenta(self.empresa, "ventas"), "haber": Decimal("100")},
            ],
            usuario=self.usuario,
        )

    def test_sin_cierre_todo_pasa(self):
        from .services import fecha_bloqueo
        self.assertIsNone(fecha_bloqueo(self.empresa))
        self._asiento("2026-01-15")  # no revienta

    def test_cerrar_bloquea_fecha_igual_o_anterior(self):
        from datetime import date
        from .services import cerrar_periodo
        cerrar_periodo(empresa=self.empresa, fecha_cierre=date(2026, 6, 30), usuario=self.usuario, nota="I trim")
        with self.assertRaises(ValidationError):
            self._asiento("2026-06-30")  # misma fecha: bloqueada
        with self.assertRaises(ValidationError):
            self._asiento("2026-05-01")  # anterior: bloqueada

    def test_cerrar_permite_fecha_posterior(self):
        from datetime import date
        from .services import cerrar_periodo
        cerrar_periodo(empresa=self.empresa, fecha_cierre=date(2026, 6, 30), usuario=self.usuario)
        a = self._asiento("2026-07-01")  # posterior: pasa
        self.assertIsNotNone(a.pk)

    def test_reabrir_desbloquea(self):
        from datetime import date
        from .services import cerrar_periodo, reabrir_periodo
        c = cerrar_periodo(empresa=self.empresa, fecha_cierre=date(2026, 6, 30), usuario=self.usuario)
        with self.assertRaises(ValidationError):
            self._asiento("2026-06-15")
        reabrir_periodo(cierre=c, usuario=self.usuario, motivo="corregir factura mal digitada")
        a = self._asiento("2026-06-15")  # ahora sí
        self.assertIsNotNone(a.pk)

    def test_reabrir_sin_motivo_falla(self):
        from datetime import date
        from .services import cerrar_periodo, reabrir_periodo
        c = cerrar_periodo(empresa=self.empresa, fecha_cierre=date(2026, 6, 30), usuario=self.usuario)
        with self.assertRaises(ValidationError):
            reabrir_periodo(cierre=c, usuario=self.usuario, motivo="   ")

    def test_reapertura_queda_auditada(self):
        from datetime import date
        from .services import cerrar_periodo, reabrir_periodo
        c = cerrar_periodo(empresa=self.empresa, fecha_cierre=date(2026, 6, 30), usuario=self.usuario)
        reabrir_periodo(cierre=c, usuario=self.usuario, motivo="error real")
        c.refresh_from_db()
        self.assertFalse(c.activo)
        self.assertEqual(c.reabierto_por, self.usuario)
        self.assertEqual(c.motivo_reapertura, "error real")
        self.assertIsNotNone(c.reabierto_en)

    def test_no_se_puede_cerrar_hacia_atras(self):
        from datetime import date
        from .services import cerrar_periodo
        cerrar_periodo(empresa=self.empresa, fecha_cierre=date(2026, 6, 30), usuario=self.usuario)
        with self.assertRaises(ValidationError):
            cerrar_periodo(empresa=self.empresa, fecha_cierre=date(2026, 5, 31), usuario=self.usuario)

    def test_anular_hoy_funciona_con_periodo_anterior_cerrado(self):
        """Una venta vieja se puede anular hoy aunque su período esté cerrado:
        la reversa se registra con fecha de hoy (período abierto)."""
        from datetime import date, timedelta
        from .services import cerrar_periodo
        f = self.vender(2, "EFE")  # venta con fecha de hoy
        ayer = date.today() - timedelta(days=1)
        cerrar_periodo(empresa=self.empresa, fecha_cierre=ayer, usuario=self.usuario)
        # anular hoy: la reversa va con fecha de hoy, posterior al cierre -> pasa
        anular_factura(factura=f, motivo="cliente devolvió", usuario=self.usuario)
        self.assertTrue(Asiento.objects.filter(origen="ANU").exists())
