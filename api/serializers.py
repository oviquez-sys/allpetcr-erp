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
    # padre_id (no "padre") para calzar con la forma que ya exporta
    # exportar_catalogo_web.py y que ya sabe leer allpetcr-web.
    padre_id = serializers.IntegerField(source="padre.id", default=None, read_only=True)

    class Meta:
        model = Categoria
        # `orden` (01/09/2026): el menú del sitio se ordena con este campo.
        # Tiene que estar acá y en exportar_catalogo_web.py con el mismo
        # nombre, porque el sitio consume los dos y no sabe de cuál vino.
        fields = ["id", "nombre", "padre_id", "orden"]


class ProductoListaSerializer(serializers.ModelSerializer):
    """Para el catálogo (lista): los campos que necesita una vitrina.

    `categoria_id` (no `categoria_nombre`) a propósito: es EXACTAMENTE la
    forma que ya usa `exportar_catalogo_web.py` y que ya sabe leer
    `allpetcr-web/lib/data.ts` — así conectar el sitio a esta API (Bloque 5)
    no exige tocar la lógica de navegación por categorías, que ya arma el
    árbol padre/hija a partir de ese id."""

    disponible = serializers.SerializerMethodField()
    imagen = serializers.SerializerMethodField()
    # DRF serializa DecimalField como STRING por defecto (para no perder
    # precisión). El sitio espera un number (mismo contrato que ya tenía
    # exportar_catalogo_web.py, que hacía float(p.precio_venta)) — los
    # colones de este negocio son siempre enteros, así que el paso por
    # float no pierde nada. `coerce_to_string=False` es la forma corta de
    # pedir justo eso (mismo criterio en PedidoSalidaSerializer y
    # EstadoPedidoSerializer, más abajo). Si algún día hay tarifas con
    # centavos, estos son los lugares que hay que revisar.
    precio_venta = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)

    class Meta:
        model = Producto
        # "descripcion" va en la LISTA (no solo en el detalle) porque el
        # sitio arma la ficha de producto filtrando el catálogo completo
        # (allpetcr-web/lib/data.ts::getProductoPorSku), no con una llamada
        # aparte a /productos/<sku>/. Faltó en la primera versión de este
        # serializer y rompía la ficha con "Cannot read properties of
        # undefined (reading 'normalize')" al buscar — se encontró
        # probando en el navegador, no a ojo.
        fields = [
            "sku", "nombre", "marca", "categoria_id", "presentacion",
            "descripcion", "mascota", "peso_valor", "peso_unidad",
            "precio_venta", "disponible", "imagen",
        ]

    def get_disponible(self, obj):
        # Booleano, NUNCA la cantidad exacta — mismo criterio que el puente
        # anterior: publicar "quedan 3" le regala a cualquiera tu volumen.
        return obj.stock_actual > 0

    def get_imagen(self, obj):
        """URL ABSOLUTA (con dominio), no relativa.

        `url_imagen_producto` devuelve "/media/productos/x.jpg" cuando el
        almacenamiento es local — correcto para una plantilla del ERP, que
        se resuelve contra el propio origen del ERP, pero roto para un
        cliente en OTRO origen (el sitio web): ahí "/media/..." se
        resolvería contra el dominio del sitio, no del ERP, y la imagen no
        cargaría. `build_absolute_uri` la completa con host y protocolo.
        Con almacenamiento S3-compatible ya viene absoluta y esto no
        cambia nada.
        """
        ruta = url_imagen_producto(obj.imagen)
        if not ruta:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(ruta) if request else ruta


class ProductoDetalleSerializer(ProductoListaSerializer):
    """Para GET /productos/<sku>/. Hoy los mismos campos que la lista
    (que ya incluye descripcion) — se mantiene como clase aparte para el
    día que la ficha necesite algo que la lista no (ej. productos
    relacionados calculados en el servidor)."""


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
    total = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)


class LineaEstadoPedidoSerializer(serializers.Serializer):
    producto_nombre = serializers.CharField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)


class EstadoPedidoSerializer(serializers.Serializer):
    """Para la consulta pública de estado (ítem 16): datos mínimos, nada de
    dirección completa ni identificación — el cliente ya los tiene, no hace
    falta repetírselos en una respuesta que viaja por internet."""

    numero = serializers.CharField()
    estado = serializers.CharField()
    estado_display = serializers.CharField()
    creado_en = serializers.DateTimeField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    lineas = LineaEstadoPedidoSerializer(many=True)
