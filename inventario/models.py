from django.conf import settings
from django.db import models

from catalogo.models import Producto
from core.models import Sucursal


class Bodega(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="bodegas")
    nombre = models.CharField(max_length=80)

    class Meta:
        verbose_name_plural = "bodegas"

    def __str__(self):
        return f"{self.nombre} — {self.sucursal.nombre}"


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
