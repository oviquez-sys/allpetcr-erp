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
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "línea de compra"
        verbose_name_plural = "líneas de compra"
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_compra_positiva"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.producto.nombre}"
