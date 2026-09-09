"""Pruebas de códigos de barras y etiquetas (S7)."""
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa

from .codigos import es_interno
from .models import CambioPrecio, Categoria, Producto
from .services import cambiar_precio


class AsignarCodigosBarras(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cat = Categoria.objects.create(nombre="Accesorios")

    def _producto(self, sku, barras=""):
        return Producto.objects.create(
            empresa=self.empresa, sku=sku, nombre=f"Producto {sku}",
            categoria=self.cat, codigo_barras=barras, precio_venta=Decimal("1000"),
        )

    def test_rellena_solo_los_vacios(self):
        con = self._producto("100", barras="7850000000017")
        sin = self._producto("200")
        Producto.objects.filter(pk=sin.pk).update(codigo_barras="")
        call_command("asignar_codigos_barras", stdout=StringIO())
        con.refresh_from_db(); sin.refresh_from_db()
        self.assertEqual(con.codigo_barras, "7850000000017")  # no se toca
        # Desde el 06/09/2026 el vacío recibe un código interno (EAN-8 que
        # abre con 2), no una copia del SKU: el SKU en barras sale ilegible en
        # una etiqueta de 35 mm. Ver catalogo/codigos.py.
        self.assertTrue(es_interno(sin.codigo_barras), sin.codigo_barras)

    def test_codigos_resultantes_son_unicos(self):
        # Colisión: un producto ya usa "500" como código; otro producto vacío
        # tiene SKU "500". El comando debe desambiguar sin repetir.
        self._producto("400", barras="500")
        self._producto("500")  # SKU coincide con el código de arriba
        call_command("asignar_codigos_barras", stdout=StringIO())
        codigos = list(Producto.objects.exclude(codigo_barras="").values_list("codigo_barras", flat=True))
        self.assertEqual(len(codigos), len(set(codigos)))  # todos únicos
        self.assertEqual(len(codigos), 2)


class PaginaEtiquetas(TestCase):
    """La HOJA de etiquetas adhesivas: `inventario:etiquetas?hoja=1`.

    Desde el 06/09/2026 la dirección sin `?hoja=1` muestra otra pantalla —la
    del conteo físico, producto por producto (ver `PantallaDeConteo` más
    abajo)—. La hoja siguió existiendo para las tandas grandes, y estas
    pruebas la siguen cuidando; solo cambió por dónde se pide.

    Desde el 02/08/2026 esta pantalla respeta la regla "solo se lista lo que
    hay en existencia" (ver catalogo/consultas.py): una etiqueta es para
    pegarla en un artículo que está en la góndola. Por eso los productos de
    estas pruebas nacen CON stock — antes daba igual porque no se filtraba.

    `stock_actual` se fija directo y no por el kardex a propósito: acá se
    prueba la pantalla de etiquetas, no el servicio de inventario, y montar
    sucursal + bodega + movimiento para cada caso oscurecería lo que se está
    verificando. El camino real del stock ya está cubierto en
    inventario/tests.py.
    """

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cat = Categoria.objects.create(nombre="Accesorios")
        self.staff = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        Producto.objects.create(
            empresa=self.empresa, sku="75564", nombre="Mochila higiénica",
            categoria=self.cat, codigo_barras="75564", precio_venta=Decimal("700"),
            stock_actual=Decimal("5"),
        )

    def test_no_lista_productos_sin_existencias(self):
        """La regla del 02/08/2026, verificada donde se aplica.

        Sin esta prueba, el filtro se podría quitar en una limpieza y nadie se
        enteraría: la pantalla seguiría funcionando, solo mostraría de más."""
        Producto.objects.create(
            empresa=self.empresa, sku="88888", nombre="Agotado hace meses",
            categoria=self.cat, codigo_barras="88888", precio_venta=Decimal("900"),
            stock_actual=Decimal("0"),
        )
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"), {"hoja": "1"})
        self.assertNotContains(r, "Agotado hace meses")
        self.assertContains(r, "Mochila higiénica")

    def test_agotados_1_los_vuelve_a_mostrar(self):
        """La salida explícita: imprimir por adelantado las etiquetas de un
        pedido que viene en camino es un caso real."""
        Producto.objects.create(
            empresa=self.empresa, sku="88888", nombre="Agotado hace meses",
            categoria=self.cat, codigo_barras="88888", precio_venta=Decimal("900"),
            stock_actual=Decimal("0"),
        )
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"), {"agotados": "1", "hoja": "1"})
        self.assertContains(r, "Agotado hace meses")

    def test_solo_faltantes_levanta_el_filtro_de_existencias(self):
        """Los dos filtros miden lo mismo en direcciones opuestas: un producto
        en cero es el más faltante de todos. Sin esta excepción, 'solo
        faltantes' mostraría justo lo que no falta."""
        Producto.objects.create(
            empresa=self.empresa, sku="88888", nombre="Agotado hace meses",
            categoria=self.cat, codigo_barras="88888", precio_venta=Decimal("900"),
            stock_actual=Decimal("0"),
        )
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"), {"solo_faltantes": "1", "hoja": "1"})
        self.assertContains(r, "Agotado hace meses")

    def test_requiere_login(self):
        r = self.client.get(reverse("inventario:etiquetas"))
        self.assertEqual(r.status_code, 302)

    def test_genera_barra_svg(self):
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"), {"hoja": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Mochila higiénica")
        self.assertContains(r, "<svg")  # el código de barras se dibujó
        self.assertContains(r, "₡700")

    def test_copias_multiplica_etiquetas(self):
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"), {"copias": "3", "hoja": "1"})
        self.assertEqual(r.context["total"], 3)

    def test_omite_productos_sin_codigo(self):
        # Producto legado sin código de barras: se fuerza con .update() para
        # saltarse el save() del modelo (que hoy asigna código automáticamente).
        p = Producto.objects.create(
            empresa=self.empresa, sku="999", nombre="Sin código",
            categoria=self.cat, precio_venta=Decimal("500"),
            stock_actual=Decimal("3"),
        )
        Producto.objects.filter(pk=p.pk).update(codigo_barras="")
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"), {"hoja": "1"})
        self.assertEqual(r.context["faltan_codigo"], 1)
        self.assertNotContains(r, "Sin código")

    def test_producto_nuevo_recibe_codigo_automatico(self):
        """Todo producto creado sin código recibe uno interno, listo para
        imprimir la etiqueta. Aplica a cualquier vía de creación."""
        p = Producto.objects.create(
            empresa=self.empresa, sku="ABC123", nombre="Collar nuevo",
            categoria=self.cat, precio_venta=Decimal("3000"),
        )
        self.assertTrue(es_interno(p.codigo_barras), p.codigo_barras)

    def test_no_pisa_codigo_de_proveedor(self):
        """Si el producto ya trae código (EAN del proveedor), no se toca."""
        p = Producto.objects.create(
            empresa=self.empresa, sku="XYZ", nombre="Con EAN",
            categoria=self.cat, codigo_barras="7501234567890", precio_venta=Decimal("100"),
        )
        self.assertEqual(p.codigo_barras, "7501234567890")

    def test_dos_productos_nuevos_no_repiten_codigo(self):
        """Dos productos creados seguidos reciben códigos internos distintos.

        Es la propiedad que sostiene todo lo demás: si dos productos
        compartieran código, la pistola del POS sería ambigua y cobraría el
        artículo equivocado."""
        primero = Producto.objects.create(
            empresa=self.empresa, sku="UNO", nombre="Primero",
            categoria=self.cat, precio_venta=Decimal("100"),
        )
        segundo = Producto.objects.create(
            empresa=self.empresa, sku="DOS", nombre="Segundo",
            categoria=self.cat, precio_venta=Decimal("100"),
        )
        self.assertNotEqual(primero.codigo_barras, segundo.codigo_barras)
        self.assertTrue(es_interno(primero.codigo_barras))
        self.assertTrue(es_interno(segundo.codigo_barras))


