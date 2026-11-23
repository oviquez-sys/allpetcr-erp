"""Tareas del día (23/11/2026).

Lo que no se puede romper:
- una rutina da UNA tarea por día que aplica (nunca dos, aunque se abra el
  día dos veces), y ninguna en un día de tienda cerrada, en un día del plan
  que la excluye, fuera de su vigencia o en el futuro lejano;
- quién marcó y cuándo lo pone el sistema, no la pantalla;
- «Quedaron pendientes» muestra lo puntual que nadie marcó, no la rutina;
- solo se borra lo agregado a mano, y nadie ve ni marca tareas de otra empresa;
- el plan de Navidad se carga completo una sola vez.
"""
import importlib
from datetime import timedelta

from django.apps import apps as registro
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa
from core.roles import CAJERO

from . import plan_navidad_2026 as plan_datos
from . import servicios
from .models import Dia, Plan, Responsable, Rutina, Semana, Tarea


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.hoy = servicios.hoy()
        self.lunes = self.hoy - timedelta(days=self.hoy.weekday())
        self.oscar = User.objects.create_user("oscar", password="clave-test", is_staff=True, is_superuser=True)

    def rutina(self, clave="responder", **extra):
        datos = dict(empresa=self.empresa, clave=clave, titulo="Responder mensajes", dias="012345",
                     desde=self.lunes - timedelta(days=14))
        datos.update(extra)
        return Rutina.objects.create(**datos)

    def tarea(self, fecha=None, **extra):
        datos = dict(empresa=self.empresa, fecha=fecha or self.hoy, titulo="Publicar el reel C",
                     tipo=Tarea.Tipo.PUBLICACION)
        datos.update(extra)
        return Tarea.objects.create(**datos)

    def plan(self, **extra):
        datos = dict(empresa=self.empresa, clave="prueba", nombre="Plan de prueba",
                     inicio=self.lunes, fin=self.lunes + timedelta(days=13), hito="Sorteo",
                     hito_fecha=self.lunes + timedelta(days=13))
        datos.update(extra)
        return Plan.objects.create(**datos)


class Rutinas(Base):
    def test_una_tarea_por_dia_que_aplica_y_nunca_dos(self):
        r = self.rutina()
        servicios.asegurar_rutinas(self.empresa, self.lunes, self.lunes + timedelta(days=6))
        servicios.asegurar_rutinas(self.empresa, self.lunes, self.lunes + timedelta(days=6))
        fechas = list(Tarea.objects.filter(rutina=r).values_list("fecha", flat=True))
        self.assertEqual(len(fechas), 6, "de lunes a sábado, una vez cada día")
        self.assertNotIn(self.lunes + timedelta(days=6), fechas, "el domingo no aplica")

    def test_tienda_cerrada_y_rutina_excluida_no_crean_nada(self):
        r = self.rutina()
        otra = self.rutina(clave="post1h", titulo="Primera hora después de publicar")
        plan = self.plan()
        Dia.objects.create(plan=plan, fecha=self.lunes, tienda_cerrada=True)
        Dia.objects.create(plan=plan, fecha=self.lunes + timedelta(days=1), sin_rutinas=["post1h"])
        servicios.asegurar_rutinas(self.empresa, self.lunes, self.lunes + timedelta(days=1))
        self.assertFalse(Tarea.objects.filter(fecha=self.lunes).exists())
        martes = Tarea.objects.filter(fecha=self.lunes + timedelta(days=1))
        self.assertEqual(list(martes.values_list("rutina", flat=True)), [r.pk])
        self.assertFalse(Tarea.objects.filter(rutina=otra).exists())

    def test_respeta_la_vigencia_y_el_horizonte(self):
        self.rutina(desde=self.hoy, hasta=self.hoy + timedelta(days=2))
        servicios.asegurar_rutinas(self.empresa, self.hoy - timedelta(days=7), self.hoy + timedelta(days=9))
        for t in Tarea.objects.all():
            self.assertTrue(self.hoy <= t.fecha <= self.hoy + timedelta(days=2))
        lejos = self.hoy + timedelta(days=servicios.HORIZONTE_DIAS + 10)
        self.rutina(clave="lejana", desde=self.hoy, dias="0123456")
        servicios.asegurar_rutinas(self.empresa, lejos, lejos)
        self.assertFalse(Tarea.objects.filter(fecha=lejos).exists())

    def test_las_historias_del_dia_van_en_el_detalle(self):
        self.rutina(clave="historias-am", titulo="Subir 2 historias", detalle="El sorteo y «Pedí en línea».",
                    con_historias=True, dias="0123456")
        plan = self.plan()
        Dia.objects.create(plan=plan, fecha=self.hoy, historias="Detrás de cámaras")
        servicios.asegurar_rutinas(self.empresa, self.hoy, self.hoy)
        t = Tarea.objects.get(fecha=self.hoy)
        self.assertEqual(t.detalle, "El sorteo y «Pedí en línea». Hoy: Detrás de cámaras.")
        self.assertEqual(t.plan, plan)
        self.assertEqual(t.tipo, Tarea.Tipo.RUTINA)

    def test_cambiar_la_rutina_cambia_lo_pendiente_desde_hoy_y_no_lo_pasado(self):
        r = self.rutina(dias="0123456")
        servicios.asegurar_rutinas(self.empresa, self.hoy - timedelta(days=1), self.hoy + timedelta(days=1))
        marcada = Tarea.objects.get(rutina=r, fecha=self.hoy + timedelta(days=1))
        servicios.marcar(marcada, Tarea.Estado.HECHA, self.oscar)
        r.titulo = "Responder todo antes de las 10"
        r.save()
        servicios.refrescar_rutina(r)
        titulos = dict(Tarea.objects.filter(rutina=r).values_list("fecha", "titulo"))
        self.assertEqual(titulos[self.hoy - timedelta(days=1)], "Responder mensajes")
        self.assertEqual(titulos[self.hoy], "Responder todo antes de las 10")
        self.assertEqual(titulos[self.hoy + timedelta(days=1)], "Responder mensajes", "ya estaba marcada")


