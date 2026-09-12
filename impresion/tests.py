"""Pruebas de impresión.

Ninguna toca una impresora real: se comprueba lo que sí se puede romper sin
hardware —el contenido del tiquete, el tamaño de la etiqueta, la selección de
productos y los permisos de las vistas— y se sustituye la capa de Windows por
un doble que guarda lo que se le mandó.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from catalogo.models import Producto
from core.models import Empresa, Sucursal
from inventario.etiquetas import seleccionar_para_etiquetas
from inventario.models import Bodega
from inventario.services import registrar_movimiento

from django.utils import timezone

from impresion import cola, servicio
from impresion.models import TrabajoImpresion
from impresion.tiquete import bytes_tiquete


# --------------------------------------------------------------------------
# Dobles: una factura de mentira alcanza para probar el formato del tiquete,
# y arma la prueba en milisegundos en vez de montar venta, caja y kardex.
# --------------------------------------------------------------------------
@dataclass
class _Producto:
    nombre: str
    sku: str = "SKU1"
    codigo_barras: str = "SKU1"
    precio_venta: Decimal = Decimal("1000")


@dataclass
class _Linea:
    producto: _Producto
    cantidad: Decimal = Decimal("1")
    precio_unitario: Decimal = Decimal("1000")
    total: Decimal = Decimal("1000")
    descuento_pct: Decimal = Decimal("0")
    descuento_monto: Decimal = Decimal("0")
    es_regalia: bool = False


class _Lineas:
    def __init__(self, lineas):
        self._lineas = lineas

    def all(self):
        return self._lineas


@dataclass
class _Empresa:
    nombre: str = "ALLPETCR.COM"
    identificacion: str = "3-102-969361"


@dataclass
class _Sucursal:
    nombre: str = "Central"


class _Factura:
    def __init__(self, lineas, total=Decimal("1000")):
        self.empresa = _Empresa()
        self.sucursal = _Sucursal()
        self.numero = "FE-0001"
        self.creado_en = datetime(2026, 9, 5, 15, 30)
        self.cliente_id = None
        self.estado = "ACT"
        self.motivo_anulacion = ""
        self.subtotal = total
        self.impuesto = Decimal("0")
        self.descuento = Decimal("0")
        self.total = total
        self.lineas = _Lineas(lineas)

    def get_medio_pago_display(self):
        return "Efectivo"


class TiqueteTermico(TestCase):
    def setUp(self):
        self.factura = _Factura([_Linea(_Producto("Alimento perro adulto 15 kg"))])

    def test_lleva_numero_total_y_nombre_del_producto(self):
        datos = bytes_tiquete(self.factura, ancho=48)
        texto = datos.decode("cp850")
        self.assertIn("FE-0001", texto)
        self.assertIn("Alimento perro adulto 15 kg", texto)
        self.assertIn("TOTAL", texto)

    def test_termina_cortando_el_papel(self):
        """Sin el corte el cajero arranca el tiquete a mano y sale torcido."""
        self.assertTrue(bytes_tiquete(self.factura).endswith(b"\x1d\x56\x42\x00"))

    def test_ningun_renglon_pasa_del_ancho(self):
        """Un renglón más largo que el papel se parte solo y descuadra todo."""
        largo = _Factura([_Linea(_Producto("Cama ortopédica extra grande para perros gigantes"))])
        texto = bytes_tiquete(largo, ancho=48).decode("cp850")
        # Se ignoran los comandos: solo interesan los renglones imprimibles.
        for renglon in texto.split("\n"):
            limpio = "".join(c for c in renglon if c.isprintable() and c not in "\x1b\x1d")
            self.assertLessEqual(len(limpio), 52, f"renglón largo: {limpio!r}")

    def test_el_colon_se_convierte_a_simbolo_imprimible(self):
        """₡ no existe en las tablas de las térmicas; sale ¢ y no un error."""
        texto = bytes_tiquete(self.factura).decode("cp850")
        self.assertIn("¢", texto)
        self.assertNotIn("₡", texto)


class SeleccionDeEtiquetas(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Central")
        bodega = Bodega.objects.create(sucursal=sucursal, nombre="Principal")
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="ET-001", nombre="Collar rojo", precio_venta=3500
        )
        registrar_movimiento(
            producto=self.producto, bodega=bodega, tipo="INI",
            cantidad=Decimal("4"), costo_unitario=Decimal("1000"), referencia="INI-ET",
        )
        self.producto.refresh_from_db()

    def test_copias_multiplica_las_etiquetas(self):
        seleccion = seleccionar_para_etiquetas(self.empresa, {"copias": "3"})
        self.assertEqual(seleccion.total, 3)

    def test_segun_stock_saca_una_por_unidad(self):
        seleccion = seleccionar_para_etiquetas(self.empresa, {"segun_stock": "1"})
        self.assertEqual(seleccion.total, 4)

    def test_producto_sin_codigo_se_cuenta_aparte(self):
        Producto.objects.filter(pk=self.producto.pk).update(codigo_barras="")
        seleccion = seleccionar_para_etiquetas(self.empresa, {})
        self.assertEqual(seleccion.pares, [])
        self.assertEqual(seleccion.faltan_codigo, 1)


@override_settings(IMPRESORA_RECIBOS="Recibos de prueba", IMPRESORA_ETIQUETAS="Etiquetas de prueba")
class ServicioDeImpresion(TestCase):
    """El camino DIRECTO: el ERP corriendo en la misma máquina que las
    impresoras. Desde el 10/09/2026 hay que decírselo explícitamente, porque
    el servicio decide solo según si la máquina ve impresoras — y la máquina
    donde corren las pruebas (Linux) no ve ninguna, así que sin este parche
    los trabajos se irían a la cola del agente."""

    def setUp(self):
        parche = mock.patch("impresion.windows.disponible", return_value=True)
        parche.start()
        self.addCleanup(parche.stop)

    def test_el_tiquete_va_a_la_impresora_configurada(self):
        factura = _Factura([_Linea(_Producto("Snack"))])
        with mock.patch("impresion.windows.enviar_crudo") as enviado:
            servicio.imprimir_tiquete(factura)
        impresora, datos = enviado.call_args.args[0], enviado.call_args.args[1]
        self.assertEqual(impresora, "Recibos de prueba")
        self.assertIn(b"FE-0001", datos)

    def test_imprime_una_vez_por_copia(self):
        """Se dibuja una sola imagen y se manda N veces: dibujar es lo caro."""
        producto = _Producto("Snack", codigo_barras="SNK-1")
        with mock.patch("impresion.windows.imprimir_imagen") as impreso:
            with mock.patch("impresion.etiqueta.imagen_etiqueta", return_value="imagen"):
                salidas = servicio.imprimir_etiqueta(producto, copias=4)
        self.assertEqual(salidas, 4)
        self.assertEqual(impreso.call_count, 4)

    def test_producto_sin_codigo_no_se_manda_a_imprimir(self):
        """Mejor un mensaje claro que una etiqueta en blanco gastada."""
        producto = _Producto("Sin código", codigo_barras="")
        with mock.patch("impresion.windows.imprimir_imagen") as impreso:
            with self.assertRaises(servicio.ErrorDeImpresion):
                servicio.imprimir_etiqueta(producto)
        impreso.assert_not_called()


class PermisosDeLasVistas(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_superuser("jefe", "jefe@x.cr", "clave-larga-1234")
        self.client.force_login(self.usuario)

    def test_imprimir_tiquete_no_responde_a_get(self):
        """Imprimir gasta papel: no puede dispararse con recargar la página."""
        r = self.client.get(reverse("impresion:tiquete", args=[1]))
        self.assertEqual(r.status_code, 405)

    def test_imprimir_etiquetas_no_responde_a_get(self):
        r = self.client.get(reverse("impresion:etiquetas"))
        self.assertEqual(r.status_code, 405)

    def test_imprimir_la_etiqueta_de_un_producto_no_responde_a_get(self):
        r = self.client.get(reverse("impresion:etiqueta_producto", args=[1]))
        self.assertEqual(r.status_code, 405)


class TopeDeCopiasPorTanda(TestCase):
    """Una cantidad disparatada se recorta en el SERVIDOR, no en el navegador.

    El 09/09/2026, en la tienda, la pantalla de etiquetas mandó a imprimir con
    la cantidad puesta en el código de barras del producto —trece dígitos—
    porque un segundo escaneo del mismo artículo cayó en la caja de cantidad y
    su Enter final disparó la impresión. El navegador ya recortaba, pero la
    garantía tiene que vivir acá: el que gasta las etiquetas es el servidor, y
    un POST se puede mandar a mano.
    """

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="ALLPETCR.COM")
        self.usuario = User.objects.create_user(
            "oscar", password="clave-larga-1234", is_staff=True, is_superuser=True
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa, sku="ET-777", nombre="Arnés Chaleco Animalitos Talla S",
            codigo_barras="7852052828834", precio_venta=Decimal("5156"),
            stock_actual=Decimal("6"),
        )
        self.client.force_login(self.usuario)

    def _pedir(self, copias):
        with mock.patch("impresion.servicio.imprimir_etiqueta", return_value=1) as impreso:
            respuesta = self.client.post(
                reverse("impresion:etiqueta_producto", args=[self.producto.pk]),
                {"copias": copias},
            )
        return respuesta, impreso

    def test_un_codigo_de_barras_como_cantidad_no_saca_una_tanda(self):
        respuesta, impreso = self._pedir("7852052828834")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(impreso.call_args.args[1], 50)

    def test_una_cantidad_normal_pasa_tal_cual(self):
        _, impreso = self._pedir("6")
        self.assertEqual(impreso.call_args.args[1], 6)

    def test_una_cantidad_que_no_es_numero_imprime_una(self):
        """Mejor una etiqueta de más que una tanda o un error en la caja."""
        _, impreso = self._pedir("no-es-un-numero")
        self.assertEqual(impreso.call_args.args[1], 1)


class VolverDespuesDeImprimir(TestCase):
    """El destino de vuelta viene del formulario: no puede sacar del ERP."""

    def _pedir(self, valor):
        from django.test import RequestFactory

        from impresion.views import _a_donde_volver

        peticion = RequestFactory().post("/impresion/etiquetas/", {"volver_a": valor})
        return _a_donde_volver(peticion)

    def test_acepta_una_ruta_interna(self):
        self.assertEqual(self._pedir("/inventario/etiquetas/?hoja=1"),
                         "/inventario/etiquetas/?hoja=1")

    def test_rechaza_un_sitio_externo(self):
        self.assertEqual(self._pedir("https://sitio-falso.example/erp"),
                         "inventario:etiquetas")

    def test_rechaza_la_forma_con_doble_barra(self):
        """//sitio.example es una URL absoluta aunque empiece con barra."""
        self.assertEqual(self._pedir("//sitio-falso.example"), "inventario:etiquetas")