class PantallaDeConteo(TestCase):
    """`inventario:etiquetas` sin parámetros: la pantalla del conteo físico.

    Es la excepción a la regla "solo se lista lo que hay en existencia", y la
    excepción es el punto: en un conteo, el producto que el sistema tiene en
    cero es justamente el que hay que ir a ver al estante. Ocultarlo sería
    esconder el error que se salió a buscar. La pantalla lo trae y lo deja
    detrás de un interruptor.
    """

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cat = Categoria.objects.create(nombre="Accesorios")
        self.staff = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        Producto.objects.create(
            empresa=self.empresa, sku="75564", nombre="Mochila higiénica",
            categoria=self.cat, codigo_barras="75564", precio_venta=Decimal("700"),
            stock_actual=Decimal("5"),
        )
        Producto.objects.create(
            empresa=self.empresa, sku="88888", nombre="Agotado hace meses",
            categoria=self.cat, codigo_barras="88888", precio_venta=Decimal("900"),
            stock_actual=Decimal("0"),
        )

    def test_trae_tambien_los_que_estan_en_cero(self):
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"))
        self.assertEqual(r.status_code, 200)
        nombres = [p["nombre"] for p in r.context["productos"]]
        self.assertIn("Mochila higiénica", nombres)
        self.assertIn("Agotado hace meses", nombres)

    def test_manda_la_existencia_de_cada_producto(self):
        """Sin la existencia en pantalla no hay contra qué comparar el conteo."""
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"))
        por_nombre = {p["nombre"]: p for p in r.context["productos"]}
        self.assertEqual(por_nombre["Mochila higiénica"]["stock_actual"], 5.0)
        self.assertEqual(por_nombre["Agotado hace meses"]["stock_actual"], 0.0)

    def test_cuenta_los_que_no_tienen_codigo(self):
        p = Producto.objects.create(
            empresa=self.empresa, sku="999", nombre="Sin código",
            categoria=self.cat, precio_venta=Decimal("500"), stock_actual=Decimal("3"),
        )
        Producto.objects.filter(pk=p.pk).update(codigo_barras="")
        self.client.login(username="oscar", password="x")
        r = self.client.get(reverse("inventario:etiquetas"))
        self.assertEqual(r.context["sin_codigo"], 1)


