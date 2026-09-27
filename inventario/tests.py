"""Pruebas del núcleo de inventario: las reglas que protegen el negocio."""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Producto
from core.models import AuditLog, Empresa, Sucursal

from .models import Bodega, MovimientoInventario
from .services import registrar_movimiento


class BaseInventario(TestCase):
    def setUp(self):
        empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        sucursal = Sucursal.objects.create(empresa=empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=sucursal, nombre="Principal")
        self.producto = Producto.objects.create(
            empresa=empresa, sku="TEST-001", nombre="Producto de prueba", precio_venta=1000
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("10"), costo_unitario=Decimal("500"), referencia="INI-TEST",
        )
        self.producto.refresh_from_db()


class ReglasDeInventario(BaseInventario):
    def test_carga_inicial_fija_stock_y_costo(self):
        self.assertEqual(self.producto.stock_actual, Decimal("10"))
        self.assertEqual(self.producto.costo_promedio, Decimal("500.00"))

    def test_salida_descuenta_stock(self):
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="VEN",
            cantidad=Decimal("-4"), referencia="FE-TEST",
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("6"))

    def test_no_permite_stock_negativo(self):
        with self.assertRaises(ValidationError):
            registrar_movimiento(
                producto=self.producto, bodega=self.bodega, tipo="VEN",
                cantidad=Decimal("-11"), referencia="FE-TEST",
            )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # intacto

    def test_no_permite_cantidad_cero(self):
        with self.assertRaises(ValidationError):
            registrar_movimiento(
                producto=self.producto, bodega=self.bodega, tipo="AJU",
                cantidad=Decimal("0"), referencia="AJ-TEST",
            )

    def test_costo_promedio_ponderado(self):
        # 10 uds a 500 + 10 uds a 700 = promedio 600
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="COM",
            cantidad=Decimal("10"), costo_unitario=Decimal("700"), referencia="OC-TEST",
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.costo_promedio, Decimal("600.00"))

    def test_salida_no_cambia_costo_promedio(self):
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="VEN",
            cantidad=Decimal("-5"), referencia="FE-TEST",
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.costo_promedio, Decimal("500.00"))

    def test_kardex_guarda_resultantes(self):
        mov = registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="VEN",
            cantidad=Decimal("-3"), referencia="FE-TEST",
        )
        self.assertEqual(mov.stock_resultante, Decimal("7"))
        self.assertEqual(mov.costo_promedio_resultante, Decimal("500.00"))

    def test_todo_movimiento_queda_auditado(self):
        antes = AuditLog.objects.filter(tabla="inventario.movimientoinventario").count()
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="AJU",
            cantidad=Decimal("-1"), referencia="AJ-TEST", motivo="dañado",
        )
        despues = AuditLog.objects.filter(tabla="inventario.movimientoinventario").count()
        self.assertEqual(despues, antes + 1)


