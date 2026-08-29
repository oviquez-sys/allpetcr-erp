"""Serializadores de la API pública (catálogo) y del puente con el sitio
(pedidos). Bloque 3, 2026-08-28.

REGLA DURA, repetida a propósito en cada serializer que toca Producto: el
costo, el margen y el markup NUNCA salen del ERP. `exportar_catalogo_web.py`
ya tenía esta misma regla escrita para el puente viejo — acá se sostiene
para el nuevo. `api/tests.py::CostoNuncaSaleDelERP` falla si alguien agrega
esos campos a `fields` más adelante.
"""
from decimal import Decimal

from rest_framework import serializers

from catalogo.models import Categoria, Producto
from core.imagenes import url_imagen_producto
from pedidos.models import AvisoDisponibilidad


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ["id", "nombre", "padre"]


class ProductoListaSerializer(serializers.ModelSerializer):
    """Para el catálogo (lista): los campos que necesita una vitrina."""

    disponible = serializers.SerializerMethodField()
    imagen = serializers.SerializerMethodField()
    categoria_nombre = serializers.CharField(source="categoria.nombre", default="", read_only=True)

    class Meta:
        model = Producto
        fields = [
            "sku", "nombre", "marca", "categoria_nombre", "presentacion",
            "mascota", "peso_valor", "peso_unidad", "precio_venta",
            "disponible", "imagen",
        ]

    def get_disponible(self, obj):
        # Booleano, NUNCA la cantidad exacta — mismo criterio que el puente
        # anterior: publicar "quedan 3" le regala a cualquiera tu volumen.
        return obj.stock_actual > 0

    def get_imagen(self, obj):
        return url_imagen_producto(obj.imagen)


class ProductoDetalleSerializer(ProductoListaSerializer):
    """Para la ficha de producto: agrega la descripción larga."""

    class Meta(ProductoListaSerializer.Meta):
        fields = ProductoListaSerializer.Meta.fields + ["descripcion"]


class DisponibilidadSerializer(serializers.Serializer):
    sku = serializers.CharField()
    disponible = serializers.BooleanField()


class AvisoDisponibilidadSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(write_only=True)

    class Meta:
        model = AvisoDisponibilidad
        fields = ["sku", "email"]

    def validate_sku(self, valor):
        if not Producto.objects.filter(sku=valor, activo=True).exists():
            raise serializers.ValidationError("No existe un producto activo con ese SKU.")
        return valor

    def create(self, datos_validados):
        sku = datos_validados.pop("sku")
        producto = Producto.objects.get(sku=sku)
        aviso, _ = AvisoDisponibilidad.objects.get_or_create(
            producto=producto, email=datos_validados["email"],
        )
        return aviso


class LineaPedidoEntradaSerializer(serializers.Serializer):
    """Una línea tal como la manda el sitio: por SKU, no por id interno del
    ERP (el sitio no tiene por qué conocer las claves primarias del ERP)."""

    sku = serializers.CharField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class PedidoEntradaSerializer(serializers.Serializer):
    """Lo que manda el backend del sitio al confirmar un pago (Bloque 3,
    ítem 15). No es un ModelSerializer de Pedido a propósito: la entrada usa
    SKU y no expone ni acepta campos internos (numero, estado, consecutivo)."""

    cliente_nombre = serializers.CharField(max_length=150)
    cliente_identificacion = serializers.CharField(max_length=20, required=False, allow_blank=True)
    cliente_telefono = serializers.CharField(max_length=30)
    cliente_email = serializers.EmailField(required=False, allow_blank=True)
    direccion_texto = serializers.CharField(max_length=300)
    direccion_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    direccion_lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    token_carrito = serializers.CharField(max_length=64, required=False, allow_blank=True)
    referencia_pago = serializers.CharField(max_length=100, required=False, allow_blank=True)
    lineas = LineaPedidoEntradaSerializer(many=True)

    def validate_lineas(self, valor):
        if not valor:
            raise serializers.ValidationError("El pedido necesita al menos una línea.")
        return valor


class PedidoSalidaSerializer(serializers.Serializer):
    """Lo que se devuelve tras crear el pedido: lo justo para que el sitio
    redirija a una pantalla de confirmación."""

    numero = serializers.CharField()
    estado = serializers.CharField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)


class LineaEstadoPedidoSerializer(serializers.Serializer):
    producto_nombre = serializers.CharField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2)


class EstadoPedidoSerializer(serializers.Serializer):
    """Para la consulta pública de estado (ítem 16): datos mínimos, nada de
    dirección completa ni identificación — el cliente ya los tiene, no hace
    falta repetírselos en una respuesta que viaja por internet."""

    numero = serializers.CharField()
    estado = serializers.CharField()
    estado_display = serializers.CharField()
    creado_en = serializers.DateTimeField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    lineas = LineaEstadoPedidoSerializer(many=True)
