"""El cupón de bienvenida no rebaja el alimento (05/11/2026, pedido de Oscar).

Lo que no se puede romper: el alimento se cobra entero aunque venga cupón; el
resto de la venta sí lleva el descuento; si la compra fue solo de alimento el
cupón NO se gasta; y los cupones entregados antes del cambio se respetan como
se ofrecieron (sin la condición).
"""
import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.urls import reverse

from catalogo.models import Categoria, Producto
from inventario.services import registrar_movimiento
from ventas.services import registrar_venta

from .exclusiones import texto_con_condicion
from .models import Cupon
from .tests import ConRegalia


class CuponSinAlimentos(ConRegalia):
    def setUp(self):
        super().setUp()
        raiz = Categoria.objects.create(nombre="Alimento")
        sub = Categoria.objects.create(nombre="Alimento seco perro", padre=raiz)
        self.alimento = Producto.objects.create(
            empresa=self.empresa, sku="A1", nombre="Balance Adulto 15 kg", precio_venta=Decimal("20000"),
            impuesto=self.iva, cabys="2331000000000", categoria=sub,
        )
        registrar_movimiento(producto=self.alimento, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("10"), costo_unitario=Decimal("15000"), referencia="INI")
        self.cupon = self.registrar().cupon

    def venta(self, *productos, cupon=None):
        return registrar_venta(sesion_caja=self.sesion, medio_pago="EFE", usuario=self.usuario,
                               lineas=[{"producto_id": p.pk, "cantidad": 1} for p in productos],
                               cupon=cupon or self.cupon.codigo)

    def test_el_cupon_nuevo_trae_la_condicion(self):
        self.assertTrue(self.cupon.excluye_alimentos)
        self.assertIn("no aplica a alimentos", self.cupon.descripcion)

    def test_rebaja_el_juguete_y_no_el_alimento(self):
        f = self.venta(self.producto, self.alimento)
        lineas = {l.producto_id: l for l in f.lineas.all()}
        self.assertEqual(lineas[self.producto.pk].descuento_pct, Decimal("10"))
        self.assertEqual(lineas[self.alimento.pk].descuento_pct, Decimal("0"))
        self.assertEqual(f.total, Decimal("4770.00") + Decimal("20000.00"))
        self.cupon.refresh_from_db()
        self.assertEqual(self.cupon.factura, f)                     # se usó: rebajó el juguete

    def test_solo_alimento_no_gasta_el_cupon(self):
        f = self.venta(self.alimento)
        self.assertEqual(f.total, Decimal("20000.00"))
        self.assertEqual(f.cliente, self.cupon.cliente)              # igual queda a su nombre
        self.cupon.refresh_from_db()
        self.assertIsNone(self.cupon.usado_en)
        self.venta(self.producto)                                     # y le sirve otro día

    def test_ficha_de_alimento_cuenta_aunque_este_mal_categorizado(self):
        from catalogo.models import FichaAlimento
        ficha = FichaAlimento.objects.create(clave="balance-lata", marca="Balance", nombre="Lata",
                                             especie="perro", tipo="humedo")
        self.producto.ficha_alimento = ficha
        self.producto.save(update_fields=["ficha_alimento"])
        f = self.venta(self.producto, self.alimento)
        self.assertTrue(all(l.descuento_pct == 0 for l in f.lineas.all()))

    def test_un_cupon_viejo_se_respeta_como_se_ofrecio(self):
        Cupon.objects.filter(pk=self.cupon.pk).update(excluye_alimentos=False)
        f = self.venta(self.alimento)
        self.assertEqual(f.lineas.get().descuento_pct, Decimal("10"))

    def test_regalia_sin_la_condicion(self):
        self.regalia.excluye_alimentos = False
        self.regalia.save()
        c = self.registrar(email="luis@gmail.com").cupon
        self.assertFalse(c.excluye_alimentos)
        self.assertNotIn("alimento", c.descripcion)

    def test_texto(self):
        self.assertEqual(texto_con_condicion("10 % en tu primera compra", True),
                         "10 % en tu primera compra (no aplica a alimentos)")
        self.assertEqual(texto_con_condicion("10 %, menos alimentos", True), "10 %, menos alimentos")
        self.assertEqual(texto_con_condicion("10 %", False), "10 %")

    def test_api_y_pos_lo_saben(self):
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=self.usuario).key)
        d = api.get(reverse("api:manada_regalia")).json()
        self.assertTrue(d["excluye_alimentos"])
        self.assertIn("no aplica a alimentos", d["texto"])

        cajero = User.objects.create_user("maria", password="c", is_staff=True)
        cajero.groups.add(Group.objects.get(name="Cajero"))
        self.client.force_login(cajero)
        r = self.client.get(reverse("ventas:cupon"), {"codigo": self.cupon.codigo})
        self.assertTrue(r.json()["excluye_alimentos"])
        r = self.client.get(reverse("ventas:pos"))
        self.assertContains(r, '"alimento": true')
        r = self.client.post(reverse("ventas:vender"), json.dumps({
            "medio_pago": "EFE", "lineas": [{"producto_id": self.alimento.pk, "cantidad": 1}],
            "clave": "k9", "cupon": self.cupon.codigo,
        }), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["total"], 20000.0)


class CuponYPromocion(CuponSinAlimentos):
    """Verificación del encargo v3 (05/11/2026)."""

    def test_el_10_no_se_suma_al_40(self):
        from datetime import timedelta
        from django.utils import timezone
        from catalogo.models import Promocion, PromocionProducto
        from catalogo.promociones import activar
        hoy = timezone.localdate()
        promo = Promocion.objects.create(empresa=self.empresa, nombre="Noviembre loco", descuento_pct=40,
                                         inicio=hoy, fin=hoy + timedelta(days=25))
        PromocionProducto.objects.create(promocion=promo, producto=self.producto)
        activar(promo)
        f = self.venta(self.producto)
        linea = f.lineas.get()
        self.assertEqual(linea.promocion, promo)
        self.assertEqual(f.total, Decimal("3090.00"))               # solo el 40 % (3.090), nada del 10 %
        self.cupon.refresh_from_db()
        self.assertIsNone(self.cupon.usado_en)                      # no rebajó nada: le queda

    def test_el_tiquete_dice_vigencia_y_restriccion(self):
        from datetime import timedelta
        from django.utils import timezone
        from catalogo.models import Promocion, PromocionProducto
        from catalogo.promociones import activar
        from impresion.tiquete import bytes_tiquete
        hoy = timezone.localdate()
        promo = Promocion.objects.create(empresa=self.empresa, nombre="Noviembre loco", descuento_pct=40,
                                         inicio=hoy, fin=hoy + timedelta(days=25))
        PromocionProducto.objects.create(promocion=promo, producto=self.producto)
        activar(promo)
        t = bytes_tiquete(self.venta(self.producto)).decode("cp850", "replace")
        self.assertIn(f"Válida hasta el {promo.fin:%d/%m/%Y}", t)
        self.assertIn("agotar existencias", t)
        promo.estado = Promocion.Estado.BORRADOR
        promo.save()
        t = bytes_tiquete(self.venta(self.alimento, self.producto)).decode("cp850", "replace")
        self.assertIn("No aplica a alimentos", t)

    def test_el_texto_de_la_regalia_de_fabrica(self):
        from .models import Regalia
        self.assertIn("no aplica a alimentos", Regalia._meta.get_field("texto_cliente").default)
