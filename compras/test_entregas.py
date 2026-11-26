"""Proveedores: cuándo llega un pedido y la carga desde Excel (26/11/2026).

Los datos son inventados: el Excel real de Oscar trae teléfonos, cuentas y
claves, y el repositorio es público."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Empresa

from . import entregas
from .models import Proveedor

MARTES = datetime(2026, 11, 24, 10, 0)          # 24/11/2026 fue martes


class Llegada(TestCase):
    def prov(self, **kw):
        return Proveedor(nombre="X", **kw)

    def test_sin_datos_no_se_sabe(self):
        self.assertIsNone(entregas.llegada(self.prov(), MARTES))

    def test_solo_entrega_los_viernes(self):
        self.assertEqual(entregas.llegada(self.prov(dias_entrega="4"), MARTES), date(2026, 11, 27))

    def test_pedir_el_dia_antes_y_antes_de_las_5(self):
        p = self.prov(dias_entrega="24", dias_minimos=1, hora_limite=time(17, 0))
        self.assertEqual(entregas.llegada(p, MARTES), date(2026, 11, 25))            # miércoles
        tarde = MARTES.replace(hour=18)
        self.assertEqual(entregas.llegada(p, tarde), date(2026, 11, 27))             # ya no llega el miércoles

    def test_dias_de_pedido(self):
        p = self.prov(dias_pedido="3", dias_entrega="4", dias_minimos=1)             # pide jueves, entrega viernes
        self.assertEqual(entregas.llegada(p, MARTES), date(2026, 11, 27))
        p.dias_pedido = "0"                                                          # pide lunes
        self.assertEqual(entregas.llegada(p, MARTES), date(2026, 12, 4))

    def test_72_horas(self):
        self.assertEqual(entregas.llegada(self.prov(dias_minimos=3), MARTES), date(2026, 11, 27))

    def test_sin_dias_de_entrega_no_cae_en_domingo(self):
        jueves = MARTES + timedelta(days=2)
        self.assertEqual(entregas.llegada(self.prov(dias_minimos=3), jueves), date(2026, 11, 30))   # lunes


class Horario(TestCase):
    def test_lo_que_dice_el_excel(self):
        f = entregas.interpretar_horario
        self.assertEqual(f("M y J Pedidos, se entrega los viernes solamente"),
                         {"dias_pedido": "", "dias_entrega": "4", "dias_minimos": None, "hora_limite": ""})
        self.assertEqual(f("Miercoles y Viernes. Pedir un día anterior antes de las 5pm"),
                         {"dias_pedido": "", "dias_entrega": "24", "dias_minimos": 1, "hora_limite": "17:00"})
        self.assertEqual(f("entregas max 72 h")["dias_minimos"], 3)
        self.assertEqual(f("dos días de anticipación")["dias_minimos"], 2)
        self.assertEqual(f("Pedidos lunes y jueves, entrega viernes")["dias_pedido"], "03")


def _excel():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "ACME"
    for fila in [("Celular ", 88887777), ("Contacto", "Ana"), ("Correo", None),
                 ("Cuentas", "BNCR", "CR00000000000000000000"), ("Nombre", "Acme SA"),
                 ("Horario de entrega", "Martes y viernes", "Pedir un día antes"),
                 ("Usuario", "tienda@ejemplo.com"), ("contraseña", "no-se-guarda-123"),
                 (None, "No acepta tarjeta")]:
        ws.append(list(fila))
    otra = wb.create_sheet("Nuevo Proveedor")
    otra.append(["Contacto", "Luis"])
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


class CargaDesdeExcel(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="AllPet Test")
        self.acme = Proveedor.objects.create(empresa=self.empresa, nombre="Distribuidora Acme", notas="Vieja nota")
        self.usuario = User.objects.create_user("g", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(self.usuario)

    def test_lee_sin_claves(self):
        hojas = entregas.leer_excel(BytesIO(_excel()))
        h = hojas[0]
        self.assertEqual(h["datos"]["telefono"], "8888-7777")
        self.assertEqual(h["datos"]["cuenta_bancaria"], "BNCR CR00000000000000000000")
        self.assertEqual(h["entregas"]["dias_entrega"], "14")
        self.assertEqual(h["omitidos"], ["Usuario", "contraseña"])
        self.assertNotIn("no-se-guarda-123", str(hojas))
        self.assertNotIn("tienda@ejemplo.com", str(hojas))
        self.assertEqual(entregas.adivinar_proveedor("ACME", [self.acme]), self.acme)

    def test_vista_previa_y_confirmar(self):
        r = self.client.post(reverse("compras:proveedores_importar"),
                             {"archivo": SimpleUploadedFile("entregas.xlsx", _excel())})
        self.assertContains(r, "Hoja «ACME»")
        self.assertContains(r, "No se cargan: Usuario, contraseña")
        self.assertNotContains(r, "no-se-guarda-123")
        self.assertEqual(Proveedor.objects.get(pk=self.acme.pk).contacto, "")      # nada guardado aún
        r = self.client.post(reverse("compras:proveedores_importar"), {
            "accion": "confirmar", "firma": r.context["firma"],
            "destino_0": str(self.acme.pk), "destino_1": "nuevo"})
        self.assertRedirects(r, reverse("compras:proveedores"))
        self.acme.refresh_from_db()
        self.assertEqual((self.acme.contacto, self.acme.razon_social, self.acme.dias_entrega, self.acme.dias_minimos),
                         ("Ana", "Acme SA", "14", 1))
        self.assertIn("Vieja nota", self.acme.notas)
        self.assertIn("No acepta tarjeta", self.acme.notas)
        self.assertTrue(Proveedor.objects.filter(empresa=self.empresa, nombre="Nuevo Proveedor", contacto="Luis").exists())

    def test_pantalla_y_editar(self):
        r = self.client.get(reverse("compras:proveedores"))
        self.assertContains(r, "Distribuidora Acme")
        self.assertContains(r, "Falta decir qué días entrega")
        p = f"p{self.acme.pk}"
        r = self.client.post(reverse("compras:proveedores"), {
            "proveedor": self.acme.pk, f"{p}-nombre": "Distribuidora Acme", f"{p}-contacto": "Ana",
            f"{p}-dias_entrega": ["1", "4"], f"{p}-dias_minimos": "1", f"{p}-hora_limite": "17:00",
            f"{p}-activo": "on"})
        self.assertEqual(r.status_code, 302)
        self.acme.refresh_from_db()
        self.assertEqual((self.acme.dias_entrega, self.acme.hora_limite), ("14", time(17, 0)))
        r = self.client.get(reverse("compras:proveedores"))
        self.assertContains(r, "Si se le pide hoy, llega el")

    def test_el_cajero_no_entra(self):
        from django.contrib.auth.models import Group
        cajero = User.objects.create_user("c", password="x", is_staff=True)
        cajero.groups.add(Group.objects.get_or_create(name="Cajero")[0])
        self.client.force_login(cajero)
        self.assertNotEqual(self.client.get(reverse("compras:proveedores")).status_code, 200)