class Marcar(Base):
    def test_quien_y_cuando_los_pone_el_sistema(self):
        t = self.tarea()
        servicios.marcar(t, Tarea.Estado.HECHA, self.oscar)
        t.refresh_from_db()
        self.assertEqual((t.estado, t.marcada_por), (Tarea.Estado.HECHA, self.oscar))
        self.assertIsNotNone(t.marcada_en)
        servicios.marcar(t, Tarea.Estado.PENDIENTE, self.oscar)
        t.refresh_from_db()
        self.assertEqual((t.estado, t.marcada_por, t.marcada_en), (Tarea.Estado.PENDIENTE, None, None))

    def test_estado_desconocido_no_se_guarda(self):
        with self.assertRaises(ValueError):
            servicios.marcar(self.tarea(), "LISTO", self.oscar)


class Conteos(Base):
    def test_quedaron_pendientes_es_lo_puntual_sin_marcar(self):
        r = self.rutina(dias="0123456")
        ayer = self.hoy - timedelta(days=1)
        servicios.asegurar_rutinas(self.empresa, ayer, ayer)
        sin_marcar = self.tarea(fecha=ayer, titulo="Lanzar el anuncio 2")
        hecha = self.tarea(fecha=ayer, titulo="Publicar")
        servicios.marcar(hecha, Tarea.Estado.HECHA, self.oscar)
        no_se_hizo = self.tarea(fecha=ayer, titulo="Grupos de Facebook")
        servicios.marcar(no_se_hizo, Tarea.Estado.NO_SE_HIZO, self.oscar)
        self.tarea(fecha=self.hoy - timedelta(days=servicios.VENTANA_PENDIENTES + 1), titulo="Muy vieja")
        self.tarea(fecha=self.hoy, titulo="De hoy")
        self.assertEqual(list(servicios.pendientes_anteriores(self.empresa, self.hoy)), [sin_marcar])
        self.assertTrue(Tarea.objects.filter(rutina=r, fecha=ayer, estado=Tarea.Estado.PENDIENTE).exists())

    def test_el_filtro_por_persona_incluye_lo_de_los_dos(self):
        self.tarea(responsable=Responsable.OSCAR, titulo="De Oscar")
        self.tarea(responsable=Responsable.FRANCISCO, titulo="De Francisco")
        self.tarea(responsable=Responsable.LOS_DOS, titulo="De los dos")
        qs = servicios.filtrar_persona(Tarea.objects.filter(fecha=self.hoy), Responsable.FRANCISCO)
        self.assertEqual(sorted(qs.values_list("titulo", flat=True)), ["De Francisco", "De los dos"])
        self.assertEqual(servicios.persona_valida("XXX"), "")

    def test_conteo_por_dia(self):
        hecha = self.tarea()
        servicios.marcar(hecha, Tarea.Estado.HECHA, self.oscar)
        no = self.tarea()
        servicios.marcar(no, Tarea.Estado.NO_SE_HIZO, self.oscar)
        self.tarea()
        self.assertEqual(servicios.conteo_por_dia(self.empresa, self.hoy, self.hoy)[self.hoy],
                         {"total": 3, "hechas": 1, "no": 1})


