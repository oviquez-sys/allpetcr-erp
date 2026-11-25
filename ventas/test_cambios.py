"""Cambios y devoluciones desde la caja (24/11/2026, ventas/cambios.py).

El caso que lo originó: pechera XL comprada por SINPE, cambiada por una XXL
pagando la diferencia por SINPE. Estas pruebas fijan que caja, banco,
inventario y contabilidad vean solo lo que de verdad pasó.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import override_settings
from django.urls import reverse

from caja.models import MovimientoCaja
from caja.resumen import resumen_cierre
from caja.services import cerrar_caja, esperado_por_medio
from catalogo.models import Producto
from contabilidad.models import LineaAsiento
from contabilidad.services import cuenta
from impresion.tiquete import bytes_devolucion, bytes_tiquete
from inventario.services import registrar_movimiento

from .cambios import buscar, registrar_cambio
from .cxc import crear_cxc  # noqa: F401  (la venta fiada la crea sola)
from .models import Cliente, DevolucionVenta, FacturaVenta
from .services import anular_factura, registrar_venta
from .devoluciones import registrar_devolucion
from .tests import BaseVentas

TALLA = DevolucionVenta.TipoMotivo.TALLA


class BaseCambio(BaseVentas):
    def setUp(self):
        super().setUp()
        self.xl = self.nuevo("PEC-XL", "Pechera talla XL", "12000", barras="7400000000011")
        self.xxl = self.nuevo("PEC-XXL", "Pechera talla XXL", "15000")
        self.collar = self.nuevo("COL-1", "Collar", "8000")

    def nuevo(self, sku, nombre, precio, barras=""):
        p = Producto.objects.create(empresa=self.empresa, sku=sku, nombre=nombre, precio_venta=Decimal(precio),
                                    codigo_barras=barras or None)
        registrar_movimiento(producto=p, bodega=self.bodega, tipo="INI", cantidad=Decimal("5"),
                             costo_unitario=Decimal("6000"), referencia="INI")
        p.refresh_from_db()
        return p

    def compra(self, producto, medio="SIN", **extra):
        return registrar_venta(sesion_caja=self.sesion, medio_pago=medio, usuario=self.usuario,
                               lineas=[{"producto_id": producto.pk, "cantidad": 1}], **extra)

    def cambiar(self, original, nuevos=(), medio="SIN", tipo=TALLA, es_gerente=True, usuario=None, **extra):
        return registrar_cambio(
            sesion_caja=self.sesion, factura_original=original,
            devolver=[{"linea_venta_id": original.lineas.get().pk, "cantidad": 1}], tipo_motivo=tipo,
            lineas_nuevas=[{"producto_id": p.pk, "cantidad": 1} for p in nuevos], medio_pago=medio,
            usuario=usuario or self.usuario, es_gerente=es_gerente, **extra)

    def stock(self, p):
        p.refresh_from_db()
        return p.stock_actual

    def saldo_cambios(self):
        c = cuenta(self.empresa, "cambios")
        t = LineaAsiento.objects.filter(cuenta=c).aggregate(d=Sum("debe"), h=Sum("haber"))
        return (t["d"] or 0) - (t["h"] or 0)


class LaPecheraDelViernes(BaseCambio):
    def test_cambio_xl_por_xxl_pagando_la_diferencia_por_sinpe(self):
        original = self.compra(self.xl, "SIN")
        dev, nueva = self.cambiar(original, [self.xxl], "SIN")
        # La venta nueva: ₡15.000, ₡12.000 pagados con la XL y ₡3.000 por SINPE.
        self.assertEqual(nueva.total, Decimal("15000"))
        self.assertEqual(nueva.medio_pago, "MIX")
        self.assertEqual(sorted(nueva.desglose_pagos()), [("CAM", Decimal("12000")), ("SIN", Decimal("3000"))])
        # La devolución: ligada a las dos ventas, sin plata que salga.
        self.assertEqual((dev.factura, dev.venta_cambio), (original, nueva))
        self.assertEqual(dev.total, Decimal("12000"))
        self.assertEqual(dev.aplicado_cambio, Decimal("12000"))
        self.assertEqual(dev.sale_plata, 0)
        # Inventario: vuelve la XL, sale la XXL.
        self.assertEqual(self.stock(self.xl), 5)
        self.assertEqual(self.stock(self.xxl), 4)
        # Por SINPE entraron ₡12.000 el día de la compra y ₡3.000 hoy: nada más.
        self.assertEqual(esperado_por_medio(self.sesion)["SIN"], Decimal("15000"))
        self.assertFalse(MovimientoCaja.objects.filter(tipo__in=["VEN", "ANU"], sesion=self.sesion)
                         .exclude(monto=0).filter(referencia=dev.numero).exists())
        # La cuenta puente queda en cero.
        self.assertEqual(self.saldo_cambios(), 0)

    def test_lo_nuevo_vale_menos_y_se_devuelve_el_resto_por_el_medio_original(self):
        original = self.compra(self.xl, "SIN")
        dev, nueva = self.cambiar(original, [self.collar], "SIN")
        self.assertEqual(nueva.medio_pago, "CAM")
        self.assertEqual(dev.aplicado_cambio, Decimal("8000"))
        self.assertEqual(dev.reembolso_bancos, Decimal("4000"))
        self.assertEqual(dev.reembolso_efectivo, 0)
        self.assertEqual(self.saldo_cambios(), 0)

    def test_compra_en_efectivo_la_diferencia_entra_a_la_gaveta(self):
        original = self.compra(self.xl, "EFE")
        dev, nueva = self.cambiar(original, [self.xxl], "EFE", monto_recibido=5000)
        self.assertEqual(nueva.vuelto, Decimal("2000"))
        self.assertEqual(MovimientoCaja.objects.get(referencia=nueva.numero).monto, Decimal("3000"))
        self.assertFalse(MovimientoCaja.objects.filter(referencia=dev.numero).exists())

    def test_cambio_parejo_no_cobra_nada(self):
        otra = self.nuevo("PEC-L", "Pechera talla L", "12000")
        original = self.compra(self.xl, "TAR")
        dev, nueva = self.cambiar(original, [otra], "CAM")
        self.assertEqual(nueva.medio_pago, "CAM")
        self.assertEqual(dev.sale_plata, 0)

    def test_un_cambio_no_da_numeros_del_sorteo_ni_tumba_el_cliente(self):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Ana", telefono="8888-1111")
        original = self.compra(self.xl, "SIN", cliente=cliente)
        _, nueva = self.cambiar(original, [self.xxl], "SIN")
        self.assertEqual(nueva.cliente, cliente)   # el cambio sigue siendo de ella
        self.assertFalse(hasattr(nueva, "numeros_campana") and nueva.numeros_campana)

    def test_la_diferencia_no_se_puede_fiar(self):
        original = self.compra(self.xl, "SIN")
        with self.assertRaises(ValidationError):
            self.cambiar(original, [self.xxl], "CRE")
        self.assertEqual(self.stock(self.xl), 4)   # no quedó nada a medias

    def test_la_venta_del_cambio_no_se_anula_pero_se_puede_devolver(self):
        original = self.compra(self.xl, "EFE")
        _, nueva = self.cambiar(original, [self.xxl], "SIN")
        with self.assertRaises(ValidationError):
            anular_factura(factura=nueva, motivo="x", usuario=self.usuario)
        # Devolver la XXL: lo que pagó la XL vuelve como efectivo (la compra
        # original fue en efectivo) y los ₡3.000 por SINPE.
        dev2 = registrar_devolucion(factura=nueva, lineas=[{"linea_venta_id": nueva.lineas.get().pk, "cantidad": 1}],
                                    tipo_motivo=TALLA, usuario=self.usuario)
        self.assertEqual(dev2.reembolso_efectivo, Decimal("12000"))
        self.assertEqual(dev2.reembolso_bancos, Decimal("3000"))


class DevolucionesSolas(BaseCambio):
    def test_devolucion_sin_cambio_devuelve_por_el_medio_original(self):
        original = self.compra(self.xl, "EFE")
        dev, nueva = self.cambiar(original, [])
        self.assertIsNone(nueva)
        self.assertEqual(dev.reembolso_efectivo, Decimal("12000"))
        self.assertEqual(MovimientoCaja.objects.get(referencia=dev.numero).monto, Decimal("-12000"))
        self.assertEqual(dev.sesion_caja, self.sesion)

    def test_defectuoso_no_vuelve_a_la_estanteria(self):
        original = self.compra(self.xl, "SIN")
        dev, _ = self.cambiar(original, [self.xl], "CAM", tipo=DevolucionVenta.TipoMotivo.DEFECTUOSO)
        self.assertEqual(self.stock(self.xl), 3)   # salió una buena y la dañada no entró
        self.assertFalse(dev.lineas.get().a_inventario)

    def test_otro_pide_el_motivo_escrito(self):
        original = self.compra(self.xl, "SIN")
        with self.assertRaises(ValidationError):
            self.cambiar(original, [], tipo=DevolucionVenta.TipoMotivo.OTRO)
        dev, _ = self.cambiar(original, [], tipo=DevolucionVenta.TipoMotivo.OTRO, motivo="Se lo regalaron repetido")
        self.assertEqual(dev.motivo, "Se lo regalaron repetido")

    def test_fuera_de_plazo_solo_el_gerente(self):
        original = self.compra(self.xl, "SIN")
        FacturaVenta.objects.filter(pk=original.pk).update(creado_en=original.creado_en - timedelta(days=16))
        original.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "Solo el gerente"):
            self.cambiar(original, [self.xxl], "SIN", es_gerente=False)
        dev, _ = self.cambiar(original, [self.xxl], "SIN", es_gerente=True)
        self.assertEqual(dev.aplicado_cambio, Decimal("12000"))

    def test_fiado_primero_baja_lo_que_debe(self):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Luis", limite_credito=Decimal("50000"))
        original = self.compra(self.xl, "CRE", cliente=cliente)
        dev, nueva = self.cambiar(original, [self.xxl], "SIN")
        # No había pagado la XL: no le paga la XXL. Se le rebaja la deuda.
        self.assertEqual(dev.rebajado_cxc, Decimal("12000"))
        self.assertEqual(dev.aplicado_cambio, 0)
        self.assertEqual(nueva.medio_pago, "SIN")
        cliente.refresh_from_db()
        self.assertEqual(cliente.saldo, 0)


class EnLaCaja(BaseCambio):
    def setUp(self):
        super().setUp()
        self.cajero = User.objects.create_user("cajero", password="x", is_staff=True)
        self.cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(self.usuario)

    def post(self, datos):
        r = self.client.post(reverse("ventas:vender"), json.dumps(datos), content_type="application/json")
        return r, r.json()

    def test_el_pos_registra_el_cambio_completo(self):
        original = self.compra(self.xl, "SIN")
        r, d = self.post({"medio_pago": "SIN", "clave": "cambio-1",
                          "lineas": [{"producto_id": self.xxl.pk, "cantidad": 1}],
                          "devolucion": {"factura_id": original.pk, "tipo_motivo": "TAL",
                                         "lineas": [{"linea_venta_id": original.lineas.get().pk, "cantidad": 1}]}})
        self.assertEqual(r.status_code, 200, d)
        self.assertEqual(d["cambio"]["aplicado"], 12000)
        self.assertEqual(d["cambio"]["diferencia"], 3000)
        # Mismo cobro dos veces (doble toque): no duplica nada.
        self.post({"medio_pago": "SIN", "clave": "cambio-1",
                   "lineas": [{"producto_id": self.xxl.pk, "cantidad": 1}],
                   "devolucion": {"factura_id": original.pk, "tipo_motivo": "TAL",
                                  "lineas": [{"linea_venta_id": original.lineas.get().pk, "cantidad": 1}]}})
        self.assertEqual(DevolucionVenta.objects.count(), 1)
        self.assertEqual(self.stock(self.xxl), 4)

    def test_el_pos_registra_una_devolucion_sola(self):
        original = self.compra(self.xl, "SIN")
        r, d = self.post({"medio_pago": "", "lineas": [],
                          "devolucion": {"factura_id": original.pk, "tipo_motivo": "GUS",
                                         "lineas": [{"linea_venta_id": original.lineas.get().pk, "cantidad": 1}]}})
        self.assertTrue(d["devolucion"], d)
        self.assertEqual(d["bancos"], 12000)

    def test_buscar_por_codigo_tiquete_y_whatsapp(self):
        cliente = Cliente.objects.create(empresa=self.empresa, nombre="Ana", telefono="8888-1111")
        original = self.compra(self.xl, "SIN", cliente=cliente)
        self.compra(self.xxl, "SIN")
        for texto in ("7400000000011", "PEC-XL", str(int(original.numero[3:])), original.numero, "88881111",
                      "pechera xl"):
            ventas, _ = buscar(self.empresa, texto)
            self.assertIn(original.pk, [v["id"] for v in ventas], texto)
        ventas, como = buscar(self.empresa, "7400000000011")
        self.assertEqual((como, len(ventas)), ("producto", 1))
        r = self.client.get(reverse("ventas:cambio_buscar"), {"q": "PEC-XL"})
        linea = r.json()["ventas"][0]["lineas"][0]
        self.assertEqual((linea["precio"], linea["disponible"]), (12000, 1))
        # Ya devuelta, no se ofrece otra vez.
        self.cambiar(original, [])
        self.assertEqual(buscar(self.empresa, "PEC-XL")[0], [])

    def test_el_cajero_puede_devolver_desde_el_historial(self):
        original = self.compra(self.xl, "SIN")
        self.client.force_login(self.cajero)
        r = self.client.post(reverse("ventas:devolver", args=[original.pk]),
                             {f"cant_{original.lineas.get().pk}": "1", "tipo_motivo": "TAL"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(DevolucionVenta.objects.get().motivo, "Talla o tamaño")


class ControlEnElCierre(BaseCambio):
    @override_settings(CIERRE_AVISO_DESTINATARIOS=["oscar@example.com"])
    def test_el_cierre_lista_las_devoluciones_y_avisa_aunque_calce(self):
        original = self.compra(self.xl, "EFE")
        self.cambiar(original, [])     # salen ₡12.000 del cajón
        datos = resumen_cierre(self.sesion)
        self.assertEqual(len(datos["devoluciones_con_plata"]), 1)
        with self.captureOnCommitCallbacks(execute=True):
            cerrar_caja(sesion=self.sesion, monto_contado=Decimal("20000"), tarjeta_contado=0, sinpe_contado=0,
                        usuario=self.usuario)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("devolución con dinero", mail.outbox[0].subject)
        self.assertIn("EFECTIVO ₡12.000", mail.outbox[0].body)

    def test_tiquetes(self):
        original = self.compra(self.xl, "SIN")
        _, nueva = self.cambiar(original, [self.xxl], "SIN")
        texto = bytes_tiquete(nueva).decode("cp850", errors="replace")
        self.assertIn("DEVUELVE", texto)
        self.assertIn("DIFERENCIA PAGADA", texto)
        self.assertIn("Producto devuelto", texto)
        original2 = self.compra(self.collar, "EFE")
        dev, _ = self.cambiar(original2, [])
        texto = bytes_devolucion(dev, abrir_gaveta=True).decode("cp850", errors="replace")
        self.assertIn("DEVOLUCION", texto)
        self.assertIn("Devuelto en efectivo", texto)