class HistorialDePrecios(TestCase):
    """Sprint C: cambiar el precio de venta deja siempre rastro (quién, cuándo,
    de cuánto a cuánto)."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.gerente = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Cama",
            precio_venta=Decimal("10000"), costo_promedio=Decimal("6000"),
        )

    def test_cambiar_precio_actualiza_y_registra(self):
        cambiar_precio(producto=self.producto, nuevo_precio="12000", usuario=self.gerente, motivo="subió el costo")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("12000"))
        c = CambioPrecio.objects.get(producto=self.producto)
        self.assertEqual(c.valor_anterior, Decimal("10000"))
        self.assertEqual(c.valor_nuevo, Decimal("12000"))
        self.assertEqual(c.costo_al_momento, Decimal("6000"))  # captura el margen histórico
        self.assertEqual(c.usuario, self.gerente)
        self.assertEqual(c.motivo, "subió el costo")

    def test_variacion_calculada(self):
        cambiar_precio(producto=self.producto, nuevo_precio="9000", usuario=self.gerente)
        c = CambioPrecio.objects.get(producto=self.producto)
        self.assertEqual(c.variacion, Decimal("-1000"))  # bajó

    def test_rechaza_precio_igual(self):
        with self.assertRaises(ValidationError):
            cambiar_precio(producto=self.producto, nuevo_precio="10000", usuario=self.gerente)
        self.assertFalse(CambioPrecio.objects.exists())  # no registra un "cambio" vacío

    def test_rechaza_precio_negativo(self):
        with self.assertRaises(ValidationError):
            cambiar_precio(producto=self.producto, nuevo_precio="-5", usuario=self.gerente)

    def test_varios_cambios_quedan_ordenados(self):
        cambiar_precio(producto=self.producto, nuevo_precio="11000", usuario=self.gerente)
        self.producto.refresh_from_db()
        cambiar_precio(producto=self.producto, nuevo_precio="12500", usuario=self.gerente)
        self.assertEqual(CambioPrecio.objects.filter(producto=self.producto).count(), 2)
        # El más reciente primero (ordering por -fecha, -id)
        ultimo = CambioPrecio.objects.filter(producto=self.producto).first()
        self.assertEqual(ultimo.valor_nuevo, Decimal("12500"))


class PermisosDePrecios(TestCase):
    """Solo gerente puede entrar a precios; un cajero es rebotado."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-001", nombre="Cama", precio_venta=Decimal("10000")
        )
        grp = Group.objects.get_or_create(name="Cajero")[0]
        self.cajero = User.objects.create_user("maria", password="x", is_staff=True)
        self.cajero.groups.add(grp)
        self.gerente = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)

    def test_cajero_no_entra_a_precios(self):
        self.client.login(username="maria", password="x")
        r = self.client.get(reverse("catalogo:precios"))
        self.assertEqual(r.status_code, 302)  # redirigido al dashboard

    def test_cajero_no_puede_cambiar_precio_por_post(self):
        self.client.login(username="maria", password="x")
        self.client.post(reverse("catalogo:precio_producto", args=[self.producto.pk]),
                         {"nuevo_precio": "1", "motivo": "hack"})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("10000"))  # no cambió
        self.assertFalse(CambioPrecio.objects.exists())

    def test_gerente_cambia_precio_por_post(self):
        self.client.login(username="oscar", password="x")
        self.client.post(reverse("catalogo:precio_producto", args=[self.producto.pk]),
                         {"nuevo_precio": "13000", "motivo": "ajuste"})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_venta, Decimal("13000"))
        self.assertTrue(CambioPrecio.objects.filter(producto=self.producto).exists())


