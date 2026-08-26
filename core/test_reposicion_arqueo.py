"""Pruebas de reposición por velocidad y de diferencias de arqueo.

Las dos funciones existen para corregir un punto ciego, y lo que se prueba acá
es justamente que el punto ciego quede cubierto:

- Reposición: que un producto que rota rápido avise ANTES que uno que no rota,
  aunque los dos tengan el mismo `stock_minimo`. Ese es todo el punto; si no
  se cumple, el cálculo no aporta nada sobre el criterio viejo.
- Arqueo: que un faltante sistemático se distinga de diferencias que caen a
  los dos lados. Un promedio los cancela y no ve nada.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from caja.models import SesionCaja
from caja.services import abrir_caja, cerrar_caja
from catalogo.models import Categoria, Producto
from core import arqueo, reposicion
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta
from ventas.services import registrar_venta


class ReposicionPorVelocidad(TestCase):

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Bodega")
        self.usuario = User.objects.create_user("g", password="x", is_staff=True, is_superuser=True)
        self.categoria = Categoria.objects.create(nombre="Test")
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario,
                                 monto_apertura=Decimal("0"))

    def _producto(self, sku, stock, minimo=2):
        p = Producto.objects.create(
            empresa=self.empresa, sku=sku, nombre=f"Producto {sku}",
            categoria=self.categoria, precio_venta=Decimal("1000"),
            costo_promedio=Decimal("500"), stock_minimo=Decimal(minimo),
        )
        if stock:
            registrar_movimiento(
                producto=p, bodega=self.bodega, tipo="ENT", cantidad=Decimal(stock),
                costo_unitario=Decimal("500"), referencia="carga", usuario=self.usuario,
            )
        p.refresh_from_db()
        return p

    def _vender(self, producto, cantidad):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago=FacturaVenta.MedioPago.EFECTIVO,
            usuario=self.usuario,
            lineas=[{"producto_id": producto.pk, "cantidad": Decimal(cantidad)}],
        )

    def test_el_que_rota_rapido_avisa_antes_con_el_mismo_minimo(self):
        """El defecto que se vino a corregir.

        Los dos productos quedan con stock por encima de su mínimo, así que
        con el criterio viejo ninguno aparece. Con velocidad la foto cambia:
        el que vendió 60 unidades en la ventana promedia 1 por día y le
        quedan 20 de stock (20 días de cobertura); el que vendió 2 promedia
        0,03 por día y le quedan 18 (más de un año). Hay que comprar el
        primero y no tocar el segundo, y eso el mínimo fijo no lo distingue.

        Ojo con el matiz: la cobertura se calcula sobre el promedio de la
        VENTANA (60 días), no sobre lo que se vendió hoy. Una venta grande de
        un día no vuelve crítico a un producto — y eso es deseable, porque si
        no, cada venta mayorista dispararía una orden de compra.
        """
        rapido = self._producto("RAPIDO", stock=80, minimo=2)
        lento = self._producto("LENTO", stock=20, minimo=2)
        self._vender(rapido, 60)
        self._vender(lento, 2)
        # Queda stock suficiente para que NINGUNO esté bajo el mínimo viejo.
        rapido.refresh_from_db(); lento.refresh_from_db()
        self.assertGreater(rapido.stock_actual, rapido.stock_minimo)
        self.assertGreater(lento.stock_actual, lento.stock_minimo)

        datos = reposicion.sugerencias(self.empresa)
        por_sku = {f["producto"].sku: f for f in datos["filas"]}

        self.assertLess(por_sku["RAPIDO"]["cobertura"], por_sku["LENTO"]["cobertura"],
                        "el producto que más rota debería tener menos cobertura")
        self.assertGreater(por_sku["RAPIDO"]["sugerido"], por_sku["LENTO"]["sugerido"],
                           "habría que pedir más del que más se vende")
        # 20 días de cobertura: por debajo del objetivo de 30, por encima de
        # los 7 que marcan lo crítico.
        self.assertEqual(por_sku["RAPIDO"]["urgencia"], "reponer")
        self.assertEqual(por_sku["LENTO"]["urgencia"], "ok")

    def test_marca_como_critico_lo_que_no_llega_a_la_semana(self):
        """La banda que de verdad urge: menos de una semana de stock, que es
        lo que tarda en llegar un pedido al proveedor."""
        p = self._producto("URGENTE", stock=125, minimo=2)
        self._vender(p, 120)  # 2 por día en la ventana; quedan 5 → 2,5 días
        datos = reposicion.sugerencias(self.empresa)
        fila = next(f for f in datos["filas"] if f["producto"].sku == "URGENTE")
        self.assertEqual(fila["urgencia"], "critico")
        self.assertLess(fila["cobertura"], datos["dias_criticos"])

    def test_sin_ventas_cae_al_criterio_del_minimo_fijo(self):
        """Para lo que no rota, el mínimo fijo alcanza — y no se inventa una
        velocidad que no existe."""
        p = self._producto("QUIETO", stock=1, minimo=5)
        datos = reposicion.sugerencias(self.empresa)
        fila = next(f for f in datos["filas"] if f["producto"].sku == "QUIETO")

        self.assertIsNone(fila["cobertura"], "sin ventas no hay cobertura que calcular")
        self.assertEqual(fila["urgencia"], "bajo_minimo")
        self.assertEqual(fila["sugerido"], Decimal("4"), "5 de mínimo − 1 de stock")

    def test_marca_el_producto_que_estuvo_agotado(self):
        """El sesgo conocido del cálculo: si no había, no se vendió, y el
        promedio subestima justo donde más faltó. Se marca, no se corrige."""
        p = self._producto("AGOTADO", stock=10, minimo=2)
        self._vender(p, 10)
        p.refresh_from_db()
        self.assertEqual(p.stock_actual, Decimal("0"))

        datos = reposicion.sugerencias(self.empresa)
        fila = next(f for f in datos["filas"] if f["producto"].sku == "AGOTADO")
        self.assertTrue(fila["hubo_quiebre"])
        self.assertEqual(fila["urgencia"], "agotado")

    def test_nunca_sugiere_cantidades_negativas(self):
        """Un producto con stock de sobra no genera una orden negativa."""
        p = self._producto("SOBRA", stock=1000, minimo=2)
        self._vender(p, 1)
        datos = reposicion.sugerencias(self.empresa)
        fila = next(f for f in datos["filas"] if f["producto"].sku == "SOBRA")
        self.assertEqual(fila["sugerido"], Decimal("0"))
        self.assertEqual(fila["urgencia"], "ok")


class ArqueoPorCajero(TestCase):

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.honesto = User.objects.create_user("honesto", password="x", is_staff=True)
        self.sesgado = User.objects.create_user("sesgado", password="x", is_staff=True)

    def _cerrar_con_diferencia(self, usuario, diferencia):
        """Abre y cierra una caja dejando la diferencia pedida."""
        sesion = abrir_caja(sucursal=self.sucursal, usuario=usuario,
                            monto_apertura=Decimal("10000"))
        cerrar_caja(sesion=sesion, monto_contado=Decimal("10000") + Decimal(diferencia),
                    usuario=usuario)
        return sesion

    def test_distingue_el_faltante_sistematico_del_error_de_conteo(self):
        """La señal que se busca es el sesgo, no el monto.

        El cajero "honesto" descuadra tanto como el otro en total, pero sus
        diferencias caen a los dos lados: es error de conteo. El "sesgado"
        siempre pierde plata. Un promedio los dejaría parecidos.
        """
        for d in (500, -500, 700, -700, 600, -600):
            self._cerrar_con_diferencia(self.honesto, d)
        for d in (-500, -600, -450, -700, -520, -480):
            self._cerrar_con_diferencia(self.sesgado, d)

        datos = arqueo.por_cajero(self.empresa)
        por_usuario = {f["usuario"]: f for f in datos["filas"]}

        self.assertEqual(por_usuario["honesto"]["faltantes"], 3)
        self.assertEqual(por_usuario["honesto"]["sobrantes"], 3)
        self.assertFalse(por_usuario["honesto"]["revisar"],
                         "diferencias a los dos lados son error de conteo, no patrón")

        self.assertEqual(por_usuario["sesgado"]["faltantes"], 6)
        self.assertEqual(por_usuario["sesgado"]["sobrantes"], 0)
        self.assertTrue(por_usuario["sesgado"]["revisar"],
                        "seis faltantes seguidos sí son un patrón")
        self.assertTrue(datos["hay_revisar"])

    def test_no_acusa_con_pocos_cierres(self):
        """Con dos cierres no hay patrón, hay casualidad. Marcar a alguien por
        casualidad es peor que no mirar."""
        self._cerrar_con_diferencia(self.sesgado, -800)
        self._cerrar_con_diferencia(self.sesgado, -900)

        datos = arqueo.por_cajero(self.empresa)
        fila = next(f for f in datos["filas"] if f["usuario"] == "sesgado")
        self.assertEqual(fila["faltantes"], 2)
        self.assertFalse(fila["revisar"], "dos cierres no alcanzan para marcar a nadie")

    def test_las_diferencias_chicas_no_cuentan_como_descuadre(self):
        """Exigir el céntimo exacto genera ruido y entrena a ignorar la alerta."""
        for _ in range(6):
            self._cerrar_con_diferencia(self.honesto, -50)

        datos = arqueo.por_cajero(self.empresa)
        fila = next(f for f in datos["filas"] if f["usuario"] == "honesto")
        self.assertEqual(fila["faltantes"], 0, "₡50 está dentro de la tolerancia")
        self.assertEqual(fila["cuadrados"], 6)
        self.assertFalse(fila["revisar"])

    def test_la_evidencia_lista_solo_los_cierres_descuadrados(self):
        self._cerrar_con_diferencia(self.honesto, -50)      # dentro de tolerancia
        self._cerrar_con_diferencia(self.sesgado, -5000)    # descuadre real

        descuadres = arqueo.sesiones_descuadradas(self.empresa)
        self.assertEqual(descuadres.count(), 1)
        self.assertEqual(descuadres.first().usuario, self.sesgado)
