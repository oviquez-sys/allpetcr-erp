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

    def get_queryset(self):
        empresa = empresa_actual(self.request)
        qs = Producto.objects.filter(activo=True, empresa=empresa).exclude(precio_venta=0).select_related("categoria")

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
        return Producto.objects.filter(activo=True, empresa=empresa_actual(self.request))


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