class PantallaAjuste(BaseInventario):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user("oscar", password="clave-test", is_staff=True, is_superuser=True)

    def test_requiere_login_de_staff(self):
        respuesta = self.client.get(reverse("inventario:ajuste"))
        self.assertEqual(respuesta.status_code, 302)  # redirige al login

    def test_ajuste_valido_crea_movimiento_con_usuario(self):
        self.client.login(username="oscar", password="clave-test")
        respuesta = self.client.post(reverse("inventario:ajuste"), {
            "producto": self.producto.pk,
            "bodega": self.bodega.pk,
            "cantidad": "-2",
            "costo_unitario": "0",
            "tipo": "Conteo físico",
            "motivo": "Conteo físico: faltante",
        })
        self.assertEqual(respuesta.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("8"))
        mov = MovimientoInventario.objects.filter(tipo="AJU").latest("id")
        self.assertEqual(mov.usuario, self.staff)
        self.assertIn("faltante", mov.motivo)
        # INV-05: el tipo queda al inicio del motivo, para poder sumarlo por tipo.
        self.assertTrue(mov.motivo.startswith("[Conteo físico] "))

    def test_ajuste_a_negativo_muestra_error_sin_mover_stock(self):
        self.client.login(username="oscar", password="clave-test")
        respuesta = self.client.post(reverse("inventario:ajuste"), {
            "producto": self.producto.pk,
            "bodega": self.bodega.pk,
            "cantidad": "-999",
            "costo_unitario": "0",
            "tipo": "Daño",
            "motivo": "prueba",
        })
        self.assertEqual(respuesta.status_code, 200)  # vuelve al formulario
        self.assertContains(respuesta, "Stock insuficiente")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))

    def test_auditoria_captura_usuario_e_ip(self):
        self.client.login(username="oscar", password="clave-test")
        self.client.post(reverse("inventario:ajuste"), {
            "producto": self.producto.pk,
            "bodega": self.bodega.pk,
            "cantidad": "1",
            "costo_unitario": "500",
            "tipo": "Conteo físico",
            "motivo": "Sobrante en conteo",
        })
        log = AuditLog.objects.filter(tabla="inventario.movimientoinventario").latest("fecha")
        self.assertEqual(log.usuario, self.staff)
        self.assertIsNotNone(log.ip)


