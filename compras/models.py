from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models

from catalogo.models import Producto
from core.models import Empresa, Sucursal


class Proveedor(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="proveedores")
    nombre = models.CharField(max_length=150)
    identificacion = models.CharField(max_length=30, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    notas = models.TextField(blank=True)
    saldo = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                help_text="Deuda con el proveedor (CxP, denormalizado)")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "proveedores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Compra(models.Model):
    """Compra a proveedor. Al recibirse entra al inventario (recalcula costo
    promedio) y genera su asiento. Cuenta para el monitor del límite RTS."""

    class Estado(models.TextChoices):
        BORRADOR = "BOR", "Borrador"
        RECIBIDA = "REC", "Recibida"
        ANULADA = "ANU", "Anulada"

    class Pago(models.TextChoices):
        CONTADO = "CON", "Contado (Bancos)"
        CREDITO = "CRE", "Crédito del proveedor (CxP)"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="compras")
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="compras")
    numero = models.CharField(max_length=20, unique=True)
    factura_proveedor = models.CharField(max_length=40, blank=True, help_text="N.º de factura del proveedor")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.BORRADOR)
    forma_pago = models.CharField(max_length=3, choices=Pago.choices, default=Pago.CONTADO)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    creado_en = models.DateTimeField(auto_now_add=True)
    recibida_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=200, blank=True)
    anulada_en = models.DateTimeField(null=True, blank=True)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="compras_anuladas")

    class Meta:
        verbose_name = "compra"
        verbose_name_plural = "compras"
        ordering = ["-id"]
        indexes = [
            # El monitor del RTS suma las compras recibidas del año en curso;
            # es la consulta del dashboard que más crece con el tiempo.
            models.Index(fields=["recibida_en"], name="compra_recibida_idx"),
            models.Index(fields=["empresa", "estado", "recibida_en"], name="compra_emp_est_rec_idx"),
        ]

    def __str__(self):
        return f"{self.numero} — {self.proveedor.nombre} ({self.get_estado_display()})"


class LineaCompra(models.Model):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, help_text="Unidades facturadas por el proveedor")
    # Bonificación del proveedor: los "12+1", "100+20" que ofrecen los
    # vendedores. Se guarda aparte de `cantidad` porque las dos cifras cumplen
    # papeles que se contradicen si se mezclan:
    #
    #   - La FACTURA solo reconoce las facturadas. De `cantidad × costo_unitario`
    #     sale `total`, y de ahí el asiento contable y la deuda con el
    #     proveedor. Meter las 13 unidades acá descuadraría los libros contra
    #     la factura que el proveedor va a cobrar.
    #   - La BODEGA recibe las 13. Registrar solo 12 dejaría una unidad
    #     entrando a la tienda sin existir en el sistema.
    #
    # Guardadas por separado, cada número va a donde corresponde y el costo
    # real por unidad sale solo (ver `costo_real_unitario`).
    cantidad_bonificada = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="cantidad bonificada",
        help_text="Unidades que el proveedor regala y no factura (el +1 de un 12+1).",
    )
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, help_text="Costo facturado por unidad")
    total = models.DecimalField(max_digits=12, decimal_places=2, help_text="Lo que cobra la factura: cantidad × costo_unitario")

    class Meta:
        verbose_name = "línea de compra"
        verbose_name_plural = "líneas de compra"
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_compra_positiva"),
            models.CheckConstraint(
                condition=models.Q(cantidad_bonificada__gte=0), name="bonificada_no_negativa"
            ),
        ]

    def __str__(self):
        if self.cantidad_bonificada:
            return f"{self.cantidad}+{self.cantidad_bonificada} × {self.producto.nombre}"
        return f"{self.cantidad} × {self.producto.nombre}"

    @property
    def cantidad_recibida(self):
        """Lo que de verdad entra a bodega: facturadas más bonificadas."""
        return self.cantidad + self.cantidad_bonificada

    @property
    def costo_real_unitario(self):
        """Lo que costó cada unidad recibida, con la bonificación repartida.

        Es el número que importa para poner precio. En un 12+1 a ₡1.000 el
        costo real no es ₡1.000: son ₡12.000 entre 13 unidades, o sea ₡923,08.
        Tratar la unidad bonificada como "regalo a costo cero" dejaría las
        otras doce valoradas a ₡1.000 y el inventario inflado en ₡1.000 —el
        sistema creería tener ₡13.000 de mercadería habiendo pagado ₡12.000—.
        """
        recibida = self.cantidad_recibida
        if recibida <= 0:
            return Decimal("0")
        return (self.total / recibida).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def descuento_efectivo_pct(self):
        """A cuánto equivale la bonificación como descuento, en porcentaje.

        Un 12+1 NO es 8,33% de descuento (1/12): es 7,69% (1/13), porque el
        descuento se mide sobre lo que recibís, no sobre lo que pagás. La
        diferencia importa al comparar la oferta de un proveedor contra el
        descuento por pronto pago de otro.
        """
        if not self.cantidad_bonificada or self.cantidad_recibida <= 0:
            return Decimal("0")
        return (self.cantidad_bonificada / self.cantidad_recibida * 100).quantize(Decimal("0.01"))
