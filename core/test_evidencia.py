"""Pruebas de las pantallas de evidencia de los indicadores.

La regla que fijan estas pruebas es una sola, y es la que hace que la función
sirva para algo: **la suma de la evidencia tiene que dar el número del
indicador**. Si un día no da, la pantalla deja de ser evidencia y pasa a ser
una segunda opinión, que es peor que no tener nada — porque ahora hay dos
cifras y ninguna manera de saber cuál creer.

Se prueba por caminos distintos a propósito: el indicador se calcula con la
lógica del tablero y la evidencia con la suya, y se exige que coincidan. Una
prueba que llamara dos veces a la misma función no probaría nada.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from caja.models import MovimientoCaja, SesionCaja
from caja.services import abrir_caja, monto_esperado, registrar_movimiento_caja
from catalogo.models import Categoria, Producto
from core import evidencia
from core.dashboard import indicadores
from core.models import Empresa, Sucursal
from core.roles import GERENTE
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import Cliente, DocumentoCxC, FacturaVenta
from ventas.services import registrar_venta


class BaseEvidencia(TestCase):
    """Escenario común: una empresa con caja abierta, ventas por varios
    medios de pago y un cliente con crédito."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Bodega")
        self.usuario = User.objects.create_user(
            "gerente_test", password="x", is_staff=True, is_superuser=True
        )
        self.categoria = Categoria.objects.create(nombre="Test")

        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="EV-1", nombre="Alimento",
            categoria=self.categoria, precio_venta=Decimal("10000"),
            costo_promedio=Decimal("6000"), stock_minimo=Decimal("2"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="ENT",
            cantidad=Decimal("100"), costo_unitario=Decimal("6000"),
            referencia="carga", usuario=self.usuario,
        )

        self.sesion = abrir_caja(
            sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("25000")
        )

        self.cliente = Cliente.objects.create(
            empresa=self.empresa, nombre="Cliente Crédito",
            limite_credito=Decimal("500000"),
        )

    def _vender(self, medio, cantidad=1, cliente=None):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago=medio, usuario=self.usuario,
            cliente=cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": cantidad}],
        )


class EfectivoEnCajaCuadra(BaseEvidencia):

    def test_la_suma_de_los_movimientos_da_el_indicador(self):
        """El total de la evidencia == monto_esperado() == KPI del Inicio."""
        self._vender(FacturaVenta.MedioPago.EFECTIVO, cantidad=2)
        self._vender(FacturaVenta.MedioPago.SINPE, cantidad=1)
        registrar_movimiento_caja(
            sesion=self.sesion, tipo=MovimientoCaja.Tipo.EGRESO,
            monto=Decimal("-5000"), descripcion="compra de bolsas",
            usuario=self.usuario,
        )

        detalle = evidencia.efectivo_en_caja(self.empresa)
        suma_filas = sum((m.monto for m in detalle["filas"]), Decimal("0"))
        kpi = indicadores(self.empresa, usar_cache=False)["saldo_caja"]

        self.assertEqual(suma_filas, detalle["total"],
                         "la tabla de evidencia no suma el total que muestra")
        self.assertEqual(detalle["total"], kpi,
                         "la evidencia no coincide con el KPI del Inicio")
        self.assertEqual(kpi, monto_esperado(self.sesion))

    def test_la_formula_suma_el_mismo_total(self):
        """Los sumandos de 'cómo se calcula' tienen que dar el total."""
        self._vender(FacturaVenta.MedioPago.EFECTIVO, cantidad=3)
        registrar_movimiento_caja(
            sesion=self.sesion, tipo=MovimientoCaja.Tipo.INGRESO,
            monto=Decimal("2000"), descripcion="abono", usuario=self.usuario,
        )
        detalle = evidencia.efectivo_en_caja(self.empresa)
        # Los montos ya vienen con su signo desde la base (negativo sale), así
        # que la fórmula se suma tal cual, sin aplicar el signo mostrado.
        suma_formula = sum((f["monto"] for f in detalle["formula"]), Decimal("0"))
        self.assertEqual(suma_formula, detalle["total"])

    def test_sinpe_y_tarjeta_no_entran_a_la_caja(self):
        """La razón de ser de la pantalla: explicar por qué venta ≠ efectivo."""
        self._vender(FacturaVenta.MedioPago.EFECTIVO, cantidad=1)
        self._vender(FacturaVenta.MedioPago.SINPE, cantidad=5)

        detalle = evidencia.efectivo_en_caja(self.empresa)
        kpis = indicadores(self.empresa, usar_cache=False)

        # Se vendió mucho más de lo que hay en la gaveta, y la diferencia es
        # exactamente lo cobrado por SINPE.
        self.assertGreater(kpis["ventas_hoy"], detalle["total"])
        self.assertEqual(
            kpis["ventas_hoy"] - Decimal("50000"),  # 5 × 10000 por SINPE
            detalle["total"] - self.sesion.monto_apertura + Decimal("0"),
        )
        self.assertTrue(detalle["excluye"], "no se explicó qué queda fuera")

    def test_sin_caja_abierta_no_revienta(self):
        """Fuera del horario de la tienda no hay sesión abierta, y la pantalla
        tiene que decirlo en vez de fallar.

        La sesión se CIERRA en vez de borrarse: los movimientos de caja la
        protegen con on_delete=PROTECT, que es justamente la garantía de que
        el historial de efectivo no se puede hacer desaparecer.
        """
        from caja.services import cerrar_caja

        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("25000"),
                    usuario=self.usuario)

        detalle = evidencia.efectivo_en_caja(self.empresa)
        self.assertIsNone(detalle["sesion"])
        self.assertEqual(detalle["total"], Decimal("0"))


