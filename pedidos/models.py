"""Pedidos del sitio web (e-commerce), Bloque 2 — 2026-08-28.

Un Pedido nace ya PAGADO: la pasarela de pago confirma el cobro y recién ahí
se crea el Pedido, en estado `pago_confirmado`. Todo lo de ANTES de pagar
—el carrito y la reserva temporal de stock durante el checkout— vive en
`ReservaStock`, que no depende de que exista un Pedido (ver esa clase).

Es un dominio separado de `ventas.FacturaVenta` (el documento del POS,
presencial, con caja y medio de pago en el momento) a propósito: mezclar
"venta de mostrador" con "pedido en línea" habría significado forzar campos
que no aplican de un lado o del otro (sesión de caja, dirección de envío).
Cuando ambos flujos conecten con el mismo inventario, lo hacen a través del
mismo kardex (`inventario.MovimientoInventario`), no compartiendo modelo.
"""
from django.conf import settings
from django.db import models

from catalogo.models import Producto
from core.models import Empresa, Sucursal


class Pedido(models.Model):
    class Estado(models.TextChoices):
        PAGO_CONFIRMADO = "PAG", "Pago confirmado"
        EN_PREPARACION = "PRE", "En preparación"
        DESPACHADO = "DES", "Despachado"
        ENTREGADO = "ENT", "Entregado"
        CANCELADO = "CAN", "Cancelado"

    # Transiciones permitidas. Cualquier otro salto (ej. "entregado" ->
    # "en_preparacion") se rechaza en el servicio, no acá: el modelo solo
    # declara el mapa, `pedidos/services.py::cambiar_estado` lo aplica.
    TRANSICIONES = {
        Estado.PAGO_CONFIRMADO: {Estado.EN_PREPARACION, Estado.CANCELADO},
        Estado.EN_PREPARACION: {Estado.DESPACHADO, Estado.CANCELADO},
        Estado.DESPACHADO: {Estado.ENTREGADO},
        Estado.ENTREGADO: set(),
        Estado.CANCELADO: set(),
    }

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="pedidos")
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="pedidos")
    numero = models.CharField(max_length=20, unique=True)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PAGO_CONFIRMADO)

    # Datos del cliente y envío. Texto simple: el pedido no exige que el
    # comprador tenga cuenta ni un Cliente del ERP (ese es el mundo del POS
    # y del crédito). Se pide identificación porque una futura factura
    # electrónica la necesita (Bloque 4) — vacía si el cliente no la da.
    cliente_nombre = models.CharField(max_length=150)
    cliente_identificacion = models.CharField(max_length=20, blank=True)
    cliente_telefono = models.CharField(max_length=30)
    cliente_email = models.EmailField(blank=True)
    # A quién se le liga en la base de clientes (14/10/2026): se reconoce por
    # cédula, teléfono o correo al crear el pedido (manada.identificar). Los
    # campos cliente_* de arriba se quedan como estaban: son lo que la persona
    # escribió ese día, y el courier los necesita aunque el cliente cambie.
    cliente = models.ForeignKey("ventas.Cliente", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="pedidos_web")
    direccion_texto = models.CharField(max_length=300, help_text="Dirección escrita, la que necesita el courier")
    direccion_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    direccion_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    impuesto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    referencia_pago = models.CharField(
        max_length=100, blank=True,
        help_text="ID de la transacción en la pasarela de pago, para conciliar y para la idempotencia del webhook",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["empresa", "estado", "creado_en"], name="pedido_emp_est_fecha_idx"),
        ]
        constraints = [
            # Único cuando SÍ hay referencia (índice parcial): permite que
            # varios pedidos tengan referencia_pago en blanco sin chocar
            # entre sí, pero es lo que hace posible resolver la
            # idempotencia del webhook con un IntegrityError en vez de una
            # condición de carrera entre el SELECT y el INSERT (ver
            # pedidos/services.py::crear_pedido).
            models.UniqueConstraint(
                fields=["empresa", "referencia_pago"],
                condition=~models.Q(referencia_pago=""),
                name="pedido_referencia_pago_unica",
            ),
        ]

    def __str__(self):
        return f"{self.numero} — {self.get_estado_display()}"


class LineaPedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "línea de pedido"
        verbose_name_plural = "líneas de pedido"
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_pedido_positiva"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.producto.nombre}"


class CambioEstadoPedido(models.Model):
    """Bitácora inmutable de cada cambio de estado: quién, cuándo, de qué
    estado a cuál. Mismo criterio que `catalogo.CambioPrecio` — nada de
    estado se pisa en silencio."""

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="cambios_estado")
    estado_anterior = models.CharField(max_length=3, choices=Pedido.Estado.choices)
    estado_nuevo = models.CharField(max_length=3, choices=Pedido.Estado.choices)
    nota = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "cambio de estado de pedido"
        verbose_name_plural = "cambios de estado de pedido"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.pedido.numero}: {self.estado_anterior} → {self.estado_nuevo}"


