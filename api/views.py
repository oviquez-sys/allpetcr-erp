"""API para el sitio web (Bloque 3, 2026-08-28).

Autenticación por token en TODA la API, incluida la lectura del catálogo
--------------------------------------------------------------------------
El ERP corre solo en local (no está pensado para exponerse directo a
internet). El sitio público, cuando exista de verdad, no le habla al ERP
desde el navegador del cliente: su propio backend (Next.js) es el que
llama acá, servidor a servidor, con un token. Por eso no hay ninguna vista
"pública" sin autenticación, ni siquiera el catálogo de solo lectura — la
única vía de entrada es un token creado a propósito para el sitio
(`manage.py drf_create_token <usuario>` o desde el admin, en
Autenticación y autorización → Tokens).
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, Throttled, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from catalogo.models import Categoria, Producto
from core.tenancy import empresa_actual
from pedidos import services as pedidos_services
from pedidos.models import Pedido

from .serializers import (
    AvisoDisponibilidadSerializer,
    CategoriaSerializer,
    DisponibilidadSerializer,
    EstadoPedidoSerializer,
    PedidoEntradaSerializer,
    PedidoSalidaSerializer,
    ProductoDetalleSerializer,
    ProductoListaSerializer,
)


class PaginacionCatalogo(PageNumberPagination):
    """Páginas de 24 por defecto (settings), pero quien lo necesite puede
    pedir el catálogo entero de una vez con ?page_size=.

    Rendimiento, 26/09/2026: el sitio pedía las 22 páginas de 24 (526
    productos) una tras otra en cada visita al inicio o al catálogo — ~3 s
    antes del primer byte y 23 consultas por visita contra un límite de
    120/min, o sea que con 5 o 6 visitas en el mismo minuto el sitio se
    caía con un 429. Con ?page_size=1000 es una sola consulta.

    `max_page_size` es el tope duro: nadie puede pedir más que eso aunque lo
    ponga en la URL."""

    page_size_query_param = "page_size"
    max_page_size = 1000


class CatalogoProductosView(generics.ListAPIView):
    """Catálogo con paginación (PageNumberPagination, ver settings) y
    filtros por querystring: ?categoria=<id>&mascota=Gato&marca=Royal
    Canin&q=<texto en nombre o sku>&incluir_agotados=1

    Sin existencias por defecto (regla SOLO_EN_EXISTENCIA de Oscar, del
    02/08/2026 — ver exportar_catalogo_web.py). El puente JSON viejo la
    aplicaba; esta vista, agregada después en el Bloque 3, se había quedado
    filtrando por stock solo si el cliente pedía `?disponible=1` — algo que
    allpetcr-web nunca manda (lib/data.ts pide la ruta pelada), así que el
    sitio, al pasar del JSON a esta API en vivo (Bloque 5), volvió a publicar
    agotados sin que nadie lo pidiera. `incluir_agotados=1` es el
    equivalente de `--incluir-agotados` en el comando de exportación, para
    quien de verdad necesite verlos (ej. un panel interno)."""

    serializer_class = ProductoListaSerializer
    pagination_class = PaginacionCatalogo

    def get_queryset(self):
        empresa = empresa_actual(self.request)
        # categoria__padre y ficha_alimento: los usan las palabras de búsqueda
        # (`etiquetas`) sin una consulta extra por producto.
        qs = (Producto.objects.filter(activo=True, empresa=empresa).exclude(precio_venta=0)
              .select_related("categoria__padre", "ficha_alimento"))

        parametros = self.request.query_params
        if categoria := parametros.get("categoria"):
            qs = qs.filter(categoria_id=categoria)
        if mascota := parametros.get("mascota"):
            qs = qs.filter(mascota__iexact=mascota)
        if marca := parametros.get("marca"):
            qs = qs.filter(marca__iexact=marca)
        if busqueda := parametros.get("q"):
            from django.db.models import Q
            qs = qs.filter(Q(nombre__icontains=busqueda) | Q(sku__iexact=busqueda))
        if parametros.get("incluir_agotados") != "1":
            qs = qs.filter(stock_actual__gt=0)
        return qs.order_by("nombre")


class CategoriasView(generics.ListAPIView):
    """Todo el árbol de categorías de una sola vez, sin paginar: el sitio
    lo necesita completo para armar la navegación (padre/hija), igual que
    hoy lee categorias.json completo."""

    serializer_class = CategoriaSerializer
    pagination_class = None
    queryset = Categoria.objects.all().order_by("nombre")


class ProductoDetalleView(generics.RetrieveAPIView):
    """Ficha de un producto por SKU (no por id interno: el sitio conoce el
    SKU, no las claves primarias del ERP)."""

    serializer_class = ProductoDetalleSerializer
    lookup_field = "sku"

    def get_queryset(self):
        return Producto.objects.filter(activo=True, empresa=empresa_actual(self.request)).select_related("ficha_alimento")


class DisponibilidadView(APIView):
    """Solo el booleano, nunca la cantidad — misma regla que en toda la
    API. Pensado para revalidar justo antes del checkout, cuando ya pasó
    un rato desde que se cargó la ficha del producto."""

    def get(self, request, sku):
        try:
            producto = Producto.objects.get(sku=sku, activo=True, empresa=empresa_actual(request))
        except Producto.DoesNotExist:
            raise NotFound("No existe un producto activo con ese SKU.")
        datos = DisponibilidadSerializer({"sku": producto.sku, "disponible": producto.stock_actual > 0}).data
        return Response(datos)


class ReservarStockView(APIView):
    """POST {sku, cantidad, token_carrito} -> reserva temporal (ver
    pedidos.models.ReservaStock.PLAZO_MINUTOS)."""

    def post(self, request):
        sku = request.data.get("sku")
        cantidad = request.data.get("cantidad")
        token_carrito = request.data.get("token_carrito")
        if not (sku and cantidad and token_carrito):
            raise ValidationError("Faltan sku, cantidad o token_carrito.")
        try:
            producto = Producto.objects.get(sku=sku, activo=True, empresa=empresa_actual(request))
        except Producto.DoesNotExist:
            raise NotFound("No existe un producto activo con ese SKU.")
        try:
            cantidad = Decimal(str(cantidad))
        except InvalidOperation:
            raise ValidationError("Cantidad inválida.")
        try:
            reserva = pedidos_services.reservar_stock(
                producto=producto, cantidad=cantidad, token_carrito=token_carrito,
            )
        except DjangoValidationError as e:
            raise ValidationError(" ".join(e.messages))
        return Response(
            {"sku": sku, "cantidad": str(reserva.cantidad), "expira_en": reserva.expira_en},
            status=status.HTTP_201_CREATED,
        )


class AvisoDisponibilidadView(generics.CreateAPIView):
    """POST {sku, email} -> 'avisame cuando llegue'."""

    serializer_class = AvisoDisponibilidadSerializer


class PedidosView(APIView):
    """POST: recibe un pedido YA PAGADO (ítem 15). Body: ver
    PedidoEntradaSerializer. Idempotente por `referencia_pago` (el mismo
    aviso de la pasarela reenviado dos veces no descuenta el inventario ni
    crea el pedido dos veces — ver pedidos/services.py::crear_pedido, que
    lo garantiza incluso bajo llamadas simultáneas, no solo consecutivas)."""

    def post(self, request):
        entrada = PedidoEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        empresa = empresa_actual(request)

        # SKU -> producto (y a la vez, validación de que existen).
        lineas = []
        for linea in datos["lineas"]:
            try:
                producto = Producto.objects.get(sku=linea["sku"], activo=True, empresa=empresa)
            except Producto.DoesNotExist:
                raise ValidationError(f"No existe un producto activo con SKU {linea['sku']!r}.")
            lineas.append({"producto_id": producto.pk, "cantidad": linea["cantidad"]})

        sucursal = empresa.sucursales.filter(activa=True).first()
        if sucursal is None:
            raise ValidationError("No hay una sucursal activa configurada.")

        try:
            pedido = pedidos_services.crear_pedido(
                empresa=empresa, sucursal=sucursal,
                cliente_nombre=datos["cliente_nombre"],
                cliente_identificacion=datos.get("cliente_identificacion", ""),
                cliente_telefono=datos["cliente_telefono"],
                cliente_email=datos.get("cliente_email", ""),
                direccion_texto=datos["direccion_texto"],
                direccion_lat=datos.get("direccion_lat"),
                direccion_lng=datos.get("direccion_lng"),
                token_carrito=datos.get("token_carrito", ""),
                referencia_pago=datos.get("referencia_pago", ""),
                lineas=lineas,
            )
        except DjangoValidationError as e:
            raise ValidationError(" ".join(e.messages))

        salida = PedidoSalidaSerializer({
            "numero": pedido.numero, "estado": pedido.estado, "total": pedido.total,
        })
        return Response(salida.data, status=status.HTTP_201_CREATED)


class EstadoPedidoView(APIView):
    """GET para que el cliente consulte su pedido (ítem 16).

    Requiere el número Y el teléfono con el que se hizo el pedido — no
    alcanza con el número solo. `PED-00000042` es adivinable con solo
    probar consecutivos; exigir también el teléfono evita que cualquiera
    pueda ir mirando los pedidos de otros. No es más que eso: una
    verificación liviana pensada para una tienda chica, no un login."""

    def get(self, request, numero):
        telefono = request.query_params.get("telefono", "")
        try:
            pedido = Pedido.objects.prefetch_related("lineas__producto").get(numero=numero)
        except Pedido.DoesNotExist:
            raise NotFound("No existe un pedido con ese número.")
        if not telefono or telefono.strip() != pedido.cliente_telefono.strip():
            raise NotFound("No existe un pedido con ese número.")  # mismo error: no confirma que el número sí existe

        datos = EstadoPedidoSerializer({
            "numero": pedido.numero,
            "estado": pedido.estado,
            "estado_display": pedido.get_estado_display(),
            "creado_en": pedido.creado_en,
            "total": pedido.total,
            "lineas": [
                {"producto_nombre": l.producto.nombre, "cantidad": l.cantidad}
                for l in pedido.lineas.all()
            ],
        })
        return Response(datos.data)


# --- Manada AllPetcr (13/10/2026) -------------------------------------------
# El sitio registra a quien escanea el QR de la tienda. Igual que el resto de
# la API: lo llama el servidor del sitio con su token, nunca el navegador.

class ManadaRegistroView(APIView):
    """POST {nombre?, telefono?, email?, google_sub?, verificado, acepta_promociones, fuente?}

    Hace falta el teléfono o el correo. `verificado` lo pone el sitio SOLO
    cuando Google confirmó el correo.

    Qué se le muestra al cliente (14/10/2026): el código y la llave de
    mascotas viajan en la respuesta cuando el cupón SE ACABA DE CREAR en esta
    misma petición (o con Google). A quien escribe un número o un correo que
    ya estaba registrado no se le muestra el código de esa persona: se le dice
    que lo pida en caja, donde basta con dar el número."""

    def post(self, request):
        from manada.correo import enviar_bienvenida
        from manada.services import registrar_miembro

        datos = request.data if isinstance(request.data, dict) else {}
        verificado = datos.get("verificado") is True
        try:
            resultado = registrar_miembro(
                empresa=empresa_actual(request),
                email=str(datos.get("email") or ""),
                nombre=str(datos.get("nombre") or ""),
                telefono=str(datos.get("telefono") or ""),
                google_sub=str(datos.get("google_sub") or "") if verificado else "",
                verificado=verificado,
                acepta_promociones=datos.get("acepta_promociones") is True,
                fuente=str(datos.get("fuente") or ""),
            )
        except DjangoValidationError as e:
            raise ValidationError(" ".join(e.messages))

        correo_enviado = enviar_bienvenida(resultado)
        cupon = resultado.cupon
        perfil = resultado.perfil
        mostrar = verificado or resultado.cupon_nuevo
        salida = {
            "nombre": resultado.cliente.nombre,
            "cliente_nuevo": resultado.cliente_nuevo,
            "ya_era_miembro": not resultado.perfil_nuevo,
            "correo_enviado": correo_enviado,
            "mascotas_pendientes": perfil.mascotas_registradas_en is None,
            "cupon": None,
        }
        if cupon is not None:
            salida["cupon"] = {
                "porcentaje": format(cupon.porcentaje.normalize(), "f"),
                "descripcion": cupon.descripcion,
                "vence_en": cupon.vence_en,
                "estado": cupon.estado,
                "nuevo": resultado.cupon_nuevo,
            }
            if mostrar:
                salida["cupon"]["codigo"] = cupon.codigo
        if (verificado or resultado.perfil_nuevo) and perfil.token_mascotas:
            salida["token_mascotas"] = perfil.token_mascotas
        return Response(salida, status=status.HTTP_201_CREATED if resultado.cliente_nuevo else status.HTTP_200_OK)


class ManadaMascotasView(APIView):
    """GET ?t=<llave> -> si la llave sirve todavía (para no mostrarle el
    formulario a quien ya lo llenó). POST {token, mascotas:[...]} -> las guarda
    una sola vez."""

    def get(self, request):
        from manada.models import PerfilManada

        token = (request.query_params.get("t") or "").strip()
        perfil = (PerfilManada.objects.select_related("cliente").filter(token_mascotas=token).first()
                  if len(token) >= 20 else None)
        if perfil is None:
            return Response({"valido": False})
        return Response({"valido": True, "nombre": perfil.cliente.nombre.split(" ")[0]})

    def post(self, request):
        from manada.services import registrar_mascotas

        datos = request.data if isinstance(request.data, dict) else {}
        try:
            perfil = registrar_mascotas(token=str(datos.get("token") or ""), mascotas=datos.get("mascotas"))
        except DjangoValidationError as e:
            raise ValidationError(" ".join(e.messages))
        return Response({"ok": True, "mascotas": perfil.cliente.mascotas.count()}, status=status.HTTP_201_CREATED)


class ManadaRegaliaView(APIView):
    """GET -> la regalía vigente, para que la página del QR diga lo mismo que
    va a recibir el cliente. Si Oscar la cambia en el admin, la página cambia
    sola."""

    def get(self, request):
        from manada.correo import correo_activo
        from manada.exclusiones import texto_con_condicion
        from manada.services import regalia_para_nuevos

        # Mientras una campaña reemplace la bienvenida (Navidad AllPet 2026)
        # esto responde `activa: false`: el sitio deja de ofrecer el 10 % sin
        # que haya que tocarlo. Qué mostrar en su lugar: GET campana/.
        regalia = regalia_para_nuevos(empresa_actual(request))
        # `correo_activo`: si el ERP no puede mandar correos, el sitio esconde
        # el registro por correo (el código solo viaja por correo) y deja Google.
        if regalia is None:
            return Response({"activa": False, "correo_activo": correo_activo()})
        return Response({
            "correo_activo": correo_activo(),
            "activa": True,
            "porcentaje": format(regalia.porcentaje.normalize(), "f"),
            "texto": texto_con_condicion(regalia.texto_cliente, regalia.excluye_alimentos),
            "excluye_alimentos": regalia.excluye_alimentos,
            "dias_vigencia": regalia.dias_vigencia,
        })


# --- Campañas con sorteo (16/11/2026, Navidad AllPet 2026) --------------------
# El ERP es la fuente oficial de participantes, beneficios y resultados. El
# sitio pregunta acá y no calcula nada por su cuenta: así la caja y la web
# nunca dicen cosas distintas. Reglas: campanas/reglas.py.

def _campana_vigente(request):
    from campanas import reglas
    return reglas.vigente(empresa_actual(request))


def _texto(datos, clave, largo=300):
    return str(datos.get(clave) or "").strip()[:largo]


def _cliente_de(empresa, datos):
    """Reconoce a la persona por su WhatsApp o su correo (los mismos datos
    con los que se inscribió). No crea nada."""
    from manada.identificar import identificar
    return identificar(empresa, telefono=_texto(datos, "telefono", 30), correo=_texto(datos, "email", 254)).cliente


def _plata(valor) -> str:
    """Los montos viajan como texto con dos decimales ("20001.00"), igual que
    en el resto de la API: un número de JSON pierde céntimos en el camino."""
    return f"{Decimal(valor):.2f}"


def _json_beneficios(b):
    return {
        "monto_evaluado": _plata(b["monto_evaluado"]), "umbral": _plata(b["umbral"]),
        "supera_umbral": b["supera_umbral"], "falta_para_bono": _plata(b["falta_para_bono"]),
        "participa": b["participa"], "da_numeros": b["da_numeros"],
        "numeros": b["numeros"], "envio": b["envio"],
    }


class CampanaView(APIView):
    """GET -> la campaña vigente, con todo lo que el sitio necesita mostrar:
    fechas, premio, reglas de los números, zonas de envío gratis y bases.
    `{"activa": false}` si no hay ninguna."""

    def get(self, request):
        from django.utils import timezone

        c = _campana_vigente(request)
        if c is None:
            return Response({"activa": False})
        return Response({
            "activa": True, "slug": c.slug, "nombre": c.nombre, "premio": c.premio,
            "inscripcion_abierta": c.acepta(),
            "inicio": timezone.localtime(c.inicio), "cierre": timezone.localtime(c.cierre),
            "sorteo_en": timezone.localtime(c.sorteo_en),
            "numeros": {"por_inscribirse": c.numeros_inscripcion, "por_compra": c.numeros_compra,
                        "bono": c.numeros_bono, "umbral": _plata(c.umbral_bono),
                        "compra_minima": _plata(c.compra_minima)},
            "envio_gratis": {"activo": c.da_envio_gratis(), "hasta": timezone.localtime(c.envio_hasta),
                             "zonas": c.lista_zonas},
            "reemplaza_bienvenida": c.reemplaza_bienvenida,
            "plazo_reclamo_dias": c.plazo_reclamo_dias, "suplentes": c.suplentes,
            "bases": c.bases,
        })


class CampanaInscripcionView(APIView):
    """POST {nombre, telefono?, email?, acepta_bases: true, acepta_promociones?,
    origen?, google_sub?, verificado?} -> inscribe a la persona.

    Hace falta el WhatsApp o el correo, y `acepta_bases: true` (el sitio lo
    manda solo si la persona marcó la casilla). `acepta_promociones` es OTRA
    casilla y puede ir en false. Inscribirse dos veces no duplica: responde
    200 con `ya_participaba: true`."""

    def post(self, request):
        from campanas.inscripcion import inscribir_persona
        from campanas.models import Participante

        datos = request.data if isinstance(request.data, dict) else {}
        if datos.get("acepta_bases") is not True:
            raise ValidationError("Para inscribirse hay que aceptar las bases de la campaña.")
        verificado = datos.get("verificado") is True
        try:
            r = inscribir_persona(
                empresa=empresa_actual(request), canal=Participante.Canal.WEB,
                nombre=_texto(datos, "nombre", 150), telefono=_texto(datos, "telefono", 30),
                email=_texto(datos, "email", 254), acepta_promociones=datos.get("acepta_promociones") is True,
                origen_visita=_texto(datos, "origen", 80),
                google_sub=_texto(datos, "google_sub", 64) if verificado else "", verificado=verificado,
            )
        except DjangoValidationError as e:
            raise ValidationError(" ".join(e.messages))
        return Response({
            "participa": True, "ya_participaba": not r.creada, "numeros": r.numeros,
            "cliente_nuevo": r.cliente_nuevo, "miembro_nuevo": r.miembro_nuevo,
            "campana": r.participante.campana.nombre,
        }, status=status.HTTP_201_CREATED if r.creada else status.HTTP_200_OK)


class CampanaParticipanteView(APIView):
    """GET ?telefono=…  o  ?email=… -> ¿esa persona ya participa?

    Solo dice sí o no y cuántos números lleva: no devuelve el nombre ni
    ningún otro dato de quien sea dueño de ese número."""

    def get(self, request):
        from campanas import reglas

        c = _campana_vigente(request)
        if c is None:
            return Response({"activa": False, "participa": False, "numeros": 0})
        cliente = _cliente_de(empresa_actual(request), request.query_params)
        participante = reglas.participante_de(c, cliente)
        return Response({"activa": True, "inscripcion_abierta": c.acepta(), "participa": participante is not None,
                         "numeros": reglas.saldo(participante) if participante else 0})


class CampanaBeneficiosView(APIView):
    """POST {lineas: [{sku, cantidad}], entrega: "RET"|"ENV", canton?, distrito?,
    telefono?, email?} -> qué le da la campaña a ese carrito.

    El monto lo calcula el ERP con sus precios (ofertas incluidas): el sitio
    no manda precios. El envío no entra en el monto. `numeros` es lo que la
    compra ganaría SI la persona está inscrita cuando se cobre."""

    def post(self, request):
        from campanas import reglas
        from pedidos.por_confirmar import lineas_con_precio

        datos = request.data if isinstance(request.data, dict) else {}
        empresa = empresa_actual(request)
        c = _campana_vigente(request)
        if c is None:
            return Response({"activa": False})
        try:
            lineas, subtotal = lineas_con_precio(empresa, datos.get("lineas"))
        except DjangoValidationError as e:
            raise ValidationError(" ".join(e.messages))
        entrega = _texto(datos, "entrega", 3) or "RET"
        if entrega not in ("RET", "ENV"):
            raise ValidationError("`entrega` tiene que ser RET (retiro en tienda) o ENV (envío).")
        participa = reglas.participante_de(c, _cliente_de(empresa, datos)) is not None
        b = reglas.beneficios(c, monto=subtotal, participa=participa, entrega=entrega,
                              canton=_texto(datos, "canton", 60), distrito=_texto(datos, "distrito", 60))
        for l in lineas:
            l.pop("producto_id", None)
        return Response({"activa": True, "campana": c.nombre, **_json_beneficios(b), "lineas": lineas})


class PedidoPorConfirmarView(APIView):
    """POST -> anota el pedido que el cliente va a mandar por WhatsApp y
    devuelve su número (WEB-12) para ponerlo en el mensaje.

    Body: {clave, nombre, telefono, email?, entrega: "RET"|"ENV", provincia?,
    canton?, distrito?, senas?, nota?, origen?, lineas: [{sku, cantidad}]}.
    `clave` es un identificador que el sitio genera una vez por pedido: si
    la misma llega dos veces, responde 200 con el pedido que ya existía.

    No aparta inventario ni cobra nada. El pedido se concreta cuando la
    tienda lo cobra en caja con ese número; ahí se acreditan los números."""

    def post(self, request):
        from campanas import reglas
        from pedidos import por_confirmar

        datos = request.data if isinstance(request.data, dict) else {}
        empresa = empresa_actual(request)
        try:
            pedido, creado = por_confirmar.crear(
                empresa=empresa, clave=_texto(datos, "clave", 64), nombre=_texto(datos, "nombre", 150),
                telefono=_texto(datos, "telefono", 30), email=_texto(datos, "email", 254),
                entrega=_texto(datos, "entrega", 3) or "RET", provincia=_texto(datos, "provincia", 40),
                canton=_texto(datos, "canton", 60), distrito=_texto(datos, "distrito", 60),
                senas=_texto(datos, "senas"), nota=_texto(datos, "nota"), origen_visita=_texto(datos, "origen", 80),
                lineas=datos.get("lineas"),
            )
        except DjangoValidationError as e:
            raise ValidationError(" ".join(e.messages))
        salida = {"numero": pedido.numero, "estado": pedido.estado, "estado_display": pedido.get_estado_display(),
                  "subtotal_productos": _plata(pedido.subtotal_productos),
                  "cliente_reconocido": pedido.cliente_id is not None,
                  "beneficios": None}
        c = reglas.vigente(empresa)
        if c is not None:
            b = reglas.beneficios(c, monto=pedido.subtotal_productos, entrega=pedido.entrega, canton=pedido.canton,
                                  distrito=pedido.distrito,
                                  participa=reglas.participante_de(c, pedido.cliente) is not None)
            salida["beneficios"] = _json_beneficios(b)
        return Response(salida, status=status.HTTP_201_CREATED if creado else status.HTTP_200_OK)


class PedidoPorConfirmarEstadoView(APIView):
    """GET ?telefono=… -> en qué va ese pedido: por confirmar, cobrado o
    cancelado; y, si ya se cobró, los números que dio. Igual que el estado de
    un pedido pagado: sin el teléfono con el que se hizo responde 404."""

    def get(self, request, numero):
        from campanas import reglas
        from manada.services import _ocho_digitos
        from pedidos.models import PedidoPorConfirmar
        from pedidos.por_confirmar import normalizar_numero

        pedido = (PedidoPorConfirmar.objects.select_related("factura")
                  .filter(empresa=empresa_actual(request), numero=normalizar_numero(numero)).first())
        telefono = _ocho_digitos(request.query_params.get("telefono") or "")
        if pedido is None or len(telefono) < 8 or telefono != _ocho_digitos(pedido.cliente_telefono):
            raise NotFound("No existe un pedido con ese número.")
        salida = {"numero": pedido.numero, "estado": pedido.estado, "estado_display": pedido.get_estado_display(),
                  "subtotal_productos": _plata(pedido.subtotal_productos), "entrega": pedido.entrega,
                  "envio_gratis": pedido.envio_gratis, "venta": None, "numeros": None}
        if pedido.factura_id:
            salida["venta"] = {"numero": pedido.factura.numero, "total": _plata(pedido.factura.total)}
            d = reglas.desglose_de(pedido.factura)
            if d is not None:
                salida["numeros"] = {k: d[k] for k in ("habituales", "bono", "total", "revertidos", "lleva")}
        return Response(salida)
