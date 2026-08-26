"""El índice de /admin/ muestra el resumen del mes, y sólo al gerente.

Lo que se protege acá es un riesgo de PERMISOS, no de presentación.

El panel de administración exige `is_staff`. Ser gerente es otra cosa: se
define por grupo (core/roles.py). Un cajero con `is_staff` para tocar alguna
tabla entra al admin igual. En el Inicio, la ganancia y el margen del mes
estaban detrás de `es_gerente`; al mover ese bloque a /admin/ era fácil que
quedaran detrás de `is_staff` sin que nadie lo notara — un rediseño que amplía
permisos de callado.

También se verifica que el admin siga abriendo aunque el cálculo falle. Un
indicador roto no puede dejar sin panel de administración a nadie: sería
cambiar una comodidad por una avería.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import Empresa, Sucursal
from core.roles import CAJERO


class IndiceAdminConIndicadores(TestCase):

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test", regimen="RTS")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Principal")
        self.gerente = User.objects.create_user(
            "jefe", password="x", is_staff=True, is_superuser=True
        )
        self.cajero = User.objects.create_user("caja1", password="x", is_staff=True)
        grupo, _ = Group.objects.get_or_create(name=CAJERO)
        self.cajero.groups.add(grupo)
        # Permiso mínimo para que el cajero pueda entrar al admin, que es
        # justo el escenario que hace peligroso el cambio.
        from django.contrib.auth.models import Permission
        self.cajero.user_permissions.add(
            Permission.objects.get(codename="view_producto")
        )

    def test_el_gerente_ve_el_resumen_del_mes(self):
        self.client.force_login(self.gerente)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Resumen del mes")
        self.assertContains(r, "Ganancia del mes")
        self.assertTrue(r.context.get("ax_indicadores"))

    def test_el_gerente_ve_las_herramientas_movidas_desde_el_inicio(self):
        self.client.force_login(self.gerente)
        r = self.client.get("/admin/")
        self.assertContains(r, "Centro de reportes")
        self.assertContains(r, "Códigos de barras")

    def test_el_cajero_ni_siquiera_llega_al_indice(self):
        """Primera capa: el middleware cierra /admin/ a quien no sea gerente.

        Verificado al escribir esto: `core/middleware.py` ya redirige al
        Inicio a cualquiera que no sea gerente, así que el cajero no llega al
        índice aunque tenga `is_staff` y permisos sobre una tabla.
        """
        self.client.force_login(self.cajero)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)

    def test_el_contexto_viene_vacio_para_quien_no_es_gerente(self):
        """Segunda capa, dentro del índice mismo.

        Es redundante con el middleware A PROPÓSITO. La condición de "quién
        puede entrar al admin" es una política que puede cambiar (hoy podría
        querer entrar el Contador para ver la contabilidad). Si cambia, la
        ganancia y el margen del mes no deberían viajar de regalo con ese
        cambio: quien decide mostrarlos es este chequeo, no la ruta.

        Se prueba la función directamente porque el middleware, con razón, no
        deja llegar una petición real hasta acá.
        """
        from core.admin_site import _contexto_administrativo

        peticion = mock.Mock()
        peticion.user = self.cajero
        self.assertEqual(_contexto_administrativo(peticion), {})

    def test_el_admin_abre_aunque_los_indicadores_fallen(self):
        """Un indicador roto no puede tumbar el panel de administración."""
        self.client.force_login(self.gerente)
        with mock.patch("core.dashboard.indicadores", side_effect=RuntimeError("boom")):
            r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context.get("ax_indicadores"))
        # Las tablas de siempre siguen ahí.
        self.assertContains(r, "Tablas del sistema")

    def test_las_tablas_del_admin_siguen_apareciendo(self):
        """La envoltura del índice no puede romper el registro de modelos."""
        self.client.force_login(self.gerente)
        r = self.client.get("/admin/")
        self.assertContains(r, "Operación diaria")
        self.assertIn("app_list", r.context)
        self.assertTrue(r.context["app_list"], "se perdió el listado de apps")

    def test_instalar_dos_veces_no_apila_capas(self):
        """`ready()` puede correr más de una vez (autoreload). Envolver la
        vista ya envuelta dejaría capas apiladas."""
        from django.contrib import admin

        from core import admin_site

        antes = admin.site.index
        admin_site.instalar()
        self.assertIs(admin.site.index, antes)