class AvisoDisponibilidad(models.Model):
    """'Avisame cuando llegue': correo + producto. Se marca `notificado`
    cuando se le avisa, en vez de borrarse, para no perder el historial de
    quién pidió qué (útil para decidir qué reponer primero)."""

    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="avisos_disponibilidad")
    email = models.EmailField()
    creado_en = models.DateTimeField(auto_now_add=True)
    notificado = models.BooleanField(default=False)
    notificado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "aviso de disponibilidad"
        verbose_name_plural = "avisos de disponibilidad"
        constraints = [
            # La misma persona puede pedir aviso de varios productos, pero no
            # duplicar el pedido del mismo producto una y otra vez.
            models.UniqueConstraint(fields=["producto", "email"], name="aviso_unico_por_producto_y_correo"),
        ]

    def __str__(self):
        return f"{self.email} — {self.producto.sku}"


class ReservaStock(models.Model):
    """Reserva temporal de stock durante el checkout, ANTES de que exista un
    Pedido (que solo nace tras confirmarse el pago — ver `Pedido`).

    Por qué 15 minutos: es tiempo de sobra para completar un pago con
    tarjeta o SINPE sin que el cliente sienta apuro, y corto para que un
    carrito abandonado no bloquee la última unidad de un producto para
    todos los demás por horas. Es un valor de arranque razonable, no una
    medición — si en producción resulta corto o largo, se ajusta acá
    (una sola constante, `PLAZO_MINUTOS`).
    """

    PLAZO_MINUTOS = 15

    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="reservas_stock")
    token_carrito = models.CharField(max_length=64, db_index=True, help_text="Identificador opaco del carrito del navegador")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    creada_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "reserva de stock"
        verbose_name_plural = "reservas de stock"
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_reserva_positiva"),
            # Una fila por producto y carrito: cambiar la cantidad en el
            # carrito actualiza la reserva existente, no apila una nueva.
            models.UniqueConstraint(fields=["producto", "token_carrito"], name="reserva_unica_por_producto_y_carrito"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.producto.sku} (carrito {self.token_carrito[:8]}…)"


class PedidoPorConfirmar(models.Model):
    """El pedido que el cliente arma en el sitio y manda por WhatsApp, ANTES
    de pagarlo (16/11/2026, campaña Navidad AllPet).

    Hasta esta fecha ese pedido no existía en el ERP: el sitio solo armaba un
    mensaje de WhatsApp y la venta se cobraba después en caja como cualquier
    otra, así que era imposible saber qué ventas habían nacido en la web.

    Ahora el sitio lo anota acá al armar el mensaje y recibe un número corto
    (WEB-12) que viaja en el WhatsApp. Cuando la tienda lo cobra en caja, la
    venta queda ligada a este registro: la identidad del pedido web se
    conserva aunque se confirme por WhatsApp y se cobre en el mostrador.

    No aparta inventario ni mueve nada: es una intención de compra. Lo que
    cuenta —existencias, precio, números de la campaña— se decide al cobrar.
    Por eso es otro modelo y no un estado más de `Pedido`, que nace pagado y
    descuenta el kardex al crearse.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Por confirmar"
        CONCRETADO = "CON", "Cobrado"
        CANCELADO = "CAN", "Cancelado"

    class Entrega(models.TextChoices):
        RETIRO = "RET", "Retiro en tienda"
        ENVIO = "ENV", "Envío a domicilio"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="pedidos_por_confirmar")
    numero = models.CharField(max_length=20, unique=True)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE)
    # La misma clave reenviada (doble toque, reintento de la red) devuelve el
    # mismo pedido en vez de crear dos.
    clave = models.CharField(max_length=64, null=True, blank=True, unique=True, editable=False)

    cliente_nombre = models.CharField(max_length=150)
    cliente_telefono = models.CharField(max_length=30)
    cliente_email = models.EmailField(blank=True)
    cliente = models.ForeignKey("ventas.Cliente", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="pedidos_por_confirmar")

    entrega = models.CharField(max_length=3, choices=Entrega.choices, default=Entrega.RETIRO)
    provincia = models.CharField(max_length=40, blank=True)
    canton = models.CharField("cantón", max_length=60, blank=True)
    distrito = models.CharField(max_length=60, blank=True)
    senas = models.CharField("señas", max_length=300, blank=True)
    nota = models.CharField(max_length=300, blank=True)
    # De dónde vino la visita (UTM del sitio). Vacío = origen desconocido.
    origen_visita = models.CharField(max_length=80, blank=True)

    # Lo que pidió, como lo vio ese día: [{"sku", "nombre", "cantidad", "precio"}].
    # Es una foto para el que atiende; al cobrar manda el precio de la caja.
    lineas = models.JSONField(default=list)
    subtotal_productos = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                             help_text="Suma de los productos con IVA, sin envío.")

    # Se llenan al cobrar.
    factura = models.OneToOneField("ventas.FacturaVenta", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="pedido_web")
    envio_gratis = models.BooleanField(default=False, help_text="¿El envío de este pedido lo pagó la tienda?")
    envio_costo = models.DecimalField("costo del envío para la tienda (₡)", max_digits=12, decimal_places=2,
                                      default=0, help_text="Lo que se le pagó al mensajero.")
    concretado_en = models.DateTimeField(null=True, blank=True)
    cancelado_en = models.DateTimeField(null=True, blank=True)
    motivo_cancelacion = models.CharField(max_length=200, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "pedido web por confirmar"
        verbose_name_plural = "pedidos web por confirmar"
        ordering = ["-creado_en"]
        indexes = [models.Index(fields=["empresa", "estado", "creado_en"], name="pedweb_emp_est_fecha_idx")]

    def __str__(self):
        return f"{self.numero} — {self.cliente_nombre} ({self.get_estado_display()})"
