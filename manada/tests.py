"""Pruebas de la manada AllPetcr (13/10/2026).

Lo que no se puede romper: un cupón por persona, un solo uso, que se queme en
la misma transacción que la venta, que el código no salga de la API sin un
correo verificado, y que las mascotas se cuenten una sola vez.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from ventas.models import Cliente
from ventas.services import anular_factura
from ventas.test_auditoria_2026_09 import Base

from .models import Cupon, Mascota, PerfilManada, Regalia
from .services import (cupon_para_venta, normalizar_codigo, registrar_mascotas,
                       registrar_miembro)


class ConRegalia(Base):
    def setUp(self):
        super().setUp()
        self.regalia = Regalia.objects.create(empresa=self.empresa, porcentaje=Decimal("10"),
                                              texto_cliente="10 % de descuento en tu primera compra")

    def registrar(self, email="ana@gmail.com", **extra):
        datos = {"empresa": self.empresa, "email": email, "nombre": "Ana Pérez", "verificado": True}
        datos.update(extra)
        return registrar_miembro(**datos)


class Registro(ConRegalia):
    def test_crea_cliente_perfil_y_cupon(self):
        r = self.registrar(telefono="8888-1234", acepta_promociones=True, fuente="qr-tienda")
        self.assertTrue(r.cliente_nuevo)
        self.assertTrue(r.cupon_nuevo)
        self.assertEqual(r.cliente.email, "ana@gmail.com")
        self.assertEqual(r.cliente.telefono, "88881234")
        self.assertEqual(r.cupon.porcentaje, Decimal("10"))
        self.assertTrue(r.cupon.codigo.startswith("AP-"))
        self.assertTrue(r.perfil.acepta_promociones)
        self.assertEqual(r.perfil.fuente, "qr-tienda")
        self.assertTrue(r.perfil.token_mascotas)

    def test_registrarse_dos_veces_no_da_otro_cupon(self):
        primero = self.registrar()
        segundo = self.registrar(email="ANA@gmail.com ")
        self.assertEqual(primero.cupon.pk, segundo.cupon.pk)
        self.assertFalse(segundo.cupon_nuevo)
        self.assertFalse(segundo.cliente_nuevo)
        self.assertEqual(Cupon.objects.count(), 1)
        self.assertEqual(Cliente.objects.filter(email__iexact="ana@gmail.com").count(), 1)

    def test_la_misma_cuenta_de_google_con_otro_correo_no_da_otro_cupon(self):
        self.registrar(google_sub="123456")
        otro = self.registrar(email="ana.nueva@gmail.com", google_sub="123456")
        self.assertFalse(otro.cupon_nuevo)
        self.assertEqual(Cupon.objects.count(), 1)

    def test_usa_el_cliente_que_ya_existia_en_caja(self):
        viejo = Cliente.objects.create(empresa=self.empresa, nombre="Ana P. (caja)", email="ana@gmail.com")
        r = self.registrar()
        self.assertEqual(r.cliente.pk, viejo.pk)
        self.assertEqual(r.cliente.nombre, "Ana P. (caja)")   # no pisa lo que escribió el cajero

    def test_sin_regalia_activa_se_registra_pero_sin_cupon(self):
        self.regalia.activa = False
        self.regalia.save()
        r = self.registrar()
        self.assertIsNone(r.cupon)
        self.assertTrue(PerfilManada.objects.filter(cliente=r.cliente).exists())

    def test_cambiar_la_regalia_no_toca_los_cupones_ya_entregados(self):
        r = self.registrar()
        self.regalia.porcentaje = Decimal("20")
        self.regalia.save()
        r.cupon.refresh_from_db()
        self.assertEqual(r.cupon.porcentaje, Decimal("10"))
        otra = self.registrar(email="luis@gmail.com")
        self.assertEqual(otra.cupon.porcentaje, Decimal("20"))

    def test_vigencia(self):
        self.regalia.dias_vigencia = 30
        self.regalia.save()
        r = self.registrar()
        self.assertEqual(r.cupon.vence_en, timezone.localdate() + timedelta(days=30))

    def test_correo_invalido(self):
        with self.assertRaises(ValidationError):
            self.registrar(email="no-es-correo")

    def test_whatsapp_invalido(self):
        with self.assertRaises(ValidationError):
            self.registrar(telefono="123")


class PorTelefono(ConRegalia):
    def test_el_mismo_numero_escrito_distinto_es_la_misma_persona(self):
        a = registrar_miembro(empresa=self.empresa, nombre="Rosa", telefono="8888-1234")
        b = registrar_miembro(empresa=self.empresa, nombre="Rosa", telefono="+506 8888 1234")
        self.assertEqual(a.cliente.pk, b.cliente.pk)
        self.assertFalse(b.cupon_nuevo)
        self.assertFalse(b.perfil_nuevo)

    def test_usa_el_cliente_de_caja_con_ese_telefono(self):
        viejo = Cliente.objects.create(empresa=self.empresa, nombre="Rosa (caja)", telefono="8888-1234")
        r = registrar_miembro(empresa=self.empresa, nombre="Rosa", telefono="88881234")
        self.assertEqual(r.cliente.pk, viejo.pk)

    def test_la_caja_encuentra_el_cupon_por_el_numero(self):
        r = registrar_miembro(empresa=self.empresa, nombre="Rosa", telefono="8888-1234")
        self.assertEqual(cupon_para_venta(self.empresa, "8888 1234").pk, r.cupon.pk)
        f = self.vender(cupon="88881234")
        self.assertEqual(f.total, Decimal("4770.00"))
        with self.assertRaisesMessage(ValidationError, "no tiene cupón"):
            cupon_para_venta(self.empresa, "7777-0000")

    def test_alguien_ajeno_no_cambia_las_preferencias(self):
        registrar_miembro(empresa=self.empresa, nombre="Rosa", telefono="88881234", acepta_promociones=True)
        registrar_miembro(empresa=self.empresa, nombre="X", telefono="88881234", acepta_promociones=False)
        self.assertTrue(PerfilManada.objects.get().acepta_promociones)


class UnirEnCaja(ConRegalia):
    def setUp(self):
        super().setUp()
        cajero = User.objects.create_user("maria", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(cajero)

    def post(self, **datos):
        base = {"nombre": "Doña Rosa", "telefono": "8888-1234", "acepto": True}
        base.update(datos)
        return self.client.post(reverse("ventas:manada_rapido"), json.dumps(base), content_type="application/json")

    def test_une_y_devuelve_el_cupon(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["cupon"].startswith("AP-"))
        self.assertEqual(PerfilManada.objects.get().origen, PerfilManada.Origen.CAJA)

    def test_sin_aceptar_no_guarda_nada(self):
        r = self.post(acepto=False)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PerfilManada.objects.exists())

    def test_la_caja_tiene_el_boton(self):
        self.assertContains(self.client.get(reverse("ventas:pos")), 'id="btnManada"')


class Codigos(ConRegalia):
    def test_normaliza_lo_que_teclea_el_cajero(self):
        self.assertEqual(normalizar_codigo(" ap-7k3p9q "), "AP-7K3P9Q")
        self.assertEqual(normalizar_codigo("ap7k3p9q"), "AP-7K3P9Q")
        self.assertEqual(normalizar_codigo("7k3p9q"), "AP-7K3P9Q")
        self.assertEqual(normalizar_codigo("APX2K9"), "AP-APX2K9")   # 6 caracteres: AP es parte del código
        self.assertEqual(normalizar_codigo(""), "")

    def test_el_codigo_no_tiene_caracteres_ambiguos(self):
        for i in range(30):
            c = self.registrar(email=f"x{i}@gmail.com").cupon.codigo
            self.assertFalse(set(c[3:]) & set("01OIL"), c)


class CuponEnCaja(ConRegalia):
    def setUp(self):
        super().setUp()
        self.cupon = self.registrar().cupon

    def test_aplica_el_porcentaje_y_queda_usado(self):
        f = self.vender(cupon=self.cupon.codigo.lower())
        self.assertEqual(f.total, Decimal("4770.00"))           # 5300 − 10 %
        self.assertEqual(f.descuento, Decimal("530.00"))
        self.cupon.refresh_from_db()
        self.assertEqual(self.cupon.factura, f)
        self.assertIsNotNone(self.cupon.usado_en)
        self.assertEqual(f.cliente, self.cupon.cliente)          # la compra queda a nombre del miembro

    def test_no_sirve_dos_veces(self):
        self.vender(cupon=self.cupon.codigo)
        with self.assertRaisesMessage(ValidationError, "ya se usó"):
            self.vender(cupon=self.cupon.codigo)

    def test_si_la_venta_falla_el_cupon_sigue_disponible(self):
        with self.assertRaises(ValidationError):
            self.vender(cupon=self.cupon.codigo, cantidad=999)    # no hay stock
        self.cupon.refresh_from_db()
        self.assertIsNone(self.cupon.usado_en)

    def test_no_se_suma_al_descuento_del_cajero(self):
        f = self.registrar_venta_con_descuento(5)
        self.assertEqual(f.lineas.get().descuento_pct, Decimal("10"))   # gana el mayor
        cupon2 = self.registrar(email="luis@gmail.com").cupon
        f2 = self.registrar_venta_con_descuento(12, cupon=cupon2.codigo)
        self.assertEqual(f2.lineas.get().descuento_pct, Decimal("12"))

    def registrar_venta_con_descuento(self, pct, cupon=None):
        from ventas.services import registrar_venta
        return registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                               lineas=[{"producto_id": self.producto.pk, "cantidad": 1, "descuento_pct": pct}],
                               cupon=cupon or self.cupon.codigo)

    def test_un_cupon_mayor_al_tope_del_cajero_igual_pasa(self):
        # El 15 % de tope es para los descuentos que decide el cajero; la
        # regalía la decidió el negocio.
        self.regalia.porcentaje = Decimal("20")
        self.regalia.save()
        cupon = self.registrar(email="luis@gmail.com").cupon
        f = self.vender(cupon=cupon.codigo, permitir_descuento_alto=False)
        self.assertEqual(f.lineas.get().descuento_pct, Decimal("20"))

    def test_vencido(self):
        Cupon.objects.filter(pk=self.cupon.pk).update(vence_en=timezone.localdate() - timedelta(days=1))
        with self.assertRaisesMessage(ValidationError, "venció"):
            self.vender(cupon=self.cupon.codigo)

    def test_inexistente(self):
        with self.assertRaisesMessage(ValidationError, "no existe"):
            self.vender(cupon="AP-ZZZZZZ")

    def test_anular_la_venta_libera_el_cupon(self):
        f = self.vender(cupon=self.cupon.codigo)
        anular_factura(factura=f, motivo="error", usuario=self.usuario)
        self.cupon.refresh_from_db()
        self.assertIsNone(self.cupon.usado_en)
        self.assertIsNone(self.cupon.factura)
        self.vender(cupon=self.cupon.codigo)                     # y vuelve a servir

    def test_una_venta_solo_de_regalias_no_quema_el_cupon(self):
        from ventas.services import registrar_venta
        with self.assertRaisesMessage(ValidationError, "sin productos cobrados"):
            registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                            lineas=[{"producto_id": self.producto.pk, "cantidad": 1,
                                     "es_regalia": True, "motivo": "promo"}],
                            cupon=self.cupon.codigo, permitir_regalia_alta=True)
        self.cupon.refresh_from_db()
        self.assertIsNone(self.cupon.usado_en)


class CuponDesdeElPOS(ConRegalia):
    """La pantalla de caja: revisar el cupón antes de cobrar y cobrar con él."""

    def setUp(self):
        super().setUp()
        self.cupon = self.registrar().cupon
        self.cajero = User.objects.create_user("maria", password="c", is_staff=True)
        self.cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(self.cajero)

    def test_revisar_no_lo_quema(self):
        r = self.client.get(reverse("ventas:cupon"), {"codigo": self.cupon.codigo.lower()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["porcentaje"], 10.0)
        self.assertEqual(r.json()["cliente"]["nombre"], "Ana Pérez")
        self.cupon.refresh_from_db()
        self.assertIsNone(self.cupon.usado_en)

    def test_revisar_uno_usado_da_error(self):
        self.vender(cupon=self.cupon.codigo)
        r = self.client.get(reverse("ventas:cupon"), {"codigo": self.cupon.codigo})
        self.assertEqual(r.status_code, 400)
        self.assertIn("ya se usó", r.json()["error"])

    def test_cobrar_con_cupon(self):
        r = self.client.post(reverse("ventas:vender"), json.dumps({
            "medio_pago": "TAR", "lineas": [{"producto_id": self.producto.pk, "cantidad": 1}],
            "clave": "k1", "cupon": self.cupon.codigo,
        }), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["total"], 4770.0)
        self.assertEqual(r.json()["correo_cliente"], "ana@gmail.com")

    def test_la_pantalla_trae_la_casilla(self):
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, 'id="cuponCodigo"')


class Mascotas(ConRegalia):
    def setUp(self):
        super().setUp()
        self.r = self.registrar()

    def test_se_guardan_una_sola_vez(self):
        registrar_mascotas(token=self.r.perfil.token_mascotas, mascotas=[
            {"nombre": "Cookie", "especie": "PER", "raza": "Goldendoodle", "edad_anios": 2,
             "edad_meses": 3, "peso_kg": "12,5"},
            {"nombre": "Michi", "especie": "GAT"},
        ])
        self.assertEqual(Mascota.objects.filter(cliente=self.r.cliente).count(), 2)
        cookie = Mascota.objects.get(nombre="Cookie")
        self.assertEqual(cookie.peso_kg, Decimal("12.50"))
        self.assertEqual(cookie.edad_texto, "2 años y 3 meses")
        with self.assertRaisesMessage(ValidationError, "ya se usó"):
            registrar_mascotas(token=self.r.perfil.token_mascotas, mascotas=[{"nombre": "X", "especie": "PER"}])

    def test_foto_se_achica_y_pierde_los_datos_de_la_camara(self):
        import base64, io
        from PIL import Image
        crudo = io.BytesIO()
        exif = Image.Exif()
        exif[0x010F] = "MarcaDeCamara"
        Image.new("RGB", (3000, 2000), (200, 150, 60)).save(crudo, "JPEG", exif=exif)
        dato = "data:image/jpeg;base64," + base64.b64encode(crudo.getvalue()).decode()
        with self.settings(MEDIA_ROOT=self._tmp()):
            registrar_mascotas(token=self.r.perfil.token_mascotas,
                               mascotas=[{"nombre": "Cookie", "especie": "PER", "foto": dato}])
            m = Mascota.objects.get(nombre="Cookie")
            with m.foto.open("rb") as f:
                guardada = Image.open(f)
                guardada.load()
            self.assertEqual(max(guardada.size), 1200)
            self.assertEqual(len(guardada.getexif()), 0)

    def test_foto_que_no_es_imagen(self):
        import base64
        with self.assertRaisesMessage(ValidationError, "no se pudo leer"):
            registrar_mascotas(token=self.r.perfil.token_mascotas, mascotas=[
                {"nombre": "Cookie", "especie": "PER", "foto": base64.b64encode(b"no soy foto").decode()}])
        self.assertEqual(Mascota.objects.count(), 0)

    def _tmp(self):
        import shutil, tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_validaciones(self):
        token = self.r.perfil.token_mascotas
        for malas, texto in [
            ([], "al menos una"),
            ([{"nombre": "", "especie": "PER"}], "Falta el nombre"),
            ([{"nombre": "Cookie", "especie": "PEZ"}], "perro, gato u otro"),
            ([{"nombre": "Cookie", "especie": "PER", "peso_kg": "mucho"}], "número"),
            ([{"nombre": "Cookie", "especie": "PER", "edad_meses": 14}], "meses"),
            ([{"nombre": str(i), "especie": "PER"} for i in range(6)], "hasta 5"),
        ]:
            with self.assertRaisesMessage(ValidationError, texto):
                registrar_mascotas(token=token, mascotas=malas)
        self.assertEqual(Mascota.objects.count(), 0)   # nada a medias


class APIManada(ConRegalia):
    def setUp(self):
        super().setUp()
        usuario_sitio = User.objects.create_user("sitio-web")
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=usuario_sitio).key}")

    def post(self, **datos):
        base = {"email": "ana@gmail.com", "nombre": "Ana Pérez", "acepta_promociones": True}
        base.update(datos)
        return self.api.post(reverse("api:manada_registro"), base, format="json")

    def test_requiere_token(self):
        r = APIClient().post(reverse("api:manada_registro"), {"email": "a@b.com"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_verificado_por_google_devuelve_el_codigo(self):
        r = self.post(verificado=True, google_sub="g-1")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["cupon"]["codigo"].startswith("AP-"))
        self.assertEqual(r.data["cupon"]["porcentaje"], "10")
        self.assertTrue(r.data["token_mascotas"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(r.data["cupon"]["codigo"], mail.outbox[0].body)

    def test_formulario_muestra_el_codigo_nuevo_en_pantalla(self):
        # 14/10/2026: mucha gente no se acuerda del correo; el código sale
        # en pantalla apenas se crea, y también va al correo si lo dio.
        r = self.post()
        self.assertEqual(r.status_code, 201)
        codigo = Cupon.objects.get().codigo
        self.assertEqual(r.data["cupon"]["codigo"], codigo)
        self.assertTrue(r.data["token_mascotas"])
        self.assertIn(codigo, mail.outbox[0].body)

    def test_un_registro_repetido_no_muestra_el_codigo_ajeno(self):
        self.post()
        r = self.post(nombre="Otro")
        self.assertNotIn("codigo", r.data["cupon"])
        self.assertNotIn("token_mascotas", r.data)
        self.assertTrue(r.data["ya_era_miembro"])

    def test_solo_con_whatsapp(self):
        r = self.api.post(reverse("api:manada_registro"),
                          {"nombre": "Doña Rosa", "telefono": "8888-1234"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["cupon"]["codigo"].startswith("AP-"))
        self.assertFalse(r.data["correo_enviado"])
        self.assertEqual(Cliente.objects.get(nombre="Doña Rosa").telefono, "88881234")

    def test_sin_whatsapp_ni_correo(self):
        r = self.api.post(reverse("api:manada_registro"), {"nombre": "X"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_sin_verificar_no_se_acepta_google_sub(self):
        # Si el sitio no verificó, un google_sub suelto no puede "adueñarse"
        # de la cuenta de otro.
        self.post(google_sub="g-ajeno")
        self.assertIsNone(PerfilManada.objects.get().google_sub)

    def test_registro_repetido_responde_200_y_reenvia(self):
        self.post()
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["cupon"]["nuevo"])
        self.assertEqual(len(mail.outbox), 2)

    def test_mascotas_por_api(self):
        token = self.post(verificado=True).data["token_mascotas"]
        url = reverse("api:manada_mascotas")
        self.assertTrue(self.api.get(url, {"t": token}).data["valido"])
        r = self.api.post(url, {"token": token, "mascotas": [{"nombre": "Cookie", "especie": "PER"}]},
                          format="json")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(self.api.get(url, {"t": token}).data["valido"])
        r = self.api.post(url, {"token": token, "mascotas": [{"nombre": "Otra", "especie": "PER"}]},
                          format="json")
        self.assertEqual(r.status_code, 400)

    def test_regalia_vigente(self):
        r = self.api.get(reverse("api:manada_regalia"))
        self.assertEqual(r.data, {"activa": True, "porcentaje": "10", "correo_activo": True,
                                  "texto": "10 % de descuento en tu primera compra", "dias_vigencia": 0})
        self.regalia.activa = False
        self.regalia.save()
        self.assertEqual(self.api.get(reverse("api:manada_regalia")).data, {"activa": False, "correo_activo": True})

    def test_sin_servicio_de_correo_no_dice_que_lo_mando(self):
        from django.test import override_settings
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"):
            r = self.post()
            self.assertFalse(r.data["correo_enviado"])
            self.assertFalse(self.api.get(reverse("api:manada_regalia")).data["correo_activo"])

    def test_datos_malos(self):
        self.assertEqual(self.post(email="nada").status_code, 400)


class AdminManada(ConRegalia):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)   # superusuario = gerente

    def test_activar_una_regalia_apaga_la_anterior(self):
        r = self.client.post(reverse("admin:manada_regalia_add"), {
            "nombre": "Navidad", "porcentaje": "15", "texto_cliente": "15 % en tu primera compra",
            "dias_vigencia": "0", "activa": "on",
        })
        self.assertEqual(r.status_code, 302, r.content[:2000])
        self.assertEqual(Regalia.objects.filter(activa=True).count(), 1)
        self.assertEqual(Regalia.vigente(self.empresa).nombre, "Navidad")

    def test_exportar_excel(self):
        self.registrar()
        r = self.client.post(reverse("admin:manada_perfilmanada_changelist"), {
            "action": "exportar_excel", "_selected_action": [PerfilManada.objects.get().pk],
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])

    def test_el_inicio_tiene_la_manada_y_no_cargar_excel(self):
        r = self.client.get("/")
        self.assertContains(r, reverse("admin:manada_perfilmanada_changelist"))
        self.assertContains(r, "Recibir mercadería")
        self.assertNotContains(r, ">Cargar Excel<")

    def test_pantallas_del_admin_abren(self):
        self.registrar()
        for nombre in ["manada_regalia", "manada_perfilmanada", "manada_cupon", "manada_mascota"]:
            r = self.client.get(reverse(f"admin:{nombre}_changelist"))
            self.assertEqual(r.status_code, 200, nombre)
