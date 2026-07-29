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
