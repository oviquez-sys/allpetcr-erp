from django.conf import settings
from django.db import models

from catalogo.models import Producto
from core.models import Sucursal


class Bodega(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="bodegas")
    nombre = models.CharField(max_length=80)
    # Auditoría 2026-07-28, hallazgo BE-09.
    #
    # Las ventas y las anulaciones descontaban de `Bodega.objects.filter(
    # sucursal=...).first()`: la primera que apareciera. Con una sola bodega
    # por sucursal funciona, pero el supuesto estaba implícito en el código y
    # nada lo garantizaba. El día que una sucursal tenga bodega principal y
    # bodega de exhibición, el POS descontaría de la que el ORM devolviera
    # primero —sin avisar y sin forma de notarlo hasta cuadrar inventario—.
    #
    # Ahora el supuesto es explícito y verificable: cada sucursal declara cuál
    # es su bodega principal, y una restricción de base de datos impide que
    # haya dos.
    principal = models.BooleanField(
        default=False,
        verbose_name="bodega principal",
        help_text="De esta bodega salen las ventas. Solo puede haber una por sucursal.",
    )

    class Meta:
        verbose_name_plural = "bodegas"
        constraints = [
            models.UniqueConstraint(
                fields=["sucursal"],
                condition=models.Q(principal=True),
                name="una_sola_bodega_principal_por_sucursal",
            )
        ]

    def __str__(self):
        return f"{self.nombre} — {self.sucursal.nombre}"

    @classmethod
    def principal_de(cls, sucursal):
        """Bodega de la que salen las ventas de esa sucursal.

        Si ninguna está marcada como principal —bases creadas antes de este
        campo, o una sucursal nueva sin configurar— se cae a la primera, que
        es el comportamiento histórico. Así nada se rompe al actualizar; lo
        que se gana es que cuando alguien marque la principal, se respete.
        """
        return (
            cls.objects.filter(sucursal=sucursal, principal=True).first()
            or cls.objects.filter(sucursal=sucursal).order_by("id").first()
        )


class MovimientoInventario(models.Model):
    """Kardex inmutable. Cada fila nace de un documento u operación y guarda
    el costo promedio y stock RESULTANTES: el historial completo es auditable
    sin recalcular. No se edita ni se borra; los errores se corrigen con un
    movimiento de ajuste inverso."""

    class Tipo(models.TextChoices):
        CARGA_INICIAL = "INI", "Carga inicial"
        COMPRA = "COM", "Compra"
        VENTA = "VEN", "Venta"
        REGALIA = "REG", "Regalía / promoción"
        DEVOLUCION = "DEV", "Devolución / anulación"
        AJUSTE = "AJU", "Ajuste"
        TRANSFERENCIA = "TRA", "Transferencia"

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="kardex")
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, help_text="Positiva entra, negativa sale")
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    costo_promedio_resultante = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_resultante = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    referencia = models.CharField(max_length=80, blank=True, help_text="Documento origen (factura, OC, ajuste)")
    motivo = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de inventario"
        verbose_name_plural = "movimientos de inventario"
        ordering = ["-fecha", "-id"]
        indexes = [
            # El kardex será la tabla más grande del sistema. El índice
            # compuesto (producto, fecha) es exactamente el patrón de "ver el
            # historial de este producto", la consulta más frecuente a futuro.
            models.Index(fields=["producto", "fecha"], name="kardex_prod_fecha_idx"),
            models.Index(fields=["fecha"], name="kardex_fecha_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=~models.Q(cantidad=0), name="cantidad_distinta_de_cero"),
            models.CheckConstraint(condition=models.Q(stock_resultante__gte=0), name="kardex_stock_no_negativo"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.cantidad:+} × {self.producto.sku} ({self.referencia})"


class Agotamiento(models.Model):
    """Aviso de que un producto que SÍ tuvo existencia se quedó en cero.

    Pedido de Oscar (02/10/2026): cuando algo se agota por una venta, una
    regalía o lo que sea, tiene que saltar un aviso visible y quedar en una
    lista con el código del proveedor, para decidir si se vuelve a pedir o no
    se compra más. La decisión es del negocio; el sistema solo se encarga de
    que ningún agotado pase sin que alguien lo vea.

    Por qué un modelo y no solo "productos con stock 0": la regla del 02/08
    esconde de todas las pantallas lo que no tiene existencia, así que un
    agotado desaparece sin ruido. Además hay que guardar la decisión que se
    tomó y cuándo se agotó, cosas que el stock no sabe.

    Lo crea y lo cierra `inventario.services.registrar_movimiento` —la única
    puerta del stock—, así que no hay forma de vaciar un producto sin que
    quede el aviso. Uno abierto por producto a la vez; los viejos quedan como
    historia ("se agotó tres veces este año" también es un dato para decidir).
    """

    class Decision(models.TextChoices):
        PENDIENTE = "PEN", "Por decidir"
        PEDIR = "PED", "Volver a pedir"
        NO_COMPRAR = "NO", "No comprar más"

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="agotamientos")
    # El movimiento que lo dejó en cero: de ahí sale cómo salió (venta,
    # regalía, ajuste) y con qué documento. Puede faltar en los avisos que se
    # crearon para lo que ya estaba agotado antes de existir esta función.
    movimiento = models.ForeignKey(
        MovimientoInventario, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tipo_salida = models.CharField(max_length=3, choices=MovimientoInventario.Tipo.choices, blank=True)
    fecha = models.DateTimeField(help_text="Cuándo quedó en cero")
    decision = models.CharField(max_length=3, choices=Decision.choices, default=Decision.PENDIENTE)
    nota = models.CharField(max_length=200, blank=True)
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decidido_en = models.DateTimeField(null=True, blank=True)
    # Se llena solo cuando vuelve a haber existencia (compra, devolución,
    # ajuste). Mientras esté vacío, el aviso sigue abierto.
    repuesto_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "producto agotado"
        verbose_name_plural = "productos agotados"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["producto"],
                condition=models.Q(repuesto_en__isnull=True),
                name="un_agotamiento_abierto_por_producto",
            )
        ]

    def __str__(self):
        return f"{self.producto.sku} agotado el {self.fecha:%d/%m/%Y}"
