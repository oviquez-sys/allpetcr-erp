from django.conf import settings
from django.db import models

from core.models import Empresa


class Categoria(models.Model):
    """Familia de productos (taxonomía limpia). La categoría original del
    Excel se conserva en Producto.categoria_original hasta depurarla."""

    nombre = models.CharField(max_length=80, unique=True)
    padre = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="hijas")

    class Meta:
        verbose_name_plural = "categorías"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Impuesto(models.Model):
    """Tarifas con vigencia, listas para cambios de Hacienda. En régimen
    simplificado la venta no desglosa impuesto: el motor fiscal decide."""

    nombre = models.CharField(max_length=60)
    tarifa = models.DecimalField(max_digits=5, decimal_places=2, help_text="Porcentaje, ej. 13.00")
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_hasta = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "impuestos"

    def __str__(self):
        return f"{self.nombre} ({self.tarifa}%)"


class Producto(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="productos")
    sku = models.CharField("código (REF)", max_length=30, unique=True)
    nombre = models.CharField(max_length=200)
    categoria = models.ForeignKey(Categoria, null=True, blank=True, on_delete=models.PROTECT, related_name="productos")
    categoria_original = models.CharField(max_length=120, blank=True, help_text="Categoría del Excel original, pendiente de depurar")
    codigo_barras = models.CharField(max_length=30, blank=True, db_index=True)
    presentacion = models.CharField(max_length=120, blank=True)
    imagen = models.CharField(max_length=200, blank=True, help_text="Ruta relativa dentro de media/ (ej. productos/75564.png)")
    impuesto = models.ForeignKey(Impuesto, null=True, blank=True, on_delete=models.PROTECT)
    # Costo y stock: denormalizados para lectura rápida.
    # La fuente de verdad es el kardex (inventario.MovimientoInventario).
    costo_promedio = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=2, default=2)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.CheckConstraint(condition=models.Q(precio_venta__gte=0), name="precio_no_negativo"),
            models.CheckConstraint(condition=models.Q(stock_actual__gte=0), name="stock_no_negativo"),
        ]

    def __str__(self):
        return f"{self.sku} — {self.nombre}"

    def save(self, *args, **kwargs):
        """Al crear un producto sin código de barras, se lo asigna solo usando
        el SKU (único). Así CUALQUIER producto nuevo queda listo para imprimir
        su etiqueta, sin importar por dónde se creó (Admin, Recibir mercadería o
        importación). No toca productos que ya traen código (p. ej. el EAN del
        proveedor), ni los ya existentes."""
        if self._state.adding and not self.codigo_barras and self.sku:
            base = codigo = str(self.sku).strip()
            n = 1
            while Producto.objects.filter(codigo_barras=codigo).exists():
                codigo = f"{base}-{n}"  # colisión rarísima: desambigua
                n += 1
            self.codigo_barras = codigo
        super().save(*args, **kwargs)

    @property
    def bajo_minimo(self):
        return self.stock_actual <= self.stock_minimo

    @property
    def margen_pct(self):
        """Margen de ganancia (%) sobre el precio de venta.
        Fórmula: ((PrecioVenta - Costo) / PrecioVenta) * 100
        Retorna Decimal con 2 decimales, o None si PrecioVenta es 0."""
        if self.precio_venta == 0:
            return None
        from decimal import Decimal
        margen = ((self.precio_venta - self.costo_promedio) / self.precio_venta) * Decimal('100')
        return round(margen, 2)

    @property
    def markup_pct(self):
        """Markup o recargo (%) sobre el costo.
        Fórmula: ((PrecioVenta - Costo) / Costo) * 100
        Retorna Decimal con 2 decimales, o None si Costo es 0."""
        if self.costo_promedio == 0:
            return None
        from decimal import Decimal
        markup = ((self.precio_venta - self.costo_promedio) / self.costo_promedio) * Decimal('100')
        return round(markup, 2)


class CambioPrecio(models.Model):
    """Bitácora inmutable de cada cambio manual del precio de venta: quién lo
    cambió, cuándo, de cuánto a cuánto y por qué. Un empleado no puede
    modificar precios en silencio; todo queda firmado. (El histórico del COSTO
    ya vive en el kardex: cada MovimientoInventario guarda el costo resultante.)"""

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="cambios_precio")
    valor_anterior = models.DecimalField(max_digits=12, decimal_places=2)
    valor_nuevo = models.DecimalField(max_digits=12, decimal_places=2)
    costo_al_momento = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Costo promedio del producto cuando se cambió el precio, para ver el margen histórico",
    )
    motivo = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "cambio de precio"
        verbose_name_plural = "cambios de precio"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.producto.sku}: ₡{self.valor_anterior} → ₡{self.valor_nuevo}"

    @property
    def variacion(self):
        """Diferencia absoluta (positiva sube, negativa baja)."""
        return self.valor_nuevo - self.valor_anterior
