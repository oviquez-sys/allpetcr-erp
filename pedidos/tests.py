import threading
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from catalogo.models import Impuesto, Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from .models import AvisoDisponibilidad, CambioEstadoPedido, Pedido, ReservaStock
from .services import cambiar_estado, crear_pedido, reservar_stock


class BasePedidos(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")  # RTS por defecto
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="W-001", nombre="Correa web", precio_venta=Decimal("5000"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("10"), costo_unitario=Decimal("2000"), referencia="INI",
        )
        self.producto.refresh_from_db()

    def _crear(self, **extra):
        datos = dict(
            empresa=self.empresa, sucursal=self.sucursal,
            cliente_nombre="Cliente Web", cliente_telefono="8888-0000",
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2}],
        )
        datos.update(extra)
        return crear_pedido(**datos)


class CrearPedido(BasePedidos):
    def test_crea_pedido_y_descuenta_stock(self):
        pedido = self._crear()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("8"))
        self.assertEqual(pedido.total, Decimal("10000"))
        self.assertEqual(pedido.estado, Pedido.Estado.PAGO_CONFIRMADO)
        self.assertTrue(pedido.numero.startswith("PED-"))

    def test_regimen_simplificado_no_desglosa_impuesto(self):
        pedido = self._crear()
        self.assertEqual(pedido.impuesto, Decimal("0"))
        self.assertEqual(pedido.subtotal, pedido.total)

    def test_regimen_tradicional_desglosa_iva(self):
        iva = Impuesto.objects.create(nombre="IVA general", tarifa=Decimal("13"))
        self.producto.impuesto = iva
        self.producto.save()
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL
        self.empresa.save()
        pedido = self._crear(lineas=[{"producto_id": self.producto.pk, "cantidad": 1}])  # precio 5000 incluye IVA
        self.assertEqual(pedido.subtotal, Decimal("4424.78"))
        self.assertEqual(pedido.impuesto, Decimal("575.22"))
        self.assertEqual(pedido.total, Decimal("5000.00"))

    def test_sin_lineas_falla(self):
        with self.assertRaises(ValidationError):
            self._crear(lineas=[])

    def test_registra_bitacora_de_creacion(self):
        pedido = self._crear()
        cambio = CambioEstadoPedido.objects.get(pedido=pedido)
        self.assertEqual(cambio.estado_anterior, Pedido.Estado.PAGO_CONFIRMADO)
        self.assertEqual(cambio.estado_nuevo, Pedido.Estado.PAGO_CONFIRMADO)

    def test_libera_la_reserva_del_carrito_al_confirmar(self):
        reservar_stock(producto=self.producto, cantidad=Decimal("2"), token_carrito="carrito-x")
        self._crear(token_carrito="carrito-x")
        self.assertFalse(ReservaStock.objects.filter(token_carrito="carrito-x").exists())

    # ---- Idempotencia (secuencial): el mismo webhook reenviado ----
    def test_referencia_pago_repetida_no_descuenta_dos_veces(self):
        p1 = self._crear(referencia_pago="pago-123")
        p2 = self._crear(referencia_pago="pago-123")
        self.assertEqual(p1.pk, p2.pk)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("8"))  # solo se descontó una vez
        self.assertEqual(Pedido.objects.filter(referencia_pago="pago-123").count(), 1)

    def test_referencia_pago_vacia_no_se_deduplica(self):
        p1 = self._crear()
        p2 = self._crear()
        self.assertNotEqual(p1.pk, p2.pk)  # sin referencia, cada llamada es un pedido nuevo


class CambiarEstadoPedido(BasePedidos):
    def test_avanza_por_la_secuencia_normal(self):
        pedido = self._crear()
        pedido = cambiar_estado(pedido=pedido, nuevo_estado=Pedido.Estado.EN_PREPARACION)
        self.assertEqual(pedido.estado, Pedido.Estado.EN_PREPARACION)
        pedido = cambiar_estado(pedido=pedido, nuevo_estado=Pedido.Estado.DESPACHADO)
        pedido = cambiar_estado(pedido=pedido, nuevo_estado=Pedido.Estado.ENTREGADO)
        self.assertEqual(pedido.estado, Pedido.Estado.ENTREGADO)
        self.assertEqual(pedido.cambios_estado.count(), 4)  # creación + 3 avances

    def test_rechaza_saltarse_estados(self):
        pedido = self._crear()
        with self.assertRaises(ValidationError):
            cambiar_estado(pedido=pedido, nuevo_estado=Pedido.Estado.ENTREGADO)

    def test_entregado_es_estado_final(self):
        pedido = self._crear()
        for estado in (Pedido.Estado.EN_PREPARACION, Pedido.Estado.DESPACHADO, Pedido.Estado.ENTREGADO):
            pedido = cambiar_estado(pedido=pedido, nuevo_estado=estado)
        with self.assertRaises(ValidationError):
            cambiar_estado(pedido=pedido, nuevo_estado=Pedido.Estado.CANCELADO)

    def test_se_puede_cancelar_antes_de_despachar(self):
        pedido = self._crear()
        pedido = cambiar_estado(pedido=pedido, nuevo_estado=Pedido.Estado.CANCELADO, nota="Cliente se arrepintió")
        self.assertEqual(pedido.estado, Pedido.Estado.CANCELADO)

    def test_bitacora_guarda_usuario_y_nota(self):
        from django.contrib.auth.models import User
        usuario = User.objects.create_user("bodeguero")
        pedido = self._crear()
        cambiar_estado(pedido=pedido, nuevo_estado=Pedido.Estado.EN_PREPARACION, usuario=usuario, nota="Empezando a armar")
        cambio = pedido.cambios_estado.order_by("-fecha").first()
        self.assertEqual(cambio.usuario, usuario)
        self.assertEqual(cambio.nota, "Empezando a armar")


