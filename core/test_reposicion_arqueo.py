"""Pruebas de diferencias de arqueo. (Las de reposición por velocidad se
mudaron a inventario/test_reponer.py el 26/11/2026.)

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
from core import arqueo
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento
from ventas.models import FacturaVenta
from ventas.services import registrar_venta


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