class EntradaRapidaProductoAdmin(TestCase):
    """Entrada de mercadería desde la ficha del producto (admin): debe pasar
    por el motor de compras — sube stock, recalcula costo promedio y deja la
    compra recibida. No edita el stock a mano."""

    def setUp(self):
        from core.models import Sucursal
        from inventario.models import Bodega
        from inventario.services import registrar_movimiento
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        self.bodega = Bodega.objects.create(sucursal=self.sucursal, nombre="Principal")
        self.gerente = User.objects.create_user("oscar", password="x", is_staff=True, is_superuser=True)
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="P-100", nombre="Cama", precio_venta=Decimal("10000")
        )
        registrar_movimiento(producto=self.producto, bodega=self.bodega, tipo="INI",
                             cantidad=Decimal("5"), costo_unitario=Decimal("6000"), referencia="INI")
        self.producto.refresh_from_db()
        self.client.login(username="oscar", password="x")

    def test_entrada_sube_stock_y_recalcula_costo(self):
        from compras.models import Compra
        url = reverse("admin:catalogo_producto_entrada", args=[self.producto.pk])
        r = self.client.post(url, {
            "cantidad": "5", "costo_unitario": "8000",
            "proveedor_nuevo": "Distribuidora X", "forma_pago": "CON",
        })
        self.assertEqual(r.status_code, 302)  # redirige a la ficha
        self.producto.refresh_from_db()
        # 5 @6000 + 5 @8000 = 10 unidades, costo promedio 7000
        self.assertEqual(self.producto.stock_actual, Decimal("10"))
        self.assertEqual(self.producto.costo_promedio, Decimal("7000"))
        self.assertTrue(Compra.objects.filter(estado="REC").exists())

    def test_entrada_sin_proveedor_falla_sin_tocar_stock(self):
        url = reverse("admin:catalogo_producto_entrada", args=[self.producto.pk])
        r = self.client.post(url, {"cantidad": "5", "costo_unitario": "8000", "forma_pago": "CON"})
        self.assertEqual(r.status_code, 200)  # vuelve a mostrar el form con el error
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, Decimal("5"))  # intacto


class CamposCatalogoBloque1(TestCase):
    """Marca, peso y CABYS agregados a Producto (Bloque 1, 2026-08-28)."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")

    def _producto(self, **extra):
        return Producto.objects.create(
            empresa=self.empresa, sku="M-001", nombre="Producto de prueba",
            precio_venta=Decimal("1000"), **extra,
        )

    def test_marca_y_peso_son_opcionales(self):
        p = Producto.objects.create(
            empresa=self.empresa, sku="M-002", nombre="Sin marca ni peso",
            precio_venta=Decimal("1000"),
        )
        self.assertEqual(p.marca, "")
        self.assertIsNone(p.peso_valor)
        self.assertEqual(p.peso_unidad, "")
        self.assertEqual(p.cabys, "")

    def test_marca_y_peso_se_guardan(self):
        p = self._producto(marca="Royal Canin", peso_valor=Decimal("15.000"), peso_unidad="kg")
        p.refresh_from_db()
        self.assertEqual(p.marca, "Royal Canin")
        self.assertEqual(p.peso_valor, Decimal("15.000"))
        self.assertEqual(p.peso_unidad, "kg")

    def test_cabys_vacio_no_falla_la_validacion(self):
        p = self._producto()
        p.full_clean()  # no debe lanzar, aunque cabys esté vacío

    def test_cabys_de_13_digitos_es_valido(self):
        p = self._producto(cabys="8720100000000")
        p.full_clean()  # no debe lanzar

    def test_cabys_con_formato_invalido_se_rechaza(self):
        # Instancias SIN guardar: full_clean() debe rechazarlas antes de que
        # lleguen a la base (un valor de más de 13 caracteres ya ni cabría
        # en la columna, pero la validación tiene que atajarlo antes).
        for i, malo in enumerate(["123", "abcdefghijklm", "8720100000000X", "  8720100000000  "]):
            p = Producto(
                empresa=self.empresa, sku=f"M-BAD-{i}", nombre="Producto de prueba",
                precio_venta=Decimal("1000"), cabys=malo,
            )
            with self.assertRaises(ValidationError, msg=f"debió rechazar {malo!r}"):
                p.full_clean()


class CargarFotosPorSku(TestCase):
    """Comando cargar_fotos_por_sku (Bloque 1, 2026-08-28)."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.tmp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_media.cleanup)
        self._override_media = override_settings(MEDIA_ROOT=self.tmp_media.name)
        self._override_media.enable()
        self.addCleanup(self._override_media.disable)

        self.tmp_fotos = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_fotos.cleanup)
        self.carpeta = Path(self.tmp_fotos.name)

    def _escribir(self, nombre, contenido=b"foto-falsa"):
        (self.carpeta / nombre).write_bytes(contenido)

    def test_asigna_por_sku_exacto(self):
        p = Producto.objects.create(empresa=self.empresa, sku="75564", nombre="Correa", precio_venta=Decimal("1000"))
        self._escribir("75564.jpg")
        call_command("cargar_fotos_por_sku", str(self.carpeta), stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.imagen, "productos/75564.jpg")

    def test_archivo_sin_producto_coincidente_no_falla_y_se_reporta(self):
        Producto.objects.create(empresa=self.empresa, sku="1", nombre="Otro", precio_venta=Decimal("1000"))
        self._escribir("99999.jpg")
        salida = StringIO()
        call_command("cargar_fotos_por_sku", str(self.carpeta), stdout=salida)
        self.assertIn("99999.jpg", salida.getvalue())

    def test_no_pisa_foto_existente_sin_reemplazar(self):
        p = Producto.objects.create(
            empresa=self.empresa, sku="200", nombre="Con foto",
            precio_venta=Decimal("1000"), imagen="productos/200-vieja.jpg",
        )
        self._escribir("200.jpg")
        call_command("cargar_fotos_por_sku", str(self.carpeta), stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.imagen, "productos/200-vieja.jpg")  # intacta

    def test_reemplazar_fuerza_la_sobreescritura(self):
        p = Producto.objects.create(
            empresa=self.empresa, sku="300", nombre="Con foto",
            precio_venta=Decimal("1000"), imagen="productos/300-vieja.jpg",
        )
        self._escribir("300.jpg")
        call_command("cargar_fotos_por_sku", str(self.carpeta), "--reemplazar", stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.imagen, "productos/300.jpg")

    def test_no_adivina_coincidencia_parcial(self):
        p = Producto.objects.create(empresa=self.empresa, sku="400", nombre="Producto", precio_venta=Decimal("1000"))
        self._escribir("400-copia.jpg")  # el nombre completo NO es exactamente "400"
        call_command("cargar_fotos_por_sku", str(self.carpeta), stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.imagen, "")

    def test_carpeta_inexistente_da_error_claro(self):
        with self.assertRaises(CommandError):
            call_command("cargar_fotos_por_sku", "/carpeta/que/no/existe/de/verdad", stdout=StringIO())


