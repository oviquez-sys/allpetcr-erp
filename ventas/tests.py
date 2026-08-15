"""Pruebas del flujo completo de venta: la transacción central del sistema."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from caja.models import MovimientoCaja, SesionCaja
from caja.services import abrir_caja, cerrar_caja
from catalogo.models import Impuesto, Producto
from core.models import Empresa, Sucursal
from inventario.models import Bodega, MovimientoInventario
from inventario.services import registrar_movimiento

from .cxc import registrar_abono
from .devoluciones import registrar_devolucion
from .models import Cliente, DevolucionVenta, DocumentoCxC, FacturaVenta
from .services import anular_factura, registrar_venta


class BaseVentas(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")  # RTS por defecto
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.usuario = User.objects.create_user("oscar", password="clave-test", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Arnés prueba", precio_venta=Decimal("5000")
        )
        registrar_movimiento(
            producto=self.producto, bodega=self.bodega, tipo="INI",
            cantidad=Decimal("10"), costo_unitario=Decimal("2000"), referencia="INI",
        )
        self.producto.refresh_from_db()
        self.sesion = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("20000"))

    def vender(self, cantidad=1, medio="EFE"):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago=medio, usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": cantidad}],
        )


class FlujoDeVenta(BaseVentas):
    def test_venta_descuenta_inventario_y_mueve_caja(self):
        factura = self.vender(cantidad=2, medio="EFE")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("8"))
        self.assertEqual(factura.total, Decimal("10000"))
        mov = MovimientoCaja.objects.get(tipo=MovimientoCaja.Tipo.VENTA)
        self.assertEqual(mov.monto, Decimal("10000"))
        self.assertEqual(mov.referencia, factura.numero)

    def test_regimen_simplificado_no_desglosa_impuesto(self):
        factura = self.vender()
        self.assertEqual(factura.impuesto, Decimal("0"))
        self.assertEqual(factura.subtotal, factura.total)

    def test_regimen_tradicional_desglosa_iva(self):
        iva = Impuesto.objects.create(nombre="IVA general", tarifa=Decimal("13"))
        self.producto.impuesto = iva
        self.producto.save()
        self.empresa.regimen = Empresa.Regimen.TRADICIONAL
        self.empresa.save()
        factura = self.vender()  # precio 5000 incluye IVA
        self.assertEqual(factura.subtotal, Decimal("4424.78"))
        self.assertEqual(factura.impuesto, Decimal("575.22"))
        self.assertEqual(factura.total, Decimal("5000.00"))

    def test_consecutivos_no_se_repiten(self):
        n1 = self.vender().numero
        n2 = self.vender().numero
        self.assertNotEqual(n1, n2)
        self.assertTrue(n1.startswith("FV-") and n2.startswith("FV-"))

    def test_venta_sin_stock_revienta_completa(self):
        with self.assertRaises(ValidationError):
            self.vender(cantidad=99)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # intacto
        self.assertEqual(FacturaVenta.objects.count(), 0)  # nada a medias

    def test_venta_tarjeta_no_mueve_efectivo(self):
        self.vender(medio="TAR")
        self.assertFalse(MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.VENTA).exists())

    def test_no_vende_con_caja_cerrada(self):
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("20000"))
        with self.assertRaises(ValidationError):
            self.vender()


class Anulacion(BaseVentas):
    def test_anulacion_revierte_inventario_y_caja(self):
        factura = self.vender(cantidad=3, medio="EFE")
        anular_factura(factura=factura, motivo="Cliente devolvió el producto", usuario=self.usuario)
        self.producto.refresh_from_db()
        factura.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # regresó
        self.assertEqual(factura.estado, FacturaVenta.Estado.ANULADA)
        devolucion = MovimientoCaja.objects.get(tipo=MovimientoCaja.Tipo.ANULACION)
        self.assertEqual(devolucion.monto, Decimal("-15000"))

    def test_anulacion_exige_motivo(self):
        factura = self.vender()
        with self.assertRaises(ValidationError):
            anular_factura(factura=factura, motivo="  ", usuario=self.usuario)

    def test_no_se_anula_dos_veces(self):
        factura = self.vender()
        anular_factura(factura=factura, motivo="error", usuario=self.usuario)
        with self.assertRaises(ValidationError):
            anular_factura(factura=factura, motivo="otra vez", usuario=self.usuario)


class ArqueoDeCaja(BaseVentas):
    def test_cierre_calcula_esperado_y_diferencia(self):
        self.vender(cantidad=2, medio="EFE")  # +10000
        sesion = cerrar_caja(sesion=self.sesion, monto_contado=Decimal("29500"))
        self.assertEqual(sesion.monto_esperado, Decimal("30000"))  # 20000 + 10000
        self.assertEqual(sesion.diferencia, Decimal("-500"))  # faltante

    def test_sesion_cerrada_no_admite_movimientos(self):
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("20000"))
        self.sesion.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.vender()


class PantallaPOS(BaseVentas):
    def test_pos_redirige_sin_caja_abierta(self):
        from django.contrib.auth.models import Group
        otro = User.objects.create_user("cajero2", password="clave-test", is_staff=True)
        otro.groups.add(Group.objects.get(name="Cajero"))  # con rol, sin caja abierta
        self.client.login(username="cajero2", password="clave-test")
        respuesta = self.client.get(reverse("ventas:pos"))
        self.assertRedirects(respuesta, reverse("caja:abrir"))

    def test_endpoint_vender_flujo_completo(self):
        self.client.login(username="oscar", password="clave-test")
        respuesta = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":1}]}' % self.producto.pk,
            content_type="application/json",
        )
        datos = respuesta.json()
        self.assertTrue(datos["ok"])
        self.assertEqual(datos["total"], 5000.0)
        tiquete = self.client.get(datos["tiquete_url"])
        self.assertContains(tiquete, datos["numero"])

    def test_endpoint_rechaza_venta_sin_stock(self):
        self.client.login(username="oscar", password="clave-test")
        respuesta = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":999}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("Stock insuficiente", respuesta.json()["error"])


class DescuentosYRegalias(BaseVentas):
    """Sprint A: descuento por línea y regalías (salida a costo sin ingreso).
    Se verifica el efecto en total, caja, inventario y —lo más importante—
    que la contabilidad cuadre y registre en las cuentas correctas."""

    def _saldos(self, logico):
        from contabilidad.models import LineaAsiento
        from contabilidad.services import cuenta
        c = cuenta(self.empresa, logico)
        debe = sum((l.debe for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        haber = sum((l.haber for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        return debe, haber

    def _todo_cuadra(self):
        from contabilidad.models import Asiento
        for a in Asiento.objects.all():
            self.assertTrue(a.cuadra, f"Asiento {a.numero} descuadrado")

    # ---------- Descuentos ----------
    def test_descuento_reduce_total_y_caja(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2, "descuento_pct": 15}],
        )
        # 2 × 5000 = 10000; 15% de 10000 = 1500; total = 8500
        self.assertEqual(factura.total, Decimal("8500"))
        self.assertEqual(factura.descuento, Decimal("1500"))
        mov = MovimientoCaja.objects.get(tipo=MovimientoCaja.Tipo.VENTA)
        self.assertEqual(mov.monto, Decimal("8500"))

    def test_descuento_contabiliza_ventas_brutas_y_cuenta_descuentos(self):
        registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2, "descuento_pct": 15}],
        )
        _, ventas_h = self._saldos("ventas")       # ingreso bruto acreditado
        desc_d, _ = self._saldos("descuentos")     # descuento debitado (contra-ingreso)
        caja_d, _ = self._saldos("caja")
        self.assertEqual(ventas_h, Decimal("10000"))  # 2×5000 bruto
        self.assertEqual(desc_d, Decimal("1500"))     # 15% de 10000
        self.assertEqual(caja_d, Decimal("8500"))
        self._todo_cuadra()

    def test_descuento_porcentaje_mayor_100_es_rechazado(self):
        with self.assertRaises(ValidationError):
            registrar_venta(
                sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 150}],
            )

    # ---------- Regalías ----------
    def test_regalia_descuenta_stock_pero_no_cobra(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "es_regalia": True, "motivo": "prueba"}],
        )
        self.assertEqual(factura.total, Decimal("0"))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("9"))  # sí salió del inventario
        # No mueve caja (no hay cobro)
        self.assertFalse(MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.VENTA).exists())

    def test_regalia_costo_va_a_gasto_regalias_no_a_costo_ventas(self):
        registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "es_regalia": True, "motivo": "prueba"}],
        )
        gasto_d, _ = self._saldos("gasto_regalias")
        cventas_d, _ = self._saldos("costo_ventas")
        self.assertEqual(gasto_d, Decimal("2000"))    # costo promedio del producto
        self.assertEqual(cventas_d, Decimal("0"))      # NO ensucia el costo de ventas
        self._todo_cuadra()

    def test_regalia_genera_movimiento_kardex_tipo_REG(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "es_regalia": True, "motivo": "prueba"}],
        )
        mov = MovimientoInventario.objects.filter(tipo="REG", referencia=factura.numero).first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.cantidad, Decimal("-1"))

    def test_venta_mixta_vendido_y_regalado(self):
        # Producto 2 para separar líneas
        p2 = Producto.objects.create(empresa=self.empresa, sku="P-002", nombre="Snack", precio_venta=Decimal("3000"))
        registrar_movimiento(producto=p2, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("5"), costo_unitario=Decimal("1000"), referencia="INI")
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[
                {"producto_id": self.producto.pk, "cantidad": 1},                 # vende 5000
                {"producto_id": p2.pk, "cantidad": 1, "es_regalia": True, "motivo": "prueba"},        # regala (costo 1000)
            ],
        )
        self.assertEqual(factura.total, Decimal("5000"))
        cventas_d, _ = self._saldos("costo_ventas")
        gasto_d, _ = self._saldos("gasto_regalias")
        self.assertEqual(cventas_d, Decimal("2000"))   # costo del producto vendido
        self.assertEqual(gasto_d, Decimal("1000"))     # costo del producto regalado
        self._todo_cuadra()

    def test_anular_venta_con_descuento_cuadra(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2, "descuento": 1500}],
        )
        anular_factura(factura=factura, motivo="prueba", usuario=self.usuario)
        # Tras anular, todo neteado y cuadrado
        desc_d, desc_h = self._saldos("descuentos")
        self.assertEqual(desc_d, desc_h)   # el débito original se revierte con un haber igual
        self._todo_cuadra()

    def test_endpoint_vender_acepta_descuento_porcentaje(self):
        self.client.login(username="oscar", password="clave-test")
        r = self.client.post(
            reverse("ventas:vender"),
            data=('{"medio_pago":"EFE","lineas":['
                  '{"producto_id":%d,"cantidad":1,"descuento_pct":10}]}' % self.producto.pk),
            content_type="application/json",
        )
        self.assertTrue(r.json()["ok"])
        # 5000 × 10% = 500; total = 4500
        self.assertEqual(r.json()["total"], 4500.0)


class AnularVentaDesdeElSistema(BaseVentas):
    """Sprint D: botón amigable de anular venta y bitácora de actividad."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_boton_anular_reversa_y_registra_quien(self):
        factura = self.vender(cantidad=2, medio="EFE")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("8"))
        r = self.client.post(reverse("ventas:anular", args=[factura.pk]),
                             data={"motivo": "cliente se arrepintió"})
        self.assertEqual(r.status_code, 302)  # redirige a actividad
        factura.refresh_from_db()
        self.assertEqual(factura.estado, FacturaVenta.Estado.ANULADA)
        self.assertEqual(factura.anulada_por, self.usuario)
        self.assertEqual(factura.motivo_anulacion, "cliente se arrepintió")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # stock devuelto

    def test_pagina_actividad_carga(self):
        self.vender(cantidad=1, medio="EFE")
        r = self.client.get(reverse("core:actividad"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Actividad y reversas")


class DevolucionesParciales(BaseVentas):
    """Devolución de solo algunos productos (o algunas unidades), días
    después, sin anular el tiquete completo. Cubre todos los escenarios de
    negocio: efectivo, tarjeta/SINPE, crédito con y sin abonos, descuentos,
    regalías, límites acumulados y validaciones."""

    def _saldo(self, logico):
        from contabilidad.models import LineaAsiento
        from contabilidad.services import cuenta
        c = cuenta(self.empresa, logico)
        debe = sum((l.debe for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        haber = sum((l.haber for l in LineaAsiento.objects.filter(cuenta=c)), Decimal("0"))
        return debe, haber

    def _todo_cuadra(self):
        from contabilidad.models import Asiento
        for a in Asiento.objects.all():
            self.assertTrue(a.cuadra, f"Asiento {a.numero} descuadrado")

    # ---------- Caso básico: efectivo ----------
    def test_devolucion_parcial_efectivo_devuelve_stock_y_dinero(self):
        factura = self.vender(cantidad=3, medio="EFE")  # 3 × 5000 = 15000
        linea = factura.lineas.first()
        dev = registrar_devolucion(
            factura=factura, motivo="no le sirvió",
            lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario,
        )
        self.assertEqual(dev.total, Decimal("5000"))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("8"))  # 10-3+1
        mov_caja = MovimientoCaja.objects.get(tipo=MovimientoCaja.Tipo.ANULACION, referencia=dev.numero)
        self.assertEqual(mov_caja.monto, Decimal("-5000"))
        self._todo_cuadra()

    def test_devolucion_queda_auditada(self):
        # AUD-001 (auditoría 2026-08-10): DevolucionVenta no estaba en el set
        # AUDITED de core/signals.py — una devolución fraudulenta (mercadería
        # que nunca volvió) no dejaba rastro en AuditLog, a diferencia de
        # todos los demás documentos de negocio (factura, abono, compra...).
        #
        # No se compara un conteo total antes/después: registrar_devolucion
        # crea el documento y LUEGO le fija `total` con un segundo save()
        # (ventas/devoluciones.py), así que con el modelo auditado quedan dos
        # filas (crear + editar) por devolución. Lo que exige AUD-001 es que
        # exista el registro de creación sobre el documento.
        #
        # No se afirma `log.usuario`: ese campo lo llena
        # core.middleware.get_current_user() vía CurrentUserMiddleware, que
        # solo corre en una request HTTP real — esta prueba llama al servicio
        # directo, igual que inventario.tests.test_todo_movimiento_queda_auditado,
        # que por la misma razón tampoco lo afirma. `usuario` vía middleware
        # ya está cubierto en inventario.tests.test_auditoria_captura_usuario_e_ip,
        # que sí pasa por el cliente HTTP.
        from core.models import AuditLog
        factura = self.vender(cantidad=2, medio="EFE")
        linea = factura.lineas.first()
        dev = registrar_devolucion(
            factura=factura, motivo="no le sirvió",
            lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                tabla="ventas.devolucionventa", objeto_id=str(dev.pk), accion="crear",
            ).exists()
        )

    def test_no_se_puede_devolver_mas_de_lo_comprado_acumulado(self):
        factura = self.vender(cantidad=3, medio="EFE")
        linea = factura.lineas.first()
        registrar_devolucion(factura=factura, motivo="prueba",
                             lineas=[{"linea_venta_id": linea.id, "cantidad": 2}], usuario=self.usuario)
        # Ya se devolvieron 2 de 3; solo queda 1 disponible.
        with self.assertRaises(ValidationError):
            registrar_devolucion(factura=factura, motivo="prueba",
                                 lineas=[{"linea_venta_id": linea.id, "cantidad": 2}], usuario=self.usuario)

    def test_dos_devoluciones_parciales_sucesivas_son_validas(self):
        factura = self.vender(cantidad=3, medio="EFE")
        linea = factura.lineas.first()
        registrar_devolucion(factura=factura, motivo="prueba",
                             lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario)
        registrar_devolucion(factura=factura, motivo="prueba",
                             lineas=[{"linea_venta_id": linea.id, "cantidad": 2}], usuario=self.usuario)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("10"))  # devolvió todo, volvió al original
        self.assertEqual(DevolucionVenta.objects.filter(factura=factura).count(), 2)

    # ---------- Con descuento ----------
    def test_devolucion_prorratea_el_descuento(self):
        # 20% > el 15% de SEC-001: esta prueba no trata sobre autorización de
        # descuentos, así que se autoriza explícitamente para aislar lo que
        # sí prueba (el prorrateo del descuento en la devolución).
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 4, "descuento_pct": 20}],
            permitir_descuento_alto=True,
        )
        # 4×5000=20000, 20% desc = 4000, total línea 16000 -> por unidad 4000
        linea = factura.lineas.first()
        dev = registrar_devolucion(
            factura=factura, motivo="prueba",
            lineas=[{"linea_venta_id": linea.id, "cantidad": 2}], usuario=self.usuario,
        )
        self.assertEqual(dev.total, Decimal("8000.00"))  # 2 × (16000/4)
        self._todo_cuadra()

    # ---------- Regalías ----------
    def test_devolucion_de_regalia_no_reembolsa_pero_devuelve_stock(self):
        # permitir_regalia_alta=True: 2 unidades a 5000 superan el tope de
        # SEC-006 (₡5000); esta prueba es sobre la devolución, no sobre el
        # tope, igual que test_devolucion_prorratea_el_descuento con SEC-001.
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2, "es_regalia": True, "motivo": "prueba"}],
            permitir_regalia_alta=True,
        )
        linea = factura.lineas.first()
        dev = registrar_devolucion(
            factura=factura, motivo="prueba",
            lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario,
        )
        self.assertEqual(dev.total, Decimal("0"))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("9"))  # 10-2+1
        self.assertFalse(MovimientoCaja.objects.filter(referencia=dev.numero).exists())  # no tocó caja
        gasto_d, _ = self._saldo("gasto_regalias")
        # Costo original 1000×2=2000 (costo_promedio 2000 x2 unidades regalo=... espera costo_promedio=2000)
        self._todo_cuadra()

    # ---------- Tarjeta / SINPE: no toca caja física ----------
    def test_devolucion_tarjeta_no_mueve_caja_fisica(self):
        factura = self.vender(cantidad=2, medio="TAR")  # Debe Bancos 10000 (venta original)
        linea = factura.lineas.first()
        dev = registrar_devolucion(
            factura=factura, motivo="prueba",
            lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario,
        )
        self.assertFalse(MovimientoCaja.objects.filter(referencia=dev.numero).exists())
        bancos_d, bancos_h = self._saldo("bancos")
        self.assertEqual(bancos_d, Decimal("10000"))  # de la venta original, sin cambios
        self.assertEqual(bancos_h, Decimal("5000"))    # la devolución acredita (reversa) 5000
        self._todo_cuadra()

    # ---------- Crédito sin abonos ----------
    def test_devolucion_credito_sin_abonos_reduce_cxc_y_cliente(self):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Cliente Test", limite_credito=Decimal("100000"))
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="CRE", usuario=self.usuario, cliente=cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 3}],  # 15000
        )
        linea = factura.lineas.first()
        registrar_devolucion(factura=factura, motivo="prueba",
                             lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario)  # 5000
        cliente.refresh_from_db()
        self.assertEqual(cliente.saldo, Decimal("10000"))  # 15000 - 5000
        doc = DocumentoCxC.objects.get(factura=factura)
        self.assertEqual(doc.saldo, Decimal("10000"))
        self.assertFalse(MovimientoCaja.objects.filter(referencia__startswith="DV").exists())

    # ---------- Crédito con abonos ya pagados: excedente en efectivo ----------
    def test_devolucion_credito_con_abonos_reembolsa_excedente_en_efectivo(self):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Cliente Test", limite_credito=Decimal("100000"))
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="CRE", usuario=self.usuario, cliente=cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2}],  # 10000
        )
        doc = DocumentoCxC.objects.get(factura=factura)
        registrar_abono(documento=doc, monto=Decimal("10000"), medio="EFE", usuario=self.usuario)  # pagó todo
        doc.refresh_from_db()
        self.assertEqual(doc.saldo, Decimal("0"))

        linea = factura.lineas.first()
        dev = registrar_devolucion(
            factura=factura, motivo="ya había pagado todo, devuelve 1",
            lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario,
        )  # 5000, pero saldo CxC ya es 0 -> todo se reembolsa en efectivo
        self.assertEqual(dev.total, Decimal("5000"))
        mov = MovimientoCaja.objects.get(referencia=dev.numero)
        self.assertEqual(mov.monto, Decimal("-5000"))
        self._todo_cuadra()

    def test_devolucion_credito_con_abonos_sin_caja_abierta_falla_claro(self):
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("20000"), usuario=self.usuario)
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Cliente Test", limite_credito=Decimal("100000"))
        # Necesito una sesión para vender a crédito; abro y cierro para simular que hoy no hay caja.
        sesion2 = abrir_caja(sucursal=self.sucursal, usuario=self.usuario, monto_apertura=Decimal("0"))
        factura = registrar_venta(
            sesion_caja=sesion2, medio_pago="CRE", usuario=self.usuario, cliente=cliente,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}],
        )
        doc = DocumentoCxC.objects.get(factura=factura)
        registrar_abono(documento=doc, monto=Decimal("5000"), medio="EFE", usuario=self.usuario)
        cerrar_caja(sesion=sesion2, monto_contado=Decimal("5000"), usuario=self.usuario)  # caja de hoy cerrada

        linea = factura.lineas.first()
        with self.assertRaises(ValidationError):
            registrar_devolucion(factura=factura, motivo="prueba",
                                 lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario)

    # ---------- Validaciones ----------
    def test_no_se_devuelve_sobre_factura_anulada(self):
        factura = self.vender(cantidad=2, medio="EFE")
        anular_factura(factura=factura, motivo="error", usuario=self.usuario)
        linea = factura.lineas.first()
        with self.assertRaises(ValidationError):
            registrar_devolucion(factura=factura, motivo="prueba",
                                 lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario)

    def test_motivo_obligatorio(self):
        factura = self.vender(cantidad=1, medio="EFE")
        linea = factura.lineas.first()
        with self.assertRaises(ValidationError):
            registrar_devolucion(factura=factura, motivo="   ",
                                 lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario)

    def test_efectivo_sin_caja_abierta_falla_claro(self):
        factura = self.vender(cantidad=2, medio="EFE")
        cerrar_caja(sesion=self.sesion, monto_contado=Decimal("30000"), usuario=self.usuario)
        linea = factura.lineas.first()
        with self.assertRaises(ValidationError):
            registrar_devolucion(factura=factura, motivo="prueba",
                                 lineas=[{"linea_venta_id": linea.id, "cantidad": 1}], usuario=self.usuario)

    # ---------- Vista end-to-end ----------
    def test_vista_devolver_formulario_y_envio(self):
        self.client.force_login(self.usuario)
        factura = self.vender(cantidad=2, medio="EFE")
        linea = factura.lineas.first()
        r = self.client.get(reverse("ventas:devolver", args=[factura.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, factura.numero)

        r2 = self.client.post(reverse("ventas:devolver", args=[factura.pk]), data={
            f"cant_{linea.id}": "1",
            "motivo": "cliente cambió de opinión",
        })
        self.assertEqual(r2.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("9"))  # 10-2+1
        self.assertTrue(DevolucionVenta.objects.filter(factura=factura).exists())


class RolesYPermisos(BaseVentas):
    """Sprint B: un cajero vende pero NO puede anular, devolver, recibir
    mercadería ni ver la bitácora. Solo el gerente. Esa separación es el
    control anti-fraude central."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Group
        # Cajero: solo staff + grupo Cajero (no superusuario).
        self.cajero = User.objects.create_user("maria", password="c", is_staff=True)
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        # Gerente: superusuario (como el dueño).
        self.gerente = self.usuario  # ya es superusuario en BaseVentas

    def test_cajero_puede_abrir_caja_y_vender(self):
        self.client.force_login(self.cajero)
        # Abre su propia caja
        r = self.client.post(reverse("caja:abrir"), {"sucursal": self.sucursal.id, "monto_apertura": "0"})
        self.assertEqual(r.status_code, 302)
        r2 = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":1}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertTrue(r2.json()["ok"])

    def test_cajero_no_puede_anular(self):
        factura = self.vender(cantidad=1, medio="EFE")
        self.client.force_login(self.cajero)
        r = self.client.post(reverse("ventas:anular", args=[factura.pk]), data={"motivo": "intento"})
        self.assertRedirects(r, reverse("core:dashboard"))  # rebotado
        factura.refresh_from_db()
        self.assertEqual(factura.estado, FacturaVenta.Estado.EMITIDA)  # NO se anuló

    def test_cajero_no_puede_devolver(self):
        factura = self.vender(cantidad=2, medio="EFE")
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("ventas:devolver", args=[factura.pk]))
        self.assertRedirects(r, reverse("core:dashboard"))

    def test_cajero_no_puede_ver_actividad(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("core:actividad"))
        self.assertRedirects(r, reverse("core:dashboard"))

    def test_cajero_no_puede_recibir_mercaderia(self):
        self.client.force_login(self.cajero)
        r = self.client.get(reverse("compras:nueva"))
        self.assertRedirects(r, reverse("core:dashboard"))

    def test_gerente_si_puede_anular(self):
        factura = self.vender(cantidad=1, medio="EFE")
        self.client.force_login(self.gerente)
        r = self.client.post(reverse("ventas:anular", args=[factura.pk]), data={"motivo": "corrección"})
        self.assertRedirects(r, reverse("core:actividad"))
        factura.refresh_from_db()
        self.assertEqual(factura.estado, FacturaVenta.Estado.ANULADA)


class VentaBajoCosto(BaseVentas):
    """Sprint B: no se puede vender por debajo del costo salvo autorización
    de gerente. (Producto: precio 5000, costo promedio 2000.)"""

    def test_bloquea_descuento_que_deja_bajo_costo(self):
        # 70% de descuento sobre 5000 = 1500 < 2000 de costo
        with self.assertRaises(ValidationError):
            registrar_venta(
                sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 70}],
                permitir_bajo_costo=False,
            )

    def test_gerente_puede_autorizar_bajo_costo(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 70}],
            permitir_bajo_costo=True,
            # 70% también supera el 15% de SEC-001: un gerente autoriza ambas
            # protecciones a la vez (la vista siempre las pasa juntas).
            permitir_descuento_alto=True,
        )
        self.assertEqual(factura.total, Decimal("1500.00"))

    def test_venta_normal_sobre_costo_no_se_bloquea(self):
        # 10% de 5000 = 4500 > 2000, pasa sin problema
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 10}],
            permitir_bajo_costo=False,
        )
        self.assertEqual(factura.total, Decimal("4500.00"))

    def test_endpoint_cajero_no_puede_vender_bajo_costo(self):
        from django.contrib.auth.models import Group
        cajero = User.objects.create_user("pedro", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir_caja(sucursal=self.sucursal, usuario=cajero, monto_apertura=Decimal("0"))
        self.client.force_login(cajero)
        r = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":1,"descuento_pct":70}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("costo", r.json()["error"].lower())


class VentaDescuentoAlto(BaseVentas):
    """SEC-001 (auditoría 2026-08-10): un cajero no puede aplicar más de
    DESCUENTO_MAXIMO_SIN_AUTORIZACION (15%) por línea sin que un gerente
    autorice la venta. Es una protección aparte del piso de costo: usa un
    20% sobre el producto de prueba (precio 5000, costo 2000) porque ese
    descuento NO baja del costo (total 4000 > 2000) — así se prueba el
    techo de descuento aislado, sin que el piso de costo interfiera."""

    def test_bloquea_descuento_mayor_al_umbral_sin_autorizacion(self):
        with self.assertRaises(ValidationError):
            registrar_venta(
                sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 20}],
                permitir_descuento_alto=False,
            )

    def test_gerente_puede_autorizar_descuento_alto(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 20}],
            permitir_descuento_alto=True,
        )
        self.assertEqual(factura.total, Decimal("4000.00"))

    def test_descuento_igual_al_umbral_no_requiere_autorizacion(self):
        # Exactamente 15%: dentro del límite, no se bloquea.
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": 15}],
            permitir_descuento_alto=False,
        )
        self.assertEqual(factura.total, Decimal("4250.00"))

    def test_endpoint_cajero_no_puede_superar_umbral_de_descuento(self):
        from django.contrib.auth.models import Group
        cajero = User.objects.create_user("laura", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir_caja(sucursal=self.sucursal, usuario=cajero, monto_apertura=Decimal("0"))
        self.client.force_login(cajero)
        r = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":1,"descuento_pct":20}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("15", r.json()["error"])

    def test_endpoint_gerente_si_puede_superar_umbral_de_descuento(self):
        # self.usuario (BaseVentas) ya es superusuario/gerente.
        self.client.force_login(self.usuario)
        r = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":1,"descuento_pct":20}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])


class VentaRegaliaAlta(BaseVentas):
    """SEC-006 (auditoría 2026-08-10): una regalía exige motivo siempre, y
    un cajero no puede regalar más de REGALIA_MAXIMA_SIN_AUTORIZACION
    (₡5000) por línea sin que un gerente autorice la venta. Producto de
    prueba: precio 5000, costo 2000 — 2 unidades regaladas valen ₡10000."""

    def test_bloquea_regalia_sin_motivo(self):
        with self.assertRaises(ValidationError):
            registrar_venta(
                sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "es_regalia": True}],
            )

    def test_bloquea_regalia_mayor_al_tope_sin_autorizacion(self):
        # 2 unidades × 5000 = 10000 > tope de 5000
        with self.assertRaises(ValidationError):
            registrar_venta(
                sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                lineas=[{"producto_id": self.producto.pk, "cantidad": 2, "es_regalia": True, "motivo": "prueba"}],
                permitir_regalia_alta=False,
            )

    def test_gerente_puede_autorizar_regalia_alta(self):
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 2, "es_regalia": True, "motivo": "prueba"}],
            permitir_regalia_alta=True,
        )
        self.assertEqual(factura.total, Decimal("0"))

    def test_regalia_igual_al_tope_no_requiere_autorizacion(self):
        # Exactamente 5000 (1 unidad): dentro del límite, no se bloquea.
        factura = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "es_regalia": True, "motivo": "prueba"}],
            permitir_regalia_alta=False,
        )
        self.assertEqual(factura.total, Decimal("0"))

    def test_endpoint_cajero_no_puede_superar_tope_de_regalia(self):
        from django.contrib.auth.models import Group
        cajero = User.objects.create_user("marta", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir_caja(sucursal=self.sucursal, usuario=cajero, monto_apertura=Decimal("0"))
        self.client.force_login(cajero)
        r = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":2,"es_regalia":true,"motivo":"prueba"}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("5000", r.json()["error"])

    def test_endpoint_cajero_no_puede_regalar_sin_motivo(self):
        from django.contrib.auth.models import Group
        cajero = User.objects.create_user("nora", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        abrir_caja(sucursal=self.sucursal, usuario=cajero, monto_apertura=Decimal("0"))
        self.client.force_login(cajero)
        r = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":1,"es_regalia":true}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("motivo", r.json()["error"].lower())

    def test_endpoint_gerente_si_puede_superar_tope_de_regalia(self):
        # self.usuario (BaseVentas) ya es superusuario/gerente.
        self.client.force_login(self.usuario)
        r = self.client.post(
            reverse("ventas:vender"),
            data='{"medio_pago":"EFE","lineas":[{"producto_id":%d,"cantidad":2,"es_regalia":true,"motivo":"prueba"}]}' % self.producto.pk,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