class MarcadoDeEtiquetas(BaseInventario):
    """Pantalla de Etiquetas: separar pendiente de ya impresa (26/09/2026,
    a pedido de Oscar, para ponerse al día con las cargas de ZeeDog/Gosbi).

    Estas pruebas cubren el marcado A MANO. El marcado AUTOMÁTICO al
    imprimir de verdad vive del lado de `impresion` (esa vista es la que
    llama a `servicio.imprimir_etiqueta`) — ver impresion/tests.py."""

    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user("oscar", password="clave-test", is_staff=True, is_superuser=True)
        self.client.login(username="oscar", password="clave-test")

    def test_requiere_login(self):
        self.client.logout()
        respuesta = self.client.post(
            reverse("inventario:marcar_etiqueta", args=[self.producto.pk]), {"impresa": "1"}
        )
        self.assertEqual(respuesta.status_code, 302)  # redirige al login
        self.producto.refresh_from_db()
        self.assertIsNone(self.producto.etiqueta_impresa_en)

    def test_marcar_impresa_pone_fecha(self):
        respuesta = self.client.post(
            reverse("inventario:marcar_etiqueta", args=[self.producto.pk]), {"impresa": "1"}
        )
        self.assertEqual(respuesta.json()["ok"], True)
        self.producto.refresh_from_db()
        self.assertIsNotNone(self.producto.etiqueta_impresa_en)

    def test_marcar_pendiente_borra_la_fecha(self):
        self.producto.etiqueta_impresa_en = timezone.now()
        self.producto.save(update_fields=["etiqueta_impresa_en"])
        respuesta = self.client.post(
            reverse("inventario:marcar_etiqueta", args=[self.producto.pk]), {"impresa": "0"}
        )
        self.assertEqual(respuesta.json()["ok"], True)
        self.producto.refresh_from_db()
        self.assertIsNone(self.producto.etiqueta_impresa_en)

    def test_no_imprime_nada_solo_cambia_el_estado(self):
        """El marcado a mano no debe pasar por impresion.servicio: no gasta
        papel ni toca la cola de impresión."""
        antes = self.producto.actualizado_en
        self.client.post(
            reverse("inventario:marcar_etiqueta", args=[self.producto.pk]), {"impresa": "1"}
        )
        self.producto.refresh_from_db()
        # `actualizado_en` es auto_now: si save() se llamó con update_fields
        # limitado a etiqueta_impresa_en, no cambia.
        self.assertEqual(self.producto.actualizado_en, antes)

    def test_lote_marca_solo_los_ids_pedidos(self):
        otro = Producto.objects.create(
            empresa=self.producto.empresa, sku="TEST-002", nombre="Otro producto", precio_venta=500,
        )
        respuesta = self.client.post(reverse("inventario:marcar_etiquetas_lote"), {
            "ids": [self.producto.pk], "impresa": "1",
        })
        self.assertEqual(respuesta.json()["total"], 1)
        self.producto.refresh_from_db()
        otro.refresh_from_db()
        self.assertIsNotNone(self.producto.etiqueta_impresa_en)
        self.assertIsNone(otro.etiqueta_impresa_en)  # el que no se pidió, intacto

    def test_lote_puede_devolver_varios_a_pendiente(self):
        otro = Producto.objects.create(
            empresa=self.producto.empresa, sku="TEST-003", nombre="Otro más", precio_venta=500,
            etiqueta_impresa_en=timezone.now(),
        )
        self.producto.etiqueta_impresa_en = timezone.now()
        self.producto.save(update_fields=["etiqueta_impresa_en"])
        respuesta = self.client.post(reverse("inventario:marcar_etiquetas_lote"), {
            "ids": [self.producto.pk, otro.pk], "impresa": "0",
        })
        self.assertEqual(respuesta.json()["total"], 2)
        self.producto.refresh_from_db()
        otro.refresh_from_db()
        self.assertIsNone(self.producto.etiqueta_impresa_en)
        self.assertIsNone(otro.etiqueta_impresa_en)

    def test_lote_solo_toca_los_que_cambian_y_dice_cuales(self):
        """Lo que ya estaba puesto conserva su fecha, y la respuesta trae los
        ids cambiados: es lo que usa «Deshacer» (27/09/2026)."""
        antes = timezone.now() - timezone.timedelta(days=3)
        otro = Producto.objects.create(
            empresa=self.producto.empresa, sku="TEST-004", nombre="Ya puesto", precio_venta=500,
            etiqueta_impresa_en=antes,
        )
        d = self.client.post(reverse("inventario:marcar_etiquetas_lote"), {
            "ids": [self.producto.pk, otro.pk], "impresa": "1",
        }).json()
        self.assertEqual(d["ids"], [self.producto.pk])
        otro.refresh_from_db()
        self.assertEqual(otro.etiqueta_impresa_en, antes)

    def test_deshacer_un_lote_respeta_lo_impreso_de_verdad(self):
        from django.core.management import call_command
        from impresion.models import TrabajoImpresion

        empresa = self.producto.empresa
        lote = timezone.now()
        productos = [Producto.objects.create(empresa=empresa, sku=f"LOTE-{i}", nombre=f"P{i}",
                                             precio_venta=500, etiqueta_impresa_en=lote)
                     for i in range(25)]
        suelto = Producto.objects.create(empresa=empresa, sku="SUELTO", nombre="Marcado a mano",
                                         precio_venta=500, etiqueta_impresa_en=lote - timezone.timedelta(hours=1))
        salio = lote - timezone.timedelta(days=1)
        TrabajoImpresion.objects.create(tipo=TrabajoImpresion.ETIQUETA, formato=TrabajoImpresion.IMAGEN,
                                        impresora="X", titulo="Etiqueta LOTE-0", contenido=b"",
                                        estado=TrabajoImpresion.IMPRESO, vence_en=lote, terminado_en=salio)
        call_command("deshacer_marcado_etiquetas", stdout=StringIO())
        for p in productos + [suelto]:
            p.refresh_from_db()
        self.assertEqual(productos[0].etiqueta_impresa_en, salio)  # su etiqueta salió de verdad
        self.assertIsNone(productos[1].etiqueta_impresa_en)
        self.assertIsNotNone(suelto.etiqueta_impresa_en)  # marcado uno por uno: se respeta

    def test_pantalla_de_etiquetas_manda_el_estado_al_navegador(self):
        respuesta = self.client.get(reverse("inventario:etiquetas"))
        self.assertContains(respuesta, "etiqueta_impresa_en")