class VentasPorMedioCuadra(BaseEvidencia):

    def test_los_medios_suman_las_ventas_del_dia(self):
        self._vender(FacturaVenta.MedioPago.EFECTIVO, cantidad=1)
        self._vender(FacturaVenta.MedioPago.TARJETA, cantidad=2)
        self._vender(FacturaVenta.MedioPago.SINPE, cantidad=1)

        detalle = evidencia.ventas_por_medio(self.empresa)
        suma_medios = sum((f["monto"] for f in detalle["formula"]), Decimal("0"))
        suma_filas = sum((f.total for f in detalle["filas"]), Decimal("0"))
        kpi = indicadores(self.empresa, usar_cache=False)["ventas_hoy"]

        self.assertEqual(suma_medios, detalle["total_ventas"])
        self.assertEqual(suma_filas, detalle["total_ventas"])
        self.assertEqual(detalle["total_ventas"], kpi)

    def test_el_credito_es_venta_pero_no_es_dinero_recibido(self):
        """La distinción que motivó separar los dos números.

        Una venta a crédito sube las ventas del día y NO sube lo recibido.
        Confundirlos era leer como ingreso algo que todavía no entró.
        """
        self._vender(FacturaVenta.MedioPago.EFECTIVO, cantidad=1)   # ₡10.000
        self._vender(FacturaVenta.MedioPago.CREDITO, cantidad=3, cliente=self.cliente)  # ₡30.000

        detalle = evidencia.ventas_por_medio(self.empresa)
        self.assertEqual(detalle["total_ventas"], Decimal("40000"))
        self.assertEqual(detalle["recibido"], Decimal("10000"),
                         "el crédito no debería contar como dinero recibido")

    def test_un_abono_de_hoy_sube_lo_recibido_pero_no_las_ventas(self):
        """El otro lado de la misma distinción."""
        from ventas.cxc import registrar_abono

        self._vender(FacturaVenta.MedioPago.CREDITO, cantidad=2, cliente=self.cliente)
        doc = DocumentoCxC.objects.get(cliente=self.cliente)
        # El abono en efectivo entra a la caja abierta.
        registrar_abono(documento=doc, monto=Decimal("8000"), medio="EFE",
                        usuario=self.usuario)

        detalle = evidencia.ventas_por_medio(self.empresa)
        self.assertEqual(detalle["total_ventas"], Decimal("20000"),
                         "un abono no es una venta nueva")
        self.assertEqual(detalle["recibido"], Decimal("8000"),
                         "el abono sí es dinero que entró hoy")


class PorCobrarCuadra(BaseEvidencia):

    def test_los_documentos_suman_el_indicador(self):
        self._vender(FacturaVenta.MedioPago.CREDITO, cantidad=2, cliente=self.cliente)
        self._vender(FacturaVenta.MedioPago.CREDITO, cantidad=1, cliente=self.cliente)

        detalle = evidencia.por_cobrar(self.empresa)
        suma_filas = sum((f["doc"].saldo for f in detalle["filas"]), Decimal("0"))
        kpi = indicadores(self.empresa, usar_cache=False)["cxc_total"]

        self.assertEqual(suma_filas, detalle["total"])
        self.assertEqual(detalle["total"], kpi)
        self.assertTrue(detalle["cuadra"])

    def test_detecta_el_descuadre_del_saldo_denormalizado(self):
        """El motivo principal de esta pantalla.

        Se ensucia el campo `saldo` a mano —exactamente lo que puede pasar por
        una corrección manual en el admin o una transacción a medias— y se
        comprueba que la pantalla lo delata en vez de taparlo.
        """
        self._vender(FacturaVenta.MedioPago.CREDITO, cantidad=2, cliente=self.cliente)

        self.cliente.refresh_from_db()
        self.cliente.saldo = self.cliente.saldo - Decimal("5000")
        self.cliente.save(update_fields=["saldo"])

        detalle = evidencia.por_cobrar(self.empresa)
        self.assertFalse(detalle["cuadra"], "el descuadre pasó desapercibido")
        self.assertEqual(detalle["diferencia"], Decimal("-5000"))

    def test_no_lista_documentos_pagados(self):
        from ventas.cxc import registrar_abono

        self._vender(FacturaVenta.MedioPago.CREDITO, cantidad=1, cliente=self.cliente)
        doc = DocumentoCxC.objects.get(cliente=self.cliente)
        registrar_abono(documento=doc, monto=doc.saldo, medio="EFE", usuario=self.usuario)

        detalle = evidencia.por_cobrar(self.empresa)
        self.assertEqual(detalle["filas"], [])
        self.assertEqual(detalle["total"], Decimal("0"))


class PantallasResponden(BaseEvidencia):
    """Las tres vistas abren y exigen rol de gerente."""

    RUTAS = ["/evidencia/caja/", "/evidencia/medios-de-pago/", "/evidencia/por-cobrar/"]

    def test_el_gerente_las_abre(self):
        self.client.force_login(self.usuario)
        self._vender(FacturaVenta.MedioPago.EFECTIVO, cantidad=1)
        for ruta in self.RUTAS:
            with self.subTest(ruta=ruta):
                r = self.client.get(ruta)
                self.assertEqual(r.status_code, 200, f"{ruta} no abrió")

    def test_un_cajero_no_las_abre(self):
        cajero = User.objects.create_user("cajero_ev", password="x", is_staff=True)
        grupo, _ = Group.objects.get_or_create(name="Cajero")
        cajero.groups.add(grupo)
        self.client.force_login(cajero)
        for ruta in self.RUTAS:
            with self.subTest(ruta=ruta):
                r = self.client.get(ruta)
                self.assertEqual(r.status_code, 302,
                                 f"{ruta} se le mostró a un cajero")