class Pantalla(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.oscar)

    def test_muestra_el_dia_con_su_contexto(self):
        plan = self.plan()
        Semana.objects.create(plan=plan, nombre="Semana 1", titulo="AllPet también es tienda en línea",
                              inicio=self.lunes, fin=self.lunes + timedelta(days=6), meta="2 pedidos en línea")
        Dia.objects.create(plan=plan, fecha=self.hoy, etiqueta="Black Friday", claude="Diseña la imagen")
        self.rutina(dias="0123456", minimo=True)
        self.tarea(titulo="Publicar el reel «Así pedís»")
        r = self.client.get(reverse("tareas:dia"))
        self.assertEqual(r.status_code, 200)
        for texto in ("Publicar el reel «Así pedís»", "Responder mensajes", "Mínimo", "Black Friday",
                      "Claude prepara:", "AllPet también es tienda en línea", "Sorteo en", "Rutina diaria"):
            self.assertContains(r, texto, msg_prefix=texto)

    def test_una_fecha_mala_cae_en_hoy(self):
        r = self.client.get(reverse("tareas:dia"), {"fecha": "2026-13-45", "quien": "XXX"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["fecha"], self.hoy)
        self.assertEqual(r.context["persona"], "")

    def test_marcar_sin_javascript_vuelve_a_la_tarea(self):
        t = self.tarea()
        r = self.client.post(reverse("tareas:marcar", args=[t.pk]), {"estado": "HEC", "quien": "OSC"})
        self.assertRedirects(r, reverse("tareas:dia") + f"?fecha={t.fecha:%Y-%m-%d}&quien=OSC#t-{t.pk}",
                             fetch_redirect_response=False)
        t.refresh_from_db()
        self.assertEqual((t.estado, t.marcada_por), (Tarea.Estado.HECHA, self.oscar))

    def test_marcar_en_segundo_plano_responde_con_el_dia(self):
        t = self.tarea()
        self.tarea(titulo="Otra")
        r = self.client.post(reverse("tareas:marcar", args=[t.pk]), {"estado": "NOH"},
                             headers={"X-Requested-With": "fetch"})
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertEqual((datos["estado"], datos["estado_texto"], datos["quien"]), ("NOH", "No se hizo", "vos"))
        self.assertEqual(datos["dia"], {"total": 2, "hechas": 0, "no": 1})

    def test_un_estado_inventado_no_se_guarda(self):
        t = self.tarea()
        r = self.client.post(reverse("tareas:marcar", args=[t.pk]), {"estado": "LISTO"},
                             headers={"X-Requested-With": "fetch"})
        self.assertEqual(r.status_code, 400)
        t.refresh_from_db()
        self.assertEqual(t.estado, Tarea.Estado.PENDIENTE)

    def test_marcar_solo_por_post(self):
        t = self.tarea()
        self.assertEqual(self.client.get(reverse("tareas:marcar", args=[t.pk])).status_code, 405)

    def test_guardar_nota_y_quien_la_hace(self):
        t = self.tarea()
        self.client.post(reverse("tareas:guardar", args=[t.pk]),
                         {"nota": "  Se pasó al martes  ", "responsable": "FRA"})
        t.refresh_from_db()
        self.assertEqual((t.nota, t.responsable), ("Se pasó al martes", Responsable.FRANCISCO))

    def test_agregar_y_borrar_lo_agregado_a_mano(self):
        self.client.post(reverse("tareas:agregar"),
                         {"fecha": f"{self.hoy:%Y-%m-%d}", "titulo": "Llamar al proveedor", "responsable": "OSC"})
        nueva = Tarea.objects.get(titulo="Llamar al proveedor")
        self.assertTrue(nueva.a_mano)
        self.assertEqual((nueva.creada_por, nueva.responsable), (self.oscar, Responsable.OSCAR))
        self.client.post(reverse("tareas:borrar", args=[nueva.pk]))
        self.assertFalse(Tarea.objects.filter(pk=nueva.pk).exists())

    def test_agregar_sin_titulo_no_crea_nada(self):
        self.client.post(reverse("tareas:agregar"), {"fecha": f"{self.hoy:%Y-%m-%d}", "titulo": "   "})
        self.assertFalse(Tarea.objects.exists())

    def test_lo_del_plan_no_se_borra(self):
        t = self.tarea(clave="1124-pub")
        self.client.post(reverse("tareas:borrar", args=[t.pk]))
        self.assertTrue(Tarea.objects.filter(pk=t.pk).exists())

    def test_no_se_ve_ni_se_marca_lo_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre="OTRA")
        ajena = Tarea.objects.create(empresa=otra, fecha=self.hoy, titulo="De otra empresa")
        r = self.client.post(reverse("tareas:marcar", args=[ajena.pk]), {"estado": "HEC"})
        self.assertEqual(r.status_code, 404)
        self.assertNotContains(self.client.get(reverse("tareas:dia")), "De otra empresa")