class LogoDelTiquete(TestCase):
    """El logo del recibo va como imagen de trama ESC/POS (`GS v 0`).

    Se prueba la cabecera y no los píxeles: si el ancho en bytes o el alto no
    cuadran con los datos, la impresora se come el resto del tiquete como si
    fuera parte de la imagen y sale una hoja de basura. Es el error más caro de
    este archivo y no se ve hasta que hay papel de por medio.
    """

    def setUp(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow no está instalado (ejecutar INSTALAR_IMPRESION.bat)")

    def test_la_cabecera_cuadra_con_los_datos(self):
        from impresion.tiquete import bytes_logo

        datos = bytes_logo(384, 576)
        self.assertTrue(datos, "no se armó el logo")
        self.assertEqual(datos[:4], b"\x1d\x76\x30\x00", "no empieza con GS v 0")
        ancho_bytes = datos[4] + datos[5] * 256
        alto = datos[6] + datos[7] * 256
        self.assertEqual(ancho_bytes, 72, "576 puntos son 72 bytes por fila")
        self.assertEqual(len(datos) - 8, ancho_bytes * alto)

    def test_el_logo_queda_centrado_en_el_papel(self):
        """Se rellena con blanco a los lados en vez de confiar en `ESC a 1`."""
        from PIL import Image, ImageOps

        from impresion.tiquete import bytes_logo

        datos = bytes_logo(384, 576)
        ancho_bytes = datos[4] + datos[5] * 256
        alto = datos[6] + datos[7] * 256
        trama = Image.frombytes("1", (ancho_bytes * 8, alto), datos[8:])
        imagen = trama.point(lambda v: 0 if v else 255, mode="L")
        izquierda, _, derecha, _ = ImageOps.invert(imagen).getbbox()
        self.assertAlmostEqual(izquierda, imagen.width - derecha, delta=8)

    def test_un_papel_mas_angosto_da_un_logo_mas_angosto(self):
        from impresion.tiquete import bytes_logo

        angosto = bytes_logo(384, 384)
        self.assertEqual(angosto[4] + angosto[5] * 256, 48, "384 puntos son 48 bytes")

    def test_sin_los_archivos_del_logo_devuelve_vacio(self):
        from pathlib import Path

        from impresion import logotipo
        from impresion.tiquete import bytes_logo

        original = logotipo.CARPETA
        logotipo.CARPETA = Path(original) / "no-existe"
        try:
            self.assertEqual(bytes_logo(384, 576), b"")
        finally:
            logotipo.CARPETA = original

    def test_en_cero_puntos_no_hay_logo(self):
        """Es la forma de apagarlo desde settings sin tocar código."""
        from impresion.tiquete import bytes_logo

        self.assertEqual(bytes_logo(0, 576), b"")


class TiqueteConLogo(TestCase):
    def setUp(self):
        self.factura = _Factura([_Linea(_Producto("Alimento perro adulto 15 kg"))])

    def test_con_logo_el_nombre_legal_sigue_saliendo(self):
        """El logo no reemplaza el nombre de la empresa, lo acompaña.

        En Régimen Simplificado el tiquete es el comprobante que queda: el
        nombre y la cédula tienen que estar aunque arriba haya un dibujo."""
        datos = bytes_tiquete(self.factura, ancho=48, logo=b"\x1d\x76\x30\x00LOGO")
        self.assertIn(b"\x1d\x76\x30\x00LOGO", datos)
        self.assertIn("ALLPETCR.COM".encode("cp850"), datos)
        self.assertIn("3-102-969361".encode("cp850"), datos)

    def test_sin_logo_sale_igual_que_antes(self):
        """Sin logo, el nombre va en letra doble como hasta el 09/09/2026."""
        from impresion.tiquete import DOBLE

        datos = bytes_tiquete(self.factura, ancho=48)
        self.assertIn(DOBLE + "ALLPETCR.COM".encode("cp850"), datos)


class EtiquetaDibujada(TestCase):
    """El dibujo necesita Pillow. Si no está instalado (máquina de desarrollo
    sin el módulo de impresión), la prueba se salta en vez de fallar: el resto
    del ERP no depende de imprimir."""

    def setUp(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow no está instalado (ejecutar INSTALAR_IMPRESION.bat)")

    def test_sale_del_tamano_exacto_del_rollo(self):
        from impresion.etiqueta import imagen_etiqueta

        imagen = imagen_etiqueta(_Producto("Collar rojo mediano", codigo_barras="ET-001"),
                                 ancho_mm=44.5, alto_mm=31.8)
        # 44,5 × 31,8 mm a 203 puntos por pulgada, que es el rollo que vende el
        # proveedor. Si esto cambia, la etiqueta sale corrida o partida entre
        # dos etiquetas del rollo.
        self.assertEqual(imagen.size, (356, 254))

    def test_nada_se_sale_de_la_etiqueta(self):
        """Ningún elemento toca el borde del papel.

        Es la prueba que más vale de este archivo: el reparto vertical es a
        mano y un cambio de tamaño de letra empuja la descripción fuera de la
        etiqueta. En papel eso se ve como un renglón cortado a la mitad —o
        impreso encima de la etiqueta siguiente— y solo se descubre gastando
        rollo. Se prueba con el nombre más largo que puede aparecer.
        """
        from PIL import ImageOps

        from impresion.etiqueta import imagen_etiqueta

        largo = ("Alfombrilla Refrescante Redonda de 70 cm para perros "
                 "grandes de raza gigante con funda extra")
        for producto in (_Producto(largo, codigo_barras="7852052794412"),
                         _Producto("Collar", codigo_barras="ALLPET-12345678")):
            with self.subTest(nombre=producto.nombre[:20]):
                imagen = imagen_etiqueta(producto)
                caja = ImageOps.invert(imagen.convert("L")).getbbox()
                izquierda, arriba, derecha, abajo = caja
                self.assertGreaterEqual(arriba, 4, "hay tinta pegada al borde de arriba")
                self.assertGreaterEqual(izquierda, 4, "hay tinta pegada al borde izquierdo")
                self.assertLessEqual(derecha, imagen.width - 4, "se sale por la derecha")
                self.assertLessEqual(abajo, imagen.height - 4, "se sale por abajo")

    def test_lleva_el_logo_arriba(self):
        """La franja de arriba trae el logotipo, no el nombre del producto."""
        # El logo se movió a impresion/logotipo.py el 09/09/2026, cuando el
        # tiquete empezó a usar el mismo que la etiqueta. Esta prueba siguió
        # importándolo de etiqueta.py y quedó en rojo sin que nadie lo notara;
        # corregido el 11/09/2026.
        from impresion.etiqueta import ALTO_LOGO_MM, _mm_a_px, imagen_etiqueta
        from impresion.logotipo import _pieza

        self.assertIsNotNone(_pieza("marca", 40), "falta impresion/marca/logo_marca.png")
        self.assertIsNotNone(_pieza("texto", 40), "falta impresion/marca/logo_texto.png")

        imagen = imagen_etiqueta(_Producto("Collar rojo", codigo_barras="ET-001"))
        franja = imagen.convert("L").crop((0, 0, imagen.width, _mm_a_px(ALTO_LOGO_MM + 2)))
        negros = sum(franja.histogram()[:128])
        self.assertGreater(negros, 200, "la franja del logo salió casi en blanco")

    def test_sin_los_archivos_del_logo_igual_imprime(self):
        """Si falta el PNG del logo, la etiqueta sale sin logo pero sale.

        Preferimos una etiqueta sin marca a una cajera que no puede etiquetar
        porque se movió un archivo de imagen."""
        from pathlib import Path

        from impresion import etiqueta as modulo
        from impresion import logotipo

        # La carpeta de la marca se movió a logotipo.py junto con el resto del
        # logo (09/09/2026). Ver la nota de la prueba de arriba.
        original = logotipo.CARPETA
        logotipo.CARPETA = Path(original) / "no-existe"
        try:
            imagen = modulo.imagen_etiqueta(_Producto("Collar", codigo_barras="ET-001"))
        finally:
            logotipo.CARPETA = original
        self.assertEqual(imagen.size, (356, 254))

    def test_el_codigo_de_barras_cabe_en_el_ancho(self):
        from impresion.etiqueta import imagen_codigo_barras

        # 41,5 mm es el ancho útil de la etiqueta (44,5 menos los márgenes).
        imagen = imagen_codigo_barras("ALLPET-12345678", ancho_mm=41.5, alto_px=90)
        util_px = 41.5 / 25.4 * 203
        self.assertLessEqual(imagen.width, util_px)
        # Y además tiene que sobrar blanco a los lados: sin zona de silencio
        # el lector no intenta leer, aunque las barras estén perfectas.
        self.assertLessEqual(imagen.width, util_px * 0.92)


class PantallaDeEtiquetasSeDibuja(TestCase):
    """La pantalla del conteo físico se arma sin reventar.

    Vale la pena aunque parezca trivial: un error de plantilla no lo detecta
    ninguna otra prueba y solo aparece cuando alguien abre la página —en la
    bodega, con el conteo a medias—."""

    def test_la_plantilla_se_arma_con_productos(self):
        from django.template.loader import render_to_string

        html = render_to_string("inventario/etiquetas.html", {
            "productos": [{
                "id": 1, "sku": "ET-1", "nombre": "Collar rojo", "codigo_barras": "ET-1",
                "precio_venta": 3500.0, "stock_actual": 4.0, "presentacion": "Talla M",
                "marca": "AllPet", "categoria": "Collares", "imagen": "",
            }],
            "tope": 150,
            "sin_codigo": 0,
        })
        # Las tarjetas se arman en el navegador con los datos que va abajo en
        # JSON; acá se comprueba que el dato viaje y que la pantalla sepa pedir
        # el código como imagen y mostrar la existencia.
        self.assertIn("Collar rojo", html)
        self.assertIn("/impresion/codigo/", html)
        self.assertIn("Sistema:", html)

    def test_la_hoja_adhesiva_sigue_armandose(self):
        from django.template.loader import render_to_string

        html = render_to_string("inventario/etiquetas_hoja.html", {
            "etiquetas": [{"nombre": "Collar rojo", "precio": 3500, "sku": "ET-1", "svg": ""}],
            "total": 1, "faltan_codigo": 0, "recortado": False, "tope": 500,
            "categorias": [], "cat_actual": "", "copias": 1,
            "segun_stock": False, "solo_faltantes": False, "agotados": False,
        })
        self.assertIn("Collar rojo", html)


# --------------------------------------------------------------------------
# El camino del AGENTE (10/09/2026): el ERP corre en DigitalOcean y no ve las
# impresoras de la tienda, así que deja el trabajo en una cola y el agente que
# corre en el mostrador lo recoge.
#
# Estas pruebas corren SIN parchar `windows.disponible`: la máquina de pruebas
# es Linux y no ve impresoras, que es exactamente la situación del servidor.
# --------------------------------------------------------------------------
@override_settings(IMPRESORA_RECIBOS="Recibos de prueba",
                   IMPRESORA_ETIQUETAS="Etiquetas de prueba")
class ColaDeImpresion(TestCase):
    def test_sin_impresoras_el_tiquete_queda_en_la_cola(self):
        """Lo importante es que NO reviente: la venta ya se registró."""
        factura = _Factura([_Linea(_Producto("Snack"))])
        servicio.imprimir_tiquete(factura)

        trabajo = TrabajoImpresion.objects.get()
        self.assertEqual(trabajo.tipo, TrabajoImpresion.TIQUETE)
        self.assertEqual(trabajo.formato, TrabajoImpresion.CRUDO)
        self.assertEqual(trabajo.estado, TrabajoImpresion.PENDIENTE)
        self.assertEqual(trabajo.impresora, "Recibos de prueba")
        # Los bytes son los mismos que saldrían por el camino directo.
        self.assertIn(b"FE-0001", bytes(trabajo.contenido))

    def test_cada_copia_de_etiqueta_es_un_trabajo(self):
        """El agente imprime de a un papel: cuatro copias, cuatro trabajos."""
        producto = _Producto("Snack", codigo_barras="7501234567890")
        salidas = servicio.imprimir_etiqueta(producto, copias=4)

        self.assertEqual(salidas, 4)
        trabajos = TrabajoImpresion.objects.all()
        self.assertEqual(trabajos.count(), 4)
        primero = trabajos.first()
        self.assertEqual(primero.formato, TrabajoImpresion.IMAGEN)
        # El tamaño del papel viaja con el trabajo: es del diseño de la
        # etiqueta, no de la máquina donde corre el agente.
        self.assertAlmostEqual(primero.ancho_mm, 44.5)
        self.assertAlmostEqual(primero.alto_mm, 31.8)
        self.assertTrue(bytes(primero.contenido).startswith(b"\x89PNG"))

    def test_un_trabajo_viejo_no_sale_a_destiempo(self):
        """Encender la computadora a mediodía no debe escupir los tiquetes de
        toda la mañana: el trabajo vencido se descarta, no se imprime."""
        factura = _Factura([_Linea(_Producto("Snack"))])
        servicio.imprimir_tiquete(factura)
        TrabajoImpresion.objects.update(
            vence_en=timezone.now() - timezone.timedelta(minutes=1)
        )

        self.assertEqual(cola.tomar_pendientes(), [])
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.VENCIDO
        )

    def test_lo_que_se_toma_no_se_vuelve_a_entregar(self):
        """Si el mismo trabajo se entregara dos veces, saldría impreso dos
        veces y el cliente se llevaría dos tiquetes."""
        servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))

        primera = cola.tomar_pendientes()
        segunda = cola.tomar_pendientes()
        self.assertEqual(len(primera), 1)
        self.assertEqual(segunda, [])

    # ---- Varias computadoras, unas solas impresoras (12/09/2026) ----------
    # Oscar tiene su computadora, Francisco la suya, y más adelante habrá una
    # de un empleado; las impresoras son las del mostrador. Si el agente que
    # Oscar dejó abierto en la casa se lleva el tiquete de una venta hecha en
    # la tienda, el cliente se queda sin comprobante y nadie se entera.

    def test_una_maquina_sin_impresoras_no_se_lleva_nada(self):
        """El agente de la casa de Oscar: ve cero impresoras, recibe cero
        trabajos, y el tiquete sigue esperando a la máquina del mostrador."""
        servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))

        self.assertEqual(cola.tomar_pendientes(impresoras=[]), [])
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.PENDIENTE
        )

    def test_una_maquina_con_otras_impresoras_tampoco(self):
        """Tener impresoras no alcanza: tiene que tener LA del trabajo."""
        servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))

        tomados = cola.tomar_pendientes(impresoras=["Microsoft Print to PDF"])
        self.assertEqual(tomados, [])
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.PENDIENTE
        )

    def test_la_maquina_del_mostrador_si_se_lo_lleva(self):
        servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))

        tomados = cola.tomar_pendientes(
            impresoras=["Microsoft Print to PDF", "Recibos de prueba"]
        )
        self.assertEqual(len(tomados), 1)
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.TOMADO
        )

    def test_cada_maquina_se_lleva_lo_suyo(self):
        """Si un día el rollo de etiquetas queda en otra computadora, cada una
        se lleva lo que puede imprimir y ninguna bloquea a la otra."""
        servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))
        servicio.imprimir_etiqueta(
            _Producto("Snack", codigo_barras="7501234567890"), copias=1
        )

        recibos = cola.tomar_pendientes(impresoras=["Recibos de prueba"])
        etiquetas = cola.tomar_pendientes(impresoras=["Etiquetas de prueba"])

        self.assertEqual([t.tipo for t in recibos], [TrabajoImpresion.TIQUETE])
        self.assertEqual([t.tipo for t in etiquetas], [TrabajoImpresion.ETIQUETA])

    def test_reportar_cierra_el_trabajo(self):
        servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))
        trabajo = cola.tomar_pendientes()[0]

        self.assertTrue(cola.reportar(trabajo.pk, ok=False, detalle="Sin papel"))
        trabajo.refresh_from_db()
        self.assertEqual(trabajo.estado, TrabajoImpresion.ERROR)
        self.assertEqual(trabajo.detalle, "Sin papel")
        self.assertIsNotNone(trabajo.terminado_en)


