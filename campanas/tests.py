"""Campañas con sorteo (Navidad AllPet 2026, 16/11/2026).

Lo que no se puede romper:
- una persona, una inscripción; cada compra suma números y la que SUPERA el
  umbral suma el bono (₡20.000 exactos no);
- una venta acredita una sola vez, y devolver o anular le quita lo que ya no
  merece;
- mientras la campaña corre no se emiten cupones de bienvenida nuevos, y los
  ya emitidos siguen valiendo;
- el sorteo es parejo por número, se hace una sola vez y deja todo guardado.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.utils import timezone

from catalogo.models import Producto
from inventario.services import registrar_movimiento
from manada.models import Cupon, Regalia
from manada.services import cupon_para_venta, registrar_miembro
from ventas.devoluciones import registrar_devolucion
from ventas.models import Cliente
from ventas.services import anular_factura, registrar_venta
from ventas.tests import BaseVentas

from . import reglas, sorteo
from .models import Adjudicacion, Campana, CanastaProducto, MovimientoNumeros, NumerosVenta, Participante


class ConCampana(BaseVentas):
    def setUp(self):
        super().setUp()
        ahora = timezone.now()
        self.campana = Campana.objects.create(
            empresa=self.empresa, nombre="Navidad AllPet 2026", slug="navidad-2026",
            inicio=ahora - timedelta(days=1), cierre=ahora + timedelta(days=30),
            sorteo_en=ahora + timedelta(days=31), bases="Bases de prueba.", estado=Campana.Estado.ACTIVA,
        )
        self.caro = Producto.objects.create(empresa=self.empresa, sku="P-CARO", nombre="Alimento 15 kg",
                                            precio_venta=Decimal("20001"))
        self.justo = Producto.objects.create(empresa=self.empresa, sku="P-JUSTO", nombre="Alimento 9 kg",
                                             precio_venta=Decimal("20000"))
        for p in (self.caro, self.justo):
            registrar_movimiento(producto=p, bodega=self.bodega, tipo="INI", cantidad=Decimal("10"),
                                 costo_unitario=Decimal("15000"), referencia="INI")
        self.maria = Cliente.objects.create(empresa=self.empresa, nombre="María", telefono="88881111")

    def inscribir(self, cliente=None, **extra):
        datos = dict(campana=self.campana, cliente=cliente or self.maria, canal=Participante.Canal.TIENDA)
        datos.update(extra)
        return reglas.inscribir(**datos)[0]

    def venta(self, producto=None, cliente="maria", cantidad=1, **extra):
        return registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
            cliente=self.maria if cliente == "maria" else cliente,
            lineas=[{"producto_id": (producto or self.producto).pk, "cantidad": cantidad}], **extra)

    def cerrar_y_pasar_al_sorteo(self):
        ahora = timezone.now()
        Campana.objects.filter(pk=self.campana.pk).update(
            cierre=ahora - timedelta(hours=2), sorteo_en=ahora - timedelta(hours=1))
        # Lo inscrito hasta ahora pasó ANTES de ese cierre.
        Participante.objects.filter(campana=self.campana).update(creado_en=ahora - timedelta(hours=3))
        self.campana.refresh_from_db()


class Inscripcion(ConCampana):
    def test_inscribirse_da_un_numero_y_solo_una_vez(self):
        p = self.inscribir()
        otra_vez, creado = reglas.inscribir(campana=self.campana, cliente=self.maria, canal="WEB")
        self.assertFalse(creado)
        self.assertEqual(otra_vez.pk, p.pk)
        self.assertEqual(reglas.saldo(p), 1)
        self.assertEqual(Participante.objects.count(), 1)

    def test_despues_del_cierre_no_se_inscribe(self):
        self.cerrar_y_pasar_al_sorteo()
        with self.assertRaises(ValidationError):
            self.inscribir()

    def test_en_borrador_no_se_inscribe(self):
        Campana.objects.filter(pk=self.campana.pk).update(estado=Campana.Estado.BORRADOR)
        self.campana.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.inscribir()


class NumerosPorCompra(ConCampana):
    def test_el_ejemplo_de_oscar_seis_numeros(self):
        """María se inscribe (1) y compra ₡5.000 (1), ₡20.001 (2), ₡20.001 (2) y ₡5.000 (1)."""
        p = self.inscribir()
        self.venta(self.producto)
        self.venta(self.caro)
        self.venta(self.caro)
        self.venta(self.producto)           # una más, chica: +1
        self.assertEqual(reglas.saldo(p), 1 + 1 + 2 + 2 + 1)

    def test_veinte_mil_exactos_no_ganan_el_bono(self):
        self.inscribir()
        f = self.venta(self.justo)
        self.assertEqual(f.total, Decimal("20000"))
        n = f.numeros_campana
        self.assertEqual((n.habituales, n.bono, n.total), (1, 0, 1))

    def test_un_colon_mas_si_lo_gana_y_queda_el_desglose(self):
        self.inscribir()
        n = self.venta(self.caro).numeros_campana
        self.assertEqual((n.habituales, n.bono, n.total), (1, 1, 2))
        self.assertEqual(n.monto_evaluado, Decimal("20001"))
        self.assertEqual(n.canal, NumerosVenta.Canal.TIENDA)
        tipos = sorted(n.movimientos.values_list("tipo", "cantidad"))
        self.assertEqual(tipos, [("BON", 1), ("COM", 1)])

    def test_el_umbral_se_mide_despues_del_descuento(self):
        self.inscribir()
        f = registrar_venta(
            sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario, cliente=self.maria,
            lineas=[{"producto_id": self.caro.pk, "cantidad": 1, "precio_final": "19500"}])
        self.assertEqual(f.total, Decimal("19500"))
        self.assertEqual(f.numeros_campana.bono, 0)

    def test_quien_no_esta_inscrito_no_gana_numeros(self):
        f = self.venta(self.caro)
        self.assertFalse(NumerosVenta.objects.filter(factura=f).exists())

    def test_inscribirse_antes_de_cobrar_hace_valer_esa_compra(self):
        p = self.inscribir()
        self.venta(self.caro)
        self.assertEqual(reglas.saldo(p), 3)

    def test_sin_cliente_no_hay_numeros(self):
        self.inscribir()
        f = self.venta(self.caro, cliente=None)
        self.assertFalse(NumerosVenta.objects.filter(factura=f).exists())

    def test_la_misma_venta_no_acredita_dos_veces(self):
        p = self.inscribir()
        f = self.venta(self.caro)
        reglas.acreditar_venta(f)
        reglas.acreditar_venta(f)
        self.assertEqual(reglas.saldo(p), 3)

    def test_compra_minima(self):
        Campana.objects.filter(pk=self.campana.pk).update(compra_minima=Decimal("6000"))
        p = self.inscribir()
        self.venta(self.producto)            # ₡5.000: no llega
        self.assertEqual(reglas.saldo(p), 1)

    def test_despues_del_cierre_una_compra_ya_no_da_numeros(self):
        p = self.inscribir()
        self.cerrar_y_pasar_al_sorteo()
        self.venta(self.caro)
        self.assertEqual(reglas.saldo(p), 1)

    def test_si_la_campana_falla_la_venta_no_se_cae(self):
        self.inscribir()
        with mock.patch("campanas.reglas._acreditar_venta", side_effect=RuntimeError("boom")):
            with self.assertLogs("campanas.reglas", level="ERROR"):
                f = self.venta(self.caro)
        self.assertEqual(f.estado, "EMI")


class Reversiones(ConCampana):
    def test_anular_quita_todos_los_numeros_de_esa_venta(self):
        p = self.inscribir()
        f = self.venta(self.caro)
        anular_factura(factura=f, motivo="Se equivocó de producto", usuario=self.usuario)
        n = NumerosVenta.objects.get(factura=f)
        self.assertEqual((n.total, n.revertidos, n.monto_vigente), (0, 2, Decimal("0")))
        self.assertEqual(reglas.saldo(p), 1)   # le queda el de la inscripción

    def test_devolucion_parcial_que_baja_del_umbral_quita_solo_el_bono(self):
        p = self.inscribir()
        f = registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario, cliente=self.maria,
                            lineas=[{"producto_id": self.justo.pk, "cantidad": 1},
                                    {"producto_id": self.producto.pk, "cantidad": 1}])
        self.assertEqual(f.numeros_campana.total, 2)       # ₡25.000
        chica = f.lineas.get(producto=self.producto)
        registrar_devolucion(factura=f, motivo="No le quedó",
                             lineas=[{"linea_venta_id": chica.pk, "cantidad": 1}], usuario=self.usuario)
        n = NumerosVenta.objects.get(factura=f)
        self.assertEqual((n.habituales, n.bono, n.revertidos), (1, 0, 1))
        self.assertEqual(n.monto_vigente, Decimal("20000"))
        self.assertEqual(reglas.saldo(p), 2)
        self.assertEqual(n.movimientos.filter(tipo="REV").count(), 1)

    def test_devolucion_total_quita_todo(self):
        p = self.inscribir()
        f = self.venta(self.caro)
        registrar_devolucion(factura=f, motivo="Cambio de opinión",
                             lineas=[{"linea_venta_id": f.lineas.get().pk, "cantidad": 1}], usuario=self.usuario)
        self.assertEqual(NumerosVenta.objects.get(factura=f).total, 0)
        self.assertEqual(reglas.saldo(p), 1)

    def test_devolver_algo_que_no_cambia_el_resultado_no_quita_nada(self):
        p = self.inscribir()
        f = registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario, cliente=self.maria,
                            lineas=[{"producto_id": self.caro.pk, "cantidad": 1},
                                    {"producto_id": self.producto.pk, "cantidad": 2}])
        una = f.lineas.get(producto=self.producto)
        registrar_devolucion(factura=f, motivo="Sobraba una",
                             lineas=[{"linea_venta_id": una.pk, "cantidad": 1}], usuario=self.usuario)
        self.assertEqual(reglas.saldo(p), 3)
        self.assertEqual(NumerosVenta.objects.get(factura=f).monto_vigente, Decimal("25001"))


class BienvenidaReemplazada(ConCampana):
    def setUp(self):
        super().setUp()
        Regalia.objects.create(empresa=self.empresa, porcentaje=Decimal("10"),
                               texto_cliente="10 % de descuento en tu primera compra")

    def test_con_la_campana_corriendo_no_se_emite_cupon_nuevo(self):
        r = registrar_miembro(empresa=self.empresa, nombre="Ana", telefono="88882222")
        self.assertIsNone(r.cupon)
        self.assertTrue(r.perfil_nuevo)          # igual se une a la manada

    def test_los_cupones_ya_emitidos_siguen_valiendo(self):
        Campana.objects.filter(pk=self.campana.pk).update(estado=Campana.Estado.BORRADOR)
        cupon = registrar_miembro(empresa=self.empresa, nombre="Ana", telefono="88882222").cupon
        Campana.objects.filter(pk=self.campana.pk).update(estado=Campana.Estado.ACTIVA)
        self.assertEqual(cupon_para_venta(self.empresa, cupon.codigo).pk, cupon.pk)
        f = registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 1}], cupon=cupon.codigo)
        self.assertEqual(f.total, Decimal("4500"))

    def test_en_borrador_la_bienvenida_sigue_igual(self):
        Campana.objects.filter(pk=self.campana.pk).update(estado=Campana.Estado.BORRADOR)
        self.assertIsNotNone(registrar_miembro(empresa=self.empresa, nombre="Ana", telefono="88882222").cupon)

    def test_al_finalizar_manda_lo_que_se_configuro(self):
        reglas.finalizar(self.campana)
        self.assertTrue(reglas.bloquea_bienvenida(self.empresa))       # por defecto: queda sin regalo
        Campana.objects.filter(pk=self.campana.pk).update(despues=Campana.Despues.BIENVENIDA)
        self.assertFalse(reglas.bloquea_bienvenida(self.empresa))
        self.assertEqual(Cupon.objects.count(), 0)
        self.assertIsNotNone(registrar_miembro(empresa=self.empresa, nombre="Ana", telefono="88882222").cupon)

    def test_la_demostracion_no_frena_nada(self):
        Campana.objects.filter(pk=self.campana.pk).update(es_demo=True)
        self.assertFalse(reglas.bloquea_bienvenida(self.empresa))
        self.assertIsNone(reglas.vigente(self.empresa))


class Beneficios(ConCampana):
    def b(self, monto, **extra):
        datos = dict(monto=Decimal(monto), participa=True)
        datos.update(extra)
        return reglas.beneficios(self.campana, **datos)

    def test_falta_para_el_bono(self):
        self.assertEqual(self.b("18500")["falta_para_bono"], Decimal("1501"))
        self.assertEqual(self.b("20000")["falta_para_bono"], Decimal("1"))
        self.assertEqual(self.b("20001")["falta_para_bono"], Decimal("0"))

    def test_envio_gratis_solo_sobre_el_umbral_y_en_zona(self):
        envio = lambda monto, canton, distrito="": self.b(monto, entrega="ENV", canton=canton, distrito=distrito)["envio"]
        self.assertTrue(envio("20001", "Heredia", "Mercedes")["gratis"])
        self.assertTrue(envio("20001", "heredia central", "san francisco")["gratis"])
        self.assertFalse(envio("20000", "Heredia", "Mercedes")["gratis"])      # exactos: no
        self.assertFalse(envio("50000", "Barva", "Barva")["gratis"])
        self.assertFalse(envio("50000", "Heredia", "Varablanca")["gratis"])    # mismo cantón, lejos
        self.assertFalse(envio("50000", "Heredia")["gratis"])                  # sin distrito no se promete
        self.assertFalse(self.b("50000", entrega="RET")["envio"]["aplica"])

    def test_zona_por_distrito(self):
        Campana.objects.filter(pk=self.campana.pk).update(zonas_envio="Heredia / Mercedes\nSan Pablo")
        self.campana.refresh_from_db()
        self.assertTrue(reglas.zona_califica(self.campana, "Heredia", "Mercedes"))
        self.assertFalse(reglas.zona_califica(self.campana, "Heredia", "Ulloa"))
        self.assertTrue(reglas.zona_califica(self.campana, "San Pablo", "Rincón de Sabanilla"))


class ElSorteo(ConCampana):
    def setUp(self):
        super().setUp()
        self.juan = Cliente.objects.create(empresa=self.empresa, nombre="Juan", telefono="88883333")
        self.ana = Cliente.objects.create(empresa=self.empresa, nombre="Ana", telefono="88884444")
        self.pm = self.inscribir(self.maria)
        self.pj = self.inscribir(self.juan)
        self.pa = self.inscribir(self.ana)
        self.venta(self.caro)                      # María: 1 + 2 = 3

    def test_la_lista_da_un_bloque_seguido_por_persona(self):
        lista = sorteo.armar_lista(self.campana)
        self.assertEqual([(f["nombre"], f["desde"], f["hasta"]) for f in lista],
                         [("María", 1, 3), ("Juan", 4, 4), ("Ana", 5, 5)])
        self.assertEqual(lista[0]["telefono"], "····1111")

    def test_no_se_congela_antes_del_cierre_ni_se_sortea_antes_de_la_hora(self):
        with self.assertRaises(ValidationError):
            sorteo.congelar(self.campana, self.usuario)
        with self.assertRaises(ValidationError):
            sorteo.sortear(self.campana, self.usuario)

    def test_congelar_guarda_la_lista_con_su_huella(self):
        self.cerrar_y_pasar_al_sorteo()
        s = sorteo.congelar(self.campana, self.usuario)
        self.assertEqual((s.total_participantes, s.total_numeros), (3, 5))
        self.assertEqual(s.huella, sorteo.huella_de(s.lista))
        self.campana.refresh_from_db()
        self.assertEqual(self.campana.estado, Campana.Estado.CERRADA)

    def test_gana_el_dueno_del_numero_que_sale(self):
        self.cerrar_y_pasar_al_sorteo()
        with mock.patch("campanas.sorteo.secrets.randbelow", return_value=3):   # 4.º número
            s, nuevo = sorteo.sortear(self.campana, self.usuario)
        self.assertTrue(nuevo)
        self.assertEqual(s.numero_ganador, 4)
        self.assertEqual(sorteo.titular(s).participante, self.pj)
        self.assertEqual(s.realizado_por, self.usuario)
        self.assertIn(s.huella, s.metodo)

    def test_la_segunda_pulsacion_devuelve_el_resultado_guardado(self):
        self.cerrar_y_pasar_al_sorteo()
        s1, _ = sorteo.sortear(self.campana, self.usuario)
        s2, nuevo = sorteo.sortear(self.campana, self.usuario)
        self.assertFalse(nuevo)
        self.assertEqual((s1.pk, s1.numero_ganador), (s2.pk, s2.numero_ganador))
        self.assertEqual(Adjudicacion.objects.count(), 1)

    def test_sin_permiso_no_sortea(self):
        self.cerrar_y_pasar_al_sorteo()
        cajero = User.objects.create_user("caja", password="x", is_staff=True)
        with self.assertRaises(ValidationError):
            sorteo.sortear(self.campana, cajero)
        cajero.user_permissions.add(Permission.objects.get(codename="sortear"))
        cajero = User.objects.get(pk=cajero.pk)
        self.assertTrue(sorteo.sortear(self.campana, cajero)[1])

    def test_sin_suplentes_en_las_bases_no_hay_suplentes(self):
        self.cerrar_y_pasar_al_sorteo()
        s, _ = sorteo.sortear(self.campana, self.usuario)
        self.assertEqual(s.adjudicaciones.count(), 1)

    def test_los_suplentes_son_personas_distintas(self):
        Campana.objects.filter(pk=self.campana.pk).update(suplentes=2)
        self.cerrar_y_pasar_al_sorteo()
        s, _ = sorteo.sortear(self.campana, self.usuario)
        personas = list(s.adjudicaciones.values_list("participante_id", flat=True))
        self.assertEqual(len(personas), 3)
        self.assertEqual(len(set(personas)), 3)

    def test_todos_los_numeros_pesan_igual(self):
        """Con 3 números de 5, María tiene que salir cerca del 60 %."""
        lista = sorteo.armar_lista(self.campana)
        veces = sum(1 for _ in range(4000) if sorteo._sacar(lista)[0]["nombre"] == "María")
        self.assertAlmostEqual(veces / 4000, 0.6, delta=0.04)

    def test_una_devolucion_despues_de_congelar_se_nota_y_se_puede_recongelar(self):
        self.cerrar_y_pasar_al_sorteo()
        s = sorteo.congelar(self.campana, self.usuario)
        f = NumerosVenta.objects.get().factura
        anular_factura(factura=f, motivo="Devolvió todo", usuario=self.usuario)
        self.assertTrue(sorteo.cambios_despues_de_congelar(s))
        s = sorteo.congelar(self.campana, self.usuario)
        self.assertEqual(s.total_numeros, 3)
        self.assertEqual(len(s.congelados_previos), 1)

    def test_si_no_responde_sube_el_suplente_y_despues_queda_desierto(self):
        Campana.objects.filter(pk=self.campana.pk).update(suplentes=1, plazo_reclamo_dias=5)
        self.cerrar_y_pasar_al_sorteo()
        s, _ = sorteo.sortear(self.campana, self.usuario)
        with self.assertRaises(ValidationError):          # todavía está en plazo
            sorteo.no_respondio(s, self.usuario)
        despues = timezone.now() + timedelta(days=6)
        nuevo = sorteo.no_respondio(s, self.usuario, momento=despues)
        self.assertEqual(nuevo.orden, 1)
        self.assertEqual(nuevo.estado, Adjudicacion.Estado.TITULAR)
        self.assertIsNone(sorteo.no_respondio(s, self.usuario, momento=despues + timedelta(days=6)))


class Entrega(ConCampana):
    def setUp(self):
        super().setUp()
        self.p = self.inscribir()
        CanastaProducto.objects.create(campana=self.campana, version="PER", producto=self.producto, cantidad=3)
        CanastaProducto.objects.create(campana=self.campana, version="PER", producto=self.caro, cantidad=1)
        self.cerrar_y_pasar_al_sorteo()
        self.sorteo, _ = sorteo.sortear(self.campana, self.usuario)

    def entregar(self, **extra):
        datos = dict(version="PER", recibe_nombre="María Pérez", recibe_identificacion="1-1111-1111",
                     usuario=self.usuario, sesion_caja=self.sesion)
        datos.update(extra)
        return sorteo.entregar(self.sorteo, **datos)

    def test_descuenta_el_inventario_y_deja_constancia_con_su_costo(self):
        e = self.entregar()
        self.producto.refresh_from_db(); self.caro.refresh_from_db()
        self.assertEqual((self.producto.stock_actual, self.caro.stock_actual), (Decimal("7"), Decimal("9")))
        self.assertEqual(e.costo, Decimal("2000") * 3 + Decimal("15000"))
        self.assertEqual(e.factura.total, Decimal("0"))
        self.assertTrue(all(l.es_regalia for l in e.factura.lineas.all()))
        self.assertEqual(sorteo.titular(self.sorteo).estado, Adjudicacion.Estado.ENTREGADO)
        # La venta de regalía no le da números a nadie.
        self.assertFalse(NumerosVenta.objects.filter(factura=e.factura).exists())

    def test_no_se_entrega_dos_veces(self):
        self.entregar()
        self.sorteo.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.entregar()

    def test_una_version_sin_productos_no_se_entrega(self):
        with self.assertRaises(ValidationError):
            self.entregar(version="GAT")

    def test_sin_existencias_no_queda_nada_a_medias(self):
        CanastaProducto.objects.filter(producto=self.producto).update(cantidad=50)
        with self.assertRaises(ValidationError):
            self.entregar()
        self.caro.refresh_from_db()
        self.assertEqual(self.caro.stock_actual, Decimal("10"))


class UnirClientes(ConCampana):
    def test_dos_fichas_de_la_misma_persona_quedan_con_una_inscripcion(self):
        from manada.identificar import unir_clientes
        otra = Cliente.objects.create(empresa=self.empresa, nombre="Maria P.", telefono="88885555")
        p1 = self.inscribir(self.maria)
        self.inscribir(otra)
        self.venta(self.caro, cliente=otra)
        unir_clientes(conservar=self.maria, absorber=otra, usuario=self.usuario)
        self.assertEqual(reglas.saldo(p1), 1 + 2)
        self.assertEqual(sum(f["numeros"] for f in sorteo.armar_lista(self.campana)), 3)


class LaNavidadQuedaListaParaActivar(BaseVentas):
    """17/11/2026: Oscar decidió los dos puntos abiertos de las bases y pidió
    dejar la campaña lista para activar, sin activarla."""

    def setUp(self):
        super().setUp()
        self.empresa.identificacion = "3-102-969361"
        self.empresa.save()

    def preparar(self):
        import importlib
        from django.apps import apps
        importlib.import_module("campanas.migrations.0002_navidad_2026_en_borrador").preparar(apps, None)

    def test_las_bases_ya_no_tienen_nada_por_definir(self):
        from core.tienda import DIRECCION_TIENDA
        from .plantillas import POR_DEFINIR, bases_borrador
        bases = bases_borrador(self.empresa)
        self.assertNotIn(POR_DEFINIR, bases)
        self.assertIn("No participan los dueños de AllPetcr.com (Oscar y Francisco); sus familiares sí", bases)
        self.assertIn("su nombre se publica en las redes sociales de AllPetcr.com", bases)
        self.assertIn("Al participar, la persona autoriza", bases)
        self.assertIn(DIRECCION_TIENDA, bases)

    def test_la_migracion_la_deja_en_borrador_y_se_puede_activar(self):
        self.preparar()
        c = Campana.objects.get(slug="navidad-2026")
        self.assertEqual(c.estado, Campana.Estado.BORRADOR)       # no la activa
        self.assertIsNone(reglas.vigente(self.empresa))
        Campana.objects.filter(pk=c.pk).update(inicio=timezone.now() - timedelta(days=3))
        reglas.activar(c, self.usuario)
        c.refresh_from_db()
        self.assertEqual(c.estado, Campana.Estado.ACTIVA)
        # El borrador se preparó días antes: empieza al activarse, no antes.
        self.assertGreater(c.inicio, timezone.now() - timedelta(minutes=1))

    def test_corrige_un_borrador_viejo_y_no_toca_una_ya_activa(self):
        from .plantillas import bases_borrador
        viejo = Campana.objects.create(
            empresa=self.empresa, slug="navidad-2026", nombre="Navidad", inicio=timezone.now(),
            cierre=timezone.now() + timedelta(days=30), sorteo_en=timezone.now() + timedelta(days=31),
            bases="3. Quién participa [POR DEFINIR: algo]")
        self.preparar()
        viejo.refresh_from_db()
        self.assertEqual(viejo.bases, bases_borrador(self.empresa))
        Campana.objects.filter(pk=viejo.pk).update(estado=Campana.Estado.ACTIVA, bases="Lo que el cliente aceptó")
        self.preparar()
        viejo.refresh_from_db()
        self.assertEqual(viejo.bases, "Lo que el cliente aceptó")
        self.assertEqual(Campana.objects.count(), 1)
