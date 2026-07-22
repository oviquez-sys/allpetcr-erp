from django.conf import settings
from django.db import models

from core.models import Sucursal


class SesionCaja(models.Model):
    """Turno de caja: abre con un monto contado, acumula movimientos y
    cierra con arqueo (contado vs. esperado). Inmutable tras el cierre."""

    class Estado(models.TextChoices):
        ABIERTA = "ABI", "Abierta"
        CERRADA = "CER", "Cerrada"

    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="sesiones_caja")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sesiones_caja")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.ABIERTA)
    monto_apertura = models.DecimalField(max_digits=12, decimal_places=2)
    abierta_en = models.DateTimeField(auto_now_add=True)
    monto_esperado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_contado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "sesión de caja"
        verbose_name_plural = "sesiones de caja"
        ordering = ["-abierta_en"]

    def __str__(self):
        return f"Caja #{self.pk} — {self.usuario.username} ({self.get_estado_display()})"


class MovimientoCaja(models.Model):
    """Movimiento de efectivo dentro de una sesión. Monto con signo:
    positivo entra, negativo sale. Inmutable."""

    class Tipo(models.TextChoices):
        APERTURA = "APE", "Apertura"
        VENTA = "VEN", "Venta en efectivo"
        INGRESO = "ING", "Ingreso manual"
        EGRESO = "EGR", "Egreso manual"
        ANULACION = "ANU", "Devolución por anulación"

    sesion = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    descripcion = models.CharField(max_length=200, blank=True)
    referencia = models.CharField(max_length=40, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de caja"
        verbose_name_plural = "movimientos de caja"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(monto=0), name="monto_caja_distinto_de_cero"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.monto} ({self.referencia})"