@override_settings(IMPRESION_AGENTE_TOKEN="llave-de-prueba",
                   IMPRESORA_RECIBOS="Recibos de prueba")
class PuertasDelAgente(TestCase):
    """La cola queda expuesta a internet: lo único que la protege es la llave."""

    def setUp(self):
        servicio.imprimir_tiquete(_Factura([_Linea(_Producto("Snack"))]))

    def test_sin_llave_no_entrega_nada(self):
        r = self.client.get(reverse("impresion:agente_pendientes"))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.PENDIENTE
        )

    def test_con_llave_equivocada_tampoco(self):
        r = self.client.get(reverse("impresion:agente_pendientes"),
                            headers={"x-agente-token": "otra-llave"})
        self.assertEqual(r.status_code, 401)

    @override_settings(IMPRESION_AGENTE_TOKEN="")
    def test_sin_llave_configurada_la_puerta_queda_cerrada(self):
        """Un despliegue al que se le olvidó la variable NO debe quedar con la
        cola abierta a cualquiera."""
        r = self.client.get(reverse("impresion:agente_pendientes"),
                            headers={"x-agente-token": ""})
        self.assertEqual(r.status_code, 401)

    def test_con_la_llave_se_lleva_el_trabajo(self):
        import base64

        r = self.client.get(reverse("impresion:agente_pendientes"),
                            headers={"x-agente-token": "llave-de-prueba"})
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertEqual(len(datos["trabajos"]), 1)
        trabajo = datos["trabajos"][0]
        self.assertEqual(trabajo["impresora"], "Recibos de prueba")
        self.assertIn(b"FE-0001", base64.b64decode(trabajo["contenido_b64"]))
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.TOMADO
        )

    def test_la_puerta_respeta_la_lista_de_impresoras(self):
        """Lo mismo que prueba la cola, pero por la puerta que usa el agente:
        una máquina que no tiene la impresora se va con las manos vacías."""
        r = self.client.get(
            reverse("impresion:agente_pendientes"),
            {"impresoras": "Microsoft Print to PDF"},
            headers={"x-agente-token": "llave-de-prueba"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["trabajos"], [])
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.PENDIENTE
        )

    def test_una_lista_vacia_no_es_lo_mismo_que_no_mandarla(self):
        """`impresoras=` (máquina sin impresoras) da cero trabajos; no mandar
        el parámetro los da todos, que es lo que permite probar a mano desde el
        navegador. Confundir esos dos casos es justo el error que dejaría al
        agente de la casa llevándose los tiquetes de la tienda."""
        vacia = self.client.get(
            reverse("impresion:agente_pendientes"), {"impresoras": ""},
            headers={"x-agente-token": "llave-de-prueba"},
        )
        self.assertEqual(vacia.json()["trabajos"], [])

        sin_parametro = self.client.get(
            reverse("impresion:agente_pendientes"),
            headers={"x-agente-token": "llave-de-prueba"},
        )
        self.assertEqual(len(sin_parametro.json()["trabajos"]), 1)

    def test_el_agente_reporta_como_le_fue(self):
        import json

        trabajo_id = TrabajoImpresion.objects.get().pk
        r = self.client.post(
            reverse("impresion:agente_resultado"),
            data=json.dumps({"id": trabajo_id, "ok": True}),
            content_type="application/json",
            headers={"x-agente-token": "llave-de-prueba"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            TrabajoImpresion.objects.get().estado, TrabajoImpresion.IMPRESO
        )
