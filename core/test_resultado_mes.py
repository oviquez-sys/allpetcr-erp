"""Ganancia y ventas del mes en el panel de Administración (20/09/2026).

Tres cosas que se contaban mal y que estas pruebas no dejan volver:
- el IVA cobrado (de Hacienda) entraba como venta y como ganancia;
- una devolución parcial no restaba ni la venta ni el costo;
- "vs mes anterior" comparaba lo que va del mes contra 30 días completos.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from caja.services import abrir_caja
from catalogo.models import Impuesto, Producto
from core import dashboard
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.devoluciones import registrar_devolucion
from ventas.models import FacturaVenta
from ventas.services import registrar_venta


class ResultadoDelMes(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        bodega = Bodega.objects.create(sucursal=sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-1", nombre="Arnés", precio_venta=Decimal("11300"),
            impuesto=Impuesto.objects.create(nombre="IVA", tarifa=Decimal("13")),
        )
        registrar_movimiento(producto=self.producto, bodega=bodega, tipo="INI",
                             cantidad=Decimal("20"), costo_unitario=Decimal("4000"), referencia="INI")
        self.sesion = abrir_caja(sucursal=sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))

    def vender(self, cantidad=1):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": cantidad}],
        )

    def mover_a(self, factura, dia):
        momento = timezone.make_aware(datetime.combine(dia, time(12)))
        FacturaVenta.objects.filter(pk=factura.pk).update(creado_en=momento)

    def test_tradicional_cuenta_ventas_y_ganancia_sin_iva(self):
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL
        self.empresa.save()
        self.vender(2)  # 22.600 cobrados: 20.000 de venta + 2.600 de IVA
        d = dashboard._calcular_indicadores(self.empresa)
        self.assertEqual(d["ventas_mes"], Decimal("20000.00"))
        self.assertEqual(d["utilidad_mes"], Decimal("12000.00"))  # 20.000 − 2 × 4.000
        self.assertEqual(round(d["margen"], 1), Decimal("60.0"))

    def test_simplificado_no_cambia(self):
        self.vender(2)
        d = dashboard._calcular_indicadores(self.empresa)
        self.assertEqual(d["ventas_mes"], Decimal("22600.00"))
        self.assertEqual(d["utilidad_mes"], Decimal("14600.00"))

    def test_devolucion_parcial_resta_venta_y_costo(self):
        factura = self.vender(3)  # 33.900, costo 12.000
        linea = factura.lineas.get()
        registrar_devolucion(factura=factura, motivo="talla", usuario=self.usuario,
                             lineas=[{"linea_venta_id": linea.pk, "cantidad": Decimal("1")}])
        d = dashboard._calcular_indicadores(self.empresa)
        self.assertEqual(d["ventas_mes"], Decimal("22600.00"))   # 33.900 − 11.300
        self.assertEqual(d["utilidad_mes"], Decimal("14600.00"))  # 22.600 − 2 × 4.000

    def test_compara_los_mismos_dias_del_mes_anterior(self):
        """El 5 de setiembre se compara contra el 1–5 de agosto, no contra 30 días."""
        hoy = date(2026, 9, 5)
        self.mover_a(self.vender(1), date(2026, 9, 3))    # setiembre: 11.300
        self.mover_a(self.vender(1), date(2026, 8, 2))    # agosto, dentro del 1–5
        self.mover_a(self.vender(1), date(2026, 8, 20))   # agosto, fuera: no cuenta
        with mock.patch("core.dashboard.timezone.localdate", return_value=hoy):
            d = dashboard._calcular_indicadores(self.empresa)
        self.assertEqual(d["ventas_mes"], Decimal("11300.00"))
        self.assertEqual(d["variacion_mes"], Decimal("0"))  # 11.300 vs 11.300