class ReporteNombresIncompletos(TestCase):
    """Comando reporte_nombres_incompletos (Bloque 1, 2026-08-28): solo
    lista, nunca corrige."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")

    def _producto(self, sku, nombre):
        return Producto.objects.create(
            empresa=self.empresa, sku=sku, nombre=nombre, precio_venta=Decimal("1000"),
        )

    def test_detecta_abreviatura_con_puntos(self):
        self._producto("1", "R.C. Adulto 15kg")
        salida = StringIO()
        call_command("reporte_nombres_incompletos", stdout=salida)
        self.assertIn("R.C. Adulto 15kg", salida.getvalue())

    def test_detecta_nombre_muy_corto(self):
        self._producto("2", "Bozal M")
        salida = StringIO()
        call_command("reporte_nombres_incompletos", stdout=salida)
        self.assertIn("Bozal M", salida.getvalue())

    def test_nombre_completo_no_aparece(self):
        self._producto("3", "Rascador para gatos con torre de tres niveles")
        salida = StringIO()
        call_command("reporte_nombres_incompletos", stdout=salida)
        self.assertNotIn("Rascador para gatos", salida.getvalue())

    def test_no_modifica_ningun_nombre(self):
        """La regla explícita del encargo: listar, no corregir."""
        p = self._producto("4", "R.C. Ad.")
        call_command("reporte_nombres_incompletos", stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.nombre, "R.C. Ad.")

    def test_ignora_productos_inactivos(self):
        self._producto("5", "R.C. Descontinuado").activo = False
        Producto.objects.filter(sku="5").update(activo=False)
        salida = StringIO()
        call_command("reporte_nombres_incompletos", stdout=salida)
        self.assertNotIn("R.C. Descontinuado", salida.getvalue())

    def test_salida_a_archivo(self):
        import tempfile
        self._producto("6", "R.C. Cachorro")
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "reporte.md"
            call_command("reporte_nombres_incompletos", "--salida", str(ruta), stdout=StringIO())
            contenido = ruta.read_text(encoding="utf-8")
        self.assertIn("R.C. Cachorro", contenido)


class SincronizarInventarioSinStock(TestCase):
    """Bandera --sin-stock del comando sincronizar_inventario (01/09/2026).

    Separa los dos trabajos que el comando hacía juntos: mantener el catálogo
    (información) e igualar el stock al conteo del Excel (existencias). Lo
    primero puede seguir viniendo de una hoja para siempre; lo segundo tiene
    que salir del kardex en cuanto la tienda venda algo.
    """

    # Se declaran acá a propósito, no se importan del comando: si alguien
    # cambia COL o ENCABEZADOS_ESPERADOS allá, esta prueba falla y obliga a
    # mirar el Excel real, que es exactamente lo que se quiere.
    ENCABEZADOS = [
        "", "Código (REF)", "Nombre", "Categoría web", "Subcategoría", "Mascota",
        "Descripción", "Precio mayorista (CRC)", "Cantidad en inventario",
        "", "", "", "Precio venta LOCAL sugerido (₡)",
    ]

    def setUp(self):
        import tempfile

        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archivo = Path(self.tmp.name) / "inventario.xlsx"

    def _excel(self, filas):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Inventario Claude"
        ws.append(self.ENCABEZADOS)
        for f in filas:
            ws.append(f)
        wb.save(self.archivo)

    def _fila(self, sku, nombre, cantidad, precio=1000, costo=500):
        return ["", sku, nombre, "Alimentos", "Perro adulto", "Perro",
                "Descripción", costo, cantidad, "", "", "", precio]

    def _correr(self, *extra):
        salida = StringIO()
        call_command("sincronizar_inventario", "--archivo", str(self.archivo), *extra, stdout=salida)
        return salida.getvalue()

    def test_sin_stock_crea_el_producto_con_stock_cero(self):
        from inventario.models import MovimientoInventario

        self._excel([self._fila("A1", "Alimento perro 15 kg", 40)])
        self._correr("--sin-stock")

        p = Producto.objects.get(sku="A1")
        self.assertEqual(p.nombre, "Alimento perro 15 kg")  # el catálogo SÍ entra
        self.assertEqual(p.stock_actual, Decimal("0"))      # el inventario NO
        self.assertEqual(MovimientoInventario.objects.count(), 0)

    def test_sin_la_bandera_el_stock_entra_como_siempre(self):
        """La bandera es opt-in: sin ella, el comportamiento histórico intacto."""
        from inventario.models import MovimientoInventario

        self._excel([self._fila("A1", "Alimento perro 15 kg", 40)])
        self._correr()

        self.assertEqual(Producto.objects.get(sku="A1").stock_actual, Decimal("40"))
        self.assertEqual(MovimientoInventario.objects.filter(tipo="INI").count(), 1)

    def test_sin_la_bandera_el_excel_pisa_lo_que_pasó_en_caja(self):
        """Prueba de documentación del peligro, no de una funcionalidad deseada.

        Si esta prueba empieza a fallar es porque alguien cambió el
        comportamiento por defecto — y eso hay que mirarlo, no arreglarlo a
        ciegas.
        """
        from inventario.models import Bodega, MovimientoInventario
        from inventario.services import registrar_movimiento

        self._excel([self._fila("A1", "Alimento perro 15 kg", 40)])
        self._correr()
        p = Producto.objects.get(sku="A1")
        registrar_movimiento(
            producto=p, bodega=Bodega.objects.first(), tipo="VEN",
            cantidad=Decimal("-37"), referencia="V-1",
        )
        p.refresh_from_db()
        self.assertEqual(p.stock_actual, Decimal("3"))

        self._correr()  # el Excel sigue diciendo 40

        p.refresh_from_db()
        self.assertEqual(p.stock_actual, Decimal("40"))  # las 37 vendidas "volvieron"
        self.assertEqual(MovimientoInventario.objects.filter(tipo="AJU").count(), 1)

    def test_sin_stock_deja_intacto_el_inventario_real_y_lo_reporta(self):
        """El mismo escenario de arriba, con la bandera: no toca nada y avisa."""
        from inventario.models import Bodega, MovimientoInventario
        from inventario.services import registrar_movimiento

        self._excel([self._fila("A1", "Alimento perro 15 kg", 40)])
        self._correr()
        p = Producto.objects.get(sku="A1")
        registrar_movimiento(
            producto=p, bodega=Bodega.objects.first(), tipo="VEN",
            cantidad=Decimal("-37"), referencia="V-1",
        )

        salida = self._correr("--sin-stock")

        p.refresh_from_db()
        self.assertEqual(p.stock_actual, Decimal("3"))
        self.assertEqual(MovimientoInventario.objects.filter(tipo="AJU").count(), 0)
        self.assertIn("A1", salida)  # la diferencia se reporta, no se esconde

    def test_sin_stock_sigue_actualizando_nombre_y_precio(self):
        """Lo que la bandera NO apaga: el catálogo se mantiene igual que antes."""
        from inventario.models import MovimientoInventario

        self._excel([self._fila("A1", "Nombre viejo", 40, precio=1000)])
        self._correr("--sin-stock")

        self._excel([self._fila("A1", "Nombre nuevo", 40, precio=1500)])
        self._correr("--sin-stock")

        p = Producto.objects.get(sku="A1")
        self.assertEqual(p.nombre, "Nombre nuevo")
        self.assertEqual(p.precio_venta, Decimal("1500"))
        self.assertEqual(MovimientoInventario.objects.count(), 0)


class ArbolDeCategorias(TestCase):
    """Comando asegurar_categorias (01/09/2026).

    Define el árbol oficial que comparten el ERP y el sitio. Es la única
    definición: el sitio no la repite, la lee del `orden` exportado.
    """

    def _correr(self, *extra):
        salida = StringIO()
        call_command("asegurar_categorias", *extra, stdout=salida)
        return salida.getvalue()

    def test_crea_el_arbol_completo_desde_cero(self):
        self._correr()
        raices = list(Categoria.objects.filter(padre__isnull=True).values_list("nombre", flat=True))
        for esperada in ("Alimento", "Snacks y premios", "Juguetes", "Paseo",
                         "Ropa y accesorios", "Comederos y bebederos", "Descanso",
                         "Higiene y aseo", "Salud y cuidado", "Arena y sanitarios",
                         "Rascadores y muebles", "Transporte", "Acuario"):
            self.assertIn(esperada, raices)

    def test_no_recrea_las_categorias_viejas_del_excel(self):
        """Regresión del error del 01/09/2026.

        La primera versión del comando salió del Excel y creó "Ropa y paseo",
        "Casa y comida" e "Higiene y salud" como raíces vacías, cuando en la
        base esas cinco ya se habían renombrado y repartido en un árbol de dos
        niveles. Recrearlas dejaba cascarones que habrían salido en el menú.
        """
        self._correr()
        raices = set(Categoria.objects.filter(padre__isnull=True).values_list("nombre", flat=True))
        for vieja in ("Ropa y paseo", "Casa y comida", "Higiene y salud"):
            self.assertNotIn(vieja, raices)

    def test_borrar_vacias_limpia_los_cascarones(self):
        Categoria.objects.create(nombre="Cascarón viejo")
        self._correr()
        self.assertTrue(Categoria.objects.filter(nombre="Cascarón viejo").exists())
        self._correr("--borrar-vacias")
        self.assertFalse(Categoria.objects.filter(nombre="Cascarón viejo").exists())

    def test_borrar_vacias_no_toca_una_categoria_con_productos(self):
        empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        con_producto = Categoria.objects.create(nombre="Con producto")
        Producto.objects.create(
            empresa=empresa, sku="X-1", nombre="Algo", categoria=con_producto,
            precio_venta=Decimal("1000"),
        )
        self._correr("--borrar-vacias")
        self.assertTrue(Categoria.objects.filter(nombre="Con producto").exists())

    def test_borrar_vacias_no_borra_las_categorias_del_arbol_oficial(self):
        """Regresión del 01/09/2026: el comando creaba "Snacks y premios" y la
        borraba en la misma corrida por estar vacía. Está vacía a propósito:
        espera la mercadería que todavía no se ha comprado."""
        self._correr("--borrar-vacias")
        for oficial in ("Alimento", "Snacks y premios"):
            self.assertTrue(
                Categoria.objects.filter(nombre=oficial).exists(),
                f"{oficial} se borró y no debía",
            )

    def test_borrar_vacias_no_toca_una_raiz_con_subcategorias(self):
        """Las raíces reales no tienen productos directos: los tienen sus
        hijas. Borrarlas por "vacías" habría arrasado el catálogo entero."""
        raiz = Categoria.objects.create(nombre="Raíz con hijas")
        Categoria.objects.create(nombre="Una hija", padre=raiz)
        self._correr("--borrar-vacias")
        self.assertTrue(Categoria.objects.filter(nombre="Raíz con hijas").exists())

    def test_alimento_seco_y_humedo_cuelgan_de_alimento(self):
        self._correr()
        alimento = Categoria.objects.get(nombre="Alimento")
        hijas = set(alimento.hijas.values_list("nombre", flat=True))
        self.assertEqual(hijas, {"Alimento seco", "Alimento húmedo", "Dietas veterinarias"})

    def test_alimento_sale_antes_que_juguetes(self):
        """El orden no es alfabético: es el que decide el negocio."""
        self._correr()
        self.assertLess(
            Categoria.objects.get(nombre="Alimento").orden,
            Categoria.objects.get(nombre="Juguetes").orden,
        )

    def test_dietas_veterinarias_se_crea_vacia(self):
        """Sin veterinario no hay producto que ponerle. Existe para que el día
        que entre uno aparezca sola, sin tocar código."""
        self._correr()
        self.assertEqual(Categoria.objects.get(nombre="Dietas veterinarias").productos.count(), 0)

    def test_correrlo_dos_veces_no_duplica_nada(self):
        self._correr()
        antes = Categoria.objects.count()
        salida = self._correr()
        self.assertEqual(Categoria.objects.count(), antes)
        self.assertIn("Categorías creadas ....... 0", salida)

    def test_no_duplica_una_categoria_que_ya_existia(self):
        """Las categorías que ya existían se conservan con sus productos: se
        les pone el orden, no se crean de nuevo."""
        empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        vieja = Categoria.objects.create(nombre="Juguetes")
        Producto.objects.create(
            empresa=empresa, sku="J-1", nombre="Pelota", categoria=vieja,
            precio_venta=Decimal("1000"),
        )
        self._correr()
        self.assertEqual(Categoria.objects.filter(nombre="Juguetes").count(), 1)
        vieja.refresh_from_db()
        self.assertEqual(vieja.productos.count(), 1)  # no perdió su producto
        self.assertNotEqual(vieja.orden, 100)  # sí recibió su orden

    def test_dry_run_no_escribe_nada(self):
        salida = self._correr("--dry-run")
        self.assertEqual(Categoria.objects.count(), 0)
        self.assertIn("SIMULACIÓN", salida)

    def test_el_orden_por_defecto_de_las_consultas_respeta_el_arbol(self):
        """Meta.ordering usa `orden` primero: cualquier listado del ERP sale
        en el mismo orden que el menú del sitio. Es lo que hace que buscar un
        producto se sienta igual en las dos pantallas."""
        self._correr()
        nombres = list(
            Categoria.objects.filter(padre__isnull=True).values_list("nombre", flat=True)
        )
        self.assertEqual(nombres[0], "Alimento")
        self.assertEqual(nombres[1], "Snacks y premios")


class CodigosInternos(TestCase):
    """El código interno de AllPetCR: EAN-8 que empieza con 2.

    Las tres propiedades que sostienen todo lo demás: que sea un EAN válido
    (si el verificador sale mal, el lector lee otro número), que sea único (si
    no, la caja cobra el artículo equivocado) y que NO pise el código de
    fábrica (que es el bueno y es gratis).
    """

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.cat = Categoria.objects.create(nombre="Accesorios")

    def _producto(self, sku, barras=""):
        return Producto.objects.create(
            empresa=self.empresa, sku=sku, nombre=f"Producto {sku}",
            categoria=self.cat, codigo_barras=barras, precio_venta=Decimal("1000"),
        )

    def test_el_codigo_generado_es_un_ean8_valido_que_abre_con_2(self):
        from .codigos import es_ean_valido, siguiente_interno

        codigo = siguiente_interno(set())
        self.assertEqual(len(codigo), 8)
        self.assertTrue(codigo.startswith("2"))
        self.assertTrue(es_ean_valido(codigo))

    def test_no_repite_uno_ya_usado(self):
        from .codigos import siguiente_interno

        primero = siguiente_interno(set())
        segundo = siguiente_interno({primero})
        self.assertNotEqual(primero, segundo)

    def test_reconoce_el_ean_de_fabrica_y_descarta_el_invalido(self):
        from .codigos import es_ean_valido

        self.assertTrue(es_ean_valido("7350053850019"))   # EAN-13 correcto
        self.assertFalse(es_ean_valido("7352052794412"))  # verificador malo
        self.assertFalse(es_ean_valido("RC-15KG-001"))    # sale del SKU

    def test_la_conversion_respeta_el_ean_de_fabrica(self):
        de_fabrica = self._producto("F1", barras="7350053850019")
        del_sku = self._producto("RC-15KG-001", barras="RC-15KG-001")
        call_command("convertir_codigos_internos", "--aplicar", stdout=StringIO())
        de_fabrica.refresh_from_db(); del_sku.refresh_from_db()
        self.assertEqual(de_fabrica.codigo_barras, "7350053850019")
        self.assertTrue(es_interno(del_sku.codigo_barras), del_sku.codigo_barras)

    def test_sin_aplicar_no_toca_nada(self):
        """El ensayo tiene que ser de verdad un ensayo: 532 códigos cambiados
        por error no se deshacen a mano."""
        p = self._producto("SKU-LARGO-001", barras="SKU-LARGO-001")
        call_command("convertir_codigos_internos", stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.codigo_barras, "SKU-LARGO-001")

    def test_la_pantalla_del_erp_no_convierte_sin_confirmar(self):
        """El botón exige la casilla marcada. Cambiar 532 códigos por un clic
        de más no se deshace a mano."""
        User.objects.create_user("jefe", password="x", is_staff=True, is_superuser=True)
        p = self._producto("SIN-CONF", barras="SIN-CONF")
        self.client.login(username="jefe", password="x")
        r = self.client.post(reverse("inventario:codigos"), {})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.codigo_barras, "SIN-CONF")

    def test_la_pantalla_del_erp_convierte_al_confirmar(self):
        User.objects.create_user("jefa", password="x", is_staff=True, is_superuser=True)
        p = self._producto("CON-CONF", barras="CON-CONF")
        self.client.login(username="jefa", password="x")
        self.client.post(reverse("inventario:codigos"), {"confirmar": "si"})
        p.refresh_from_db()
        self.assertTrue(es_interno(p.codigo_barras), p.codigo_barras)

    def test_convertir_dos_veces_no_cambia_los_ya_convertidos(self):
        """Correrlo de nuevo no debe reasignar: las etiquetas ya pegadas
        dejarían de servir."""
        p = self._producto("X1", barras="X1")
        call_command("convertir_codigos_internos", "--aplicar", stdout=StringIO())
        p.refresh_from_db()
        primero = p.codigo_barras
        call_command("convertir_codigos_internos", "--aplicar", stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.codigo_barras, primero)