class Permisos(Base):
    def test_el_cajero_entra_y_marca(self):
        cajero = User.objects.create_user("cajero", password="clave-test", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name=CAJERO)[0])
        self.client.force_login(cajero)
        t = self.tarea()
        self.assertEqual(self.client.get(reverse("tareas:dia")).status_code, 200)
        self.client.post(reverse("tareas:marcar", args=[t.pk]), {"estado": "HEC"})
        t.refresh_from_db()
        self.assertEqual(t.marcada_por, cajero)

    def test_el_cajero_no_borra_lo_que_agregó_otro(self):
        cajero = User.objects.create_user("cajero", password="clave-test", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name=CAJERO)[0])
        t = self.tarea(a_mano=True, creada_por=self.oscar)
        self.client.force_login(cajero)
        self.client.post(reverse("tareas:borrar", args=[t.pk]))
        self.assertTrue(Tarea.objects.filter(pk=t.pk).exists())

    def test_sin_rol_no_entra(self):
        sin_rol = User.objects.create_user("visita", password="clave-test", is_staff=True)
        self.client.force_login(sin_rol)
        r = self.client.get(reverse("tareas:dia"))
        self.assertRedirects(r, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_sin_sesion_va_al_login(self):
        r = self.client.get(reverse("tareas:dia"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r["Location"])


class PlanDeNavidad(TestCase):
    """El plan se carga completo, una vez, y sus datos son coherentes."""

    def cargar(self):
        migracion = importlib.import_module("tareas.migrations.0002_plan_navidad_2026")
        migracion.cargar(registro, None)

    def test_se_carga_completo_y_una_sola_vez(self):
        Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cargar()
        self.cargar()
        self.assertEqual(Plan.objects.count(), 1)
        self.assertEqual(Semana.objects.count(), 5)
        self.assertEqual(Dia.objects.count(), 32)
        self.assertEqual(Rutina.objects.count(), 8)
        self.assertEqual(Tarea.objects.count(), sum(len(d["tareas"]) for d in plan_datos.DIAS))
        self.assertTrue(Dia.objects.get(fecha="2026-11-29").tienda_cerrada)
        self.assertEqual(Dia.objects.get(fecha="2026-11-23").sin_rutinas, ["post1h"])

    def test_sin_empresa_no_hace_nada(self):
        self.cargar()
        self.assertFalse(Plan.objects.exists())

    def test_los_datos_del_plan_son_coherentes(self):
        claves = set()
        inicio, fin = plan_datos.INICIO, plan_datos.FIN
        for d in plan_datos.DIAS:
            self.assertTrue(inicio <= d["fecha"] <= fin, d["fecha"])
            for t in d["tareas"]:
                self.assertNotIn(t["clave"], claves, t["clave"])
                claves.add(t["clave"])
                self.assertIn(t["responsable"], Responsable.values, t["clave"])
                self.assertIn(t["tipo"], Tarea.Tipo.values, t["clave"])
                self.assertTrue(t["titulo"], t["clave"])
        for r in plan_datos.RUTINAS:
            self.assertTrue(set(r["dias"]) <= set("0123456"), r["clave"])
            self.assertIn(r["responsable"], Responsable.values, r["clave"])