class ReservarStock(BasePedidos):
    def test_reserva_dentro_del_disponible(self):
        reserva = reservar_stock(producto=self.producto, cantidad=Decimal("3"), token_carrito="c1")
        self.assertEqual(reserva.cantidad, Decimal("3"))
        self.assertGreater(reserva.expira_en, timezone.now())

    def test_no_deja_reservar_mas_de_lo_disponible(self):
        with self.assertRaises(ValidationError):
            reservar_stock(producto=self.producto, cantidad=Decimal("11"), token_carrito="c1")  # stock=10

    def test_respeta_lo_ya_reservado_por_otro_carrito(self):
        reservar_stock(producto=self.producto, cantidad=Decimal("7"), token_carrito="c1")
        with self.assertRaises(ValidationError):
            reservar_stock(producto=self.producto, cantidad=Decimal("4"), token_carrito="c2")  # solo quedan 3

    def test_mismo_carrito_actualiza_en_vez_de_sumar(self):
        reservar_stock(producto=self.producto, cantidad=Decimal("2"), token_carrito="c1")
        reservar_stock(producto=self.producto, cantidad=Decimal("5"), token_carrito="c1")  # cambió de opinión
        self.assertEqual(ReservaStock.objects.filter(token_carrito="c1").count(), 1)
        self.assertEqual(ReservaStock.objects.get(token_carrito="c1").cantidad, Decimal("5"))

    def test_reserva_vencida_libera_disponibilidad(self):
        vieja = reservar_stock(producto=self.producto, cantidad=Decimal("9"), token_carrito="c1")
        ReservaStock.objects.filter(pk=vieja.pk).update(expira_en=timezone.now() - timezone.timedelta(minutes=1))
        # Si la vencida siguiera contando, esto fallaría (9 + 5 > 10).
        reservar_stock(producto=self.producto, cantidad=Decimal("5"), token_carrito="c2")

    def test_cantidad_cero_o_negativa_se_rechaza(self):
        with self.assertRaises(ValidationError):
            reservar_stock(producto=self.producto, cantidad=Decimal("0"), token_carrito="c1")


class AvisosDisponibilidad(BasePedidos):
    def test_no_duplica_aviso_del_mismo_producto_y_correo(self):
        AvisoDisponibilidad.objects.create(producto=self.producto, email="a@x.com")
        with self.assertRaises(Exception):
            AvisoDisponibilidad.objects.create(producto=self.producto, email="a@x.com")


class ConcurrenciaReservaStock(TransactionTestCase):
    """La prueba que pide el encargo: dos compras simultáneas de la última
    unidad, solo una debe ganar. Usa TransactionTestCase (no TestCase) para
    que cada hilo tenga su propia conexión real a PostgreSQL — con
    TestCase todo el test corre envuelto en una sola transacción y esto no
    prueba nada."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="ULT-1", nombre="Última unidad", precio_venta=Decimal("1000"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("1"), costo_unitario=Decimal("500"), referencia="INI",
        )

    def test_dos_reservas_simultaneas_de_la_ultima_unidad_solo_una_gana(self):
        resultados = {}
        barrera = threading.Barrier(2)

        def intentar(token):
            connection.close()  # cada hilo abre su propia conexión a la base
            try:
                barrera.wait(timeout=5)  # ambos hilos arrancan lo más juntos posible
                reservar_stock(producto=self.producto, cantidad=Decimal("1"), token_carrito=token)
                resultados[token] = "ok"
            except ValidationError:
                resultados[token] = "rechazado"
            finally:
                connection.close()

        t1 = threading.Thread(target=intentar, args=("carrito-1",))
        t2 = threading.Thread(target=intentar, args=("carrito-2",))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        self.assertEqual(sorted(resultados.values()), ["ok", "rechazado"])
        self.assertEqual(ReservaStock.objects.filter(producto=self.producto).count(), 1)


class ConcurrenciaWebhookDuplicado(TransactionTestCase):
    """Idempotencia bajo concurrencia real: la pasarela reenvía el mismo
    aviso de pago dos veces AL MISMO TIEMPO (no solo uno después del otro).
    Solo un pedido debe crearse y el stock solo debe bajar una vez."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal", principal=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="W-002", nombre="Producto webhook", precio_venta=Decimal("2000"),
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("50"), costo_unitario=Decimal("1000"), referencia="INI",
        )

    def test_webhook_duplicado_simultaneo_crea_un_solo_pedido(self):
        resultados = []
        errores = []
        barrera = threading.Barrier(2)

        def intentar():
            connection.close()
            try:
                barrera.wait(timeout=5)
                pedido = crear_pedido(
                    empresa=self.empresa, sucursal=self.sucursal,
                    cliente_nombre="Cliente Web", cliente_telefono="8888-0000",
                    lineas=[{"producto_id": self.producto.pk, "cantidad": 3}],
                    referencia_pago="webhook-dup-1",
                )
                resultados.append(pedido.pk)
            except Exception as e:  # no debería pasar; se registra para el assert
                errores.append(repr(e))
            finally:
                connection.close()

        hilos = [threading.Thread(target=intentar) for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=15)

        self.assertEqual(errores, [])
        self.assertEqual(len(set(resultados)), 1)  # los dos hilos ven el MISMO pedido
        self.assertEqual(Pedido.objects.filter(referencia_pago="webhook-dup-1").count(), 1)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("47"))  # 50 - 3, no 50 - 6
