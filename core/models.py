from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class Empresa(models.Model):
    """Raíz del multi-empresa. El régimen fiscal condiciona impuestos y
    asientos (motor fiscal, Fase 2 §6): nada de tarifas fijas en código."""

    class Regimen(models.TextChoices):
        SIMPLIFICADO = "RTS", "Régimen de Tributación Simplificada"
        TRADICIONAL = "TRAD", "Régimen tradicional (IVA + FE v4.4)"

    nombre = models.CharField(max_length=120)
    regimen = models.CharField(max_length=4, choices=Regimen.choices, default=Regimen.SIMPLIFICADO)
    regimen_vigente_desde = models.DateField(null=True, blank=True)
    moneda = models.CharField(max_length=3, default="CRC")
    # Factor del Régimen de Tributación Simplificada: Hacienda lo fija por
    # actividad (decreto). El impuesto trimestral se estima multiplicando las
    # compras del trimestre por este factor. Se deja configurable porque cambia
    # por decreto y por rubro; el contador lo confirma en TRIBU-CR. 0 = sin
    # definir (los reportes solo muestran la base de compras).
    factor_rts = models.DecimalField(
        max_digits=6, decimal_places=4, default=0,
        help_text="Factor RTS que Hacienda asigna a tu actividad (ej. 0.02 = 2% de las compras). "
                  "Confirmalo con tu contador o en TRIBU-CR. 0 si aún no lo sabés.",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "empresas"

    def __str__(self):
        return self.nombre


class Sucursal(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="sucursales")
    nombre = models.CharField(max_length=120)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "sucursales"

    def __str__(self):
        return self.nombre


class AuditLog(models.Model):
    """Bitácora inmutable: quién, cuándo, desde dónde, qué cambió."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    ip = models.GenericIPAddressField(null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)
    tabla = models.CharField(max_length=80)
    objeto_id = models.CharField(max_length=40)
    accion = models.CharField(max_length=10)  # crear / editar / borrar
    antes = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    despues = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.fecha:%d/%m %H:%M} {self.accion} {self.tabla}#{self.objeto_id}"
