"""Verifica que los cálculos optimizados del dashboard den EXACTAMENTE lo
mismo que la lógica anterior (la que iteraba en Python).

No basta con que las pruebas pasen: ninguna cubría estos tres números. Si la
optimización cambiara aunque sea un colón, Oscar vería cifras equivocadas de
utilidad y margen todos los días sin enterarse.

Se corre como prueba de Django para tener base de datos de prueba y datos
reales sembrados.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import F, Sum, DecimalField
from django.db.models.functions import TruncDate
from django.test import TestCase
from django.utils import timezone

from caja.models import SesionCaja
from catalogo.models import Categoria, Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta, LineaVenta
from ventas.services import registrar_venta


class EquivalenciaDashboard(TestCase):
    """Compara lógica vieja (Python) contra nueva (base de datos)."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Bodega")
        self.usuario = User.objects.create_user("cajero_test", password="x", is_staff=True)
        self.categoria = Categoria.objects.create(nombre="Test")

        # Varios productos con stock y precios distintos, incluidos casos
        # borde: stock exactamente igual al mínimo, y stock por debajo.
        self.productos = []
        for i, (precio, costo, stock, minimo) in enumerate([
            (1000, 600, 10, 2),   # normal
            (2500, 1800, 2, 2),   # stock == mínimo (debe contar como bajo)
            (700, 400, 1, 5),     # bajo mínimo
            (15000, 9000, 50, 3), # normal, montos grandes
        ]):
            p = Producto.objects.create(
                empresa=self.empresa, sku=f"TEST-{i}", nombre=f"Producto {i}",
                categoria=self.categoria, precio_venta=Decimal(precio),
                costo_promedio=Decimal(costo), stock_minimo=Decimal(minimo),
            )
            registrar_movimiento(
                producto=p, bodega=self.bodega, tipo="ENT", cantidad=Decimal(stock),
                costo_unitario=Decimal(costo), referencia="carga inicial",
                usuario=self.usuario,
            )
            self.productos.append(p)

        # Varias ventas en días distintos dentro de la ventana de 7 días.
        sesion = SesionCaja.objects.create(
            sucursal=self.sucursal, usuario=self.usuario, estado="ABI",
            monto_apertura=Decimal("10000"),
        )
        for dias_atras, items in [(0, [(0, 2), (3, 1)]), (2, [(1, 1)]), (5, [(0, 1), (2, 1)])]:
            factura = registrar_venta(
                sesion_caja=sesion,
                lineas=[{"producto_id": self.productos[i].id, "cantidad": c} for i, c in items],
                medio_pago="EFE", usuario=self.usuario,
            )
            if dias_atras:
                nueva_fecha = timezone.now() - timedelta(days=dias_atras)
                FacturaVenta.objects.filter(pk=factura.pk).update(creado_en=nueva_fecha)

    def test_costo_mes_identico(self):
        hoy = timezone.localdate()
        inicio_mes = hoy.replace(day=1)
        lineas = LineaVenta.objects.filter(
            factura__empresa=self.empresa, factura__estado="EMI",
            factura__creado_en__date__gte=inicio_mes,
        )

        viejo = sum((l.costo_unitario * l.cantidad for l in lineas), Decimal("0"))
        nuevo = lineas.aggregate(
            t=Sum(F("costo_unitario") * F("cantidad"),
                  output_field=DecimalField(max_digits=14, decimal_places=2))
        )["t"] or Decimal("0")

        self.assertEqual(viejo, nuevo, f"costo_mes difiere: viejo={viejo} nuevo={nuevo}")
        self.assertGreater(nuevo, 0, "el escenario de prueba no generó costo; no probaría nada")

    def test_ventas_ultimos_7_identico(self):
        hoy = timezone.localdate()
        hace_7 = hoy - timedelta(days=7)
        emitidas = FacturaVenta.objects.filter(empresa=self.empresa, estado="EMI")

        viejo = []
        for i in range(7, -1, -1):
            fecha = hoy - timedelta(days=i)
            v = emitidas.filter(creado_en__date=fecha).aggregate(t=Sum("total"))["t"] or Decimal("0")
            viejo.append(float(v))

        por_dia = dict(
            emitidas.filter(creado_en__date__gte=hace_7)
            .annotate(dia=TruncDate("creado_en")).values("dia")
            .annotate(t=Sum("total")).values_list("dia", "t")
        )
        nuevo = [float(por_dia.get(hoy - timedelta(days=i)) or 0) for i in range(7, -1, -1)]

        self.assertEqual(viejo, nuevo, f"serie de 7 días difiere:\nviejo={viejo}\nnuevo={nuevo}")
        self.assertGreater(sum(nuevo), 0, "no hubo ventas en la ventana; no probaría nada")

    def test_num_stock_bajo_identico(self):
        qs = Producto.objects.filter(empresa=self.empresa, activo=True)

        viejo = sum(1 for p in qs if p.stock_actual <= p.stock_minimo)
        nuevo = qs.filter(stock_actual__lte=F("stock_minimo")).count()

        self.assertEqual(viejo, nuevo, f"stock bajo difiere: viejo={viejo} nuevo={nuevo}")
        self.assertGreater(nuevo, 0, "ningún producto quedó bajo mínimo; no probaría el caso")
