from django.conf import settings
from django.db import models

from core.models import Empresa


class CuentaContable(models.Model):
    """Catálogo de cuentas jerárquico. El primer dígito indica la naturaleza
    (1 activo, 2 pasivo, 3 patrimonio, 4 ingreso, 5 gasto), estándar PYME CR."""

    class Naturaleza(models.TextChoices):
        ACTIVO = "A", "Activo"
        PASIVO = "P", "Pasivo"
        PATRIMONIO = "Q", "Patrimonio"
        INGRESO = "I", "Ingreso"
        GASTO = "G", "Gasto"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="cuentas")
    codigo = models.CharField(max_length=12)
    nombre = models.CharField(max_length=120)
    naturaleza = models.CharField(max_length=1, choices=Naturaleza.choices)
    padre = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="hijas")
    movimiento = models.BooleanField(default=True, help_text="Si acepta asientos directos (cuenta de detalle)")

    class Meta:
        verbose_name = "cuenta contable"
        verbose_name_plural = "cuentas contables"
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "codigo"], name="cuenta_codigo_unico"),
        ]

    def __str__(self):
        return f"{self.codigo} {self.nombre}"


class Asiento(models.Model):
    """Asiento del libro diario. Nace SOLO del motor contable a partir de
    operaciones reales (ventas, costos, cobros); los usuarios no lo digitan.
    Inmutable: los errores se corrigen con un asiento de reversa."""

    class Origen(models.TextChoices):
        VENTA = "VEN", "Venta"
        COSTO = "COS", "Costo de venta"
        COBRO = "COB", "Cobro (abono CxC)"
        ANULACION = "ANU", "Anulación"
        MANUAL = "MAN", "Manual"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="asientos")
    numero = models.CharField(max_length=20, unique=True)
    fecha = models.DateField()
    descripcion = models.CharField(max_length=200)
    origen = models.CharField(max_length=3, choices=Origen.choices)
    referencia = models.CharField(max_length=40, blank=True, help_text="Documento que lo originó")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.numero} — {self.descripcion}"

    @property
    def total_debe(self):
        return sum((l.debe for l in self.lineas.all()), 0)

    @property
    def total_haber(self):
        return sum((l.haber for l in self.lineas.all()), 0)

    @property
    def cuadra(self):
        return self.total_debe == self.total_haber


class CierrePeriodo(models.Model):
    """Cierre de período contable. Cerrar 'hasta el DD/MM/AAAA' bloquea el
    registro de cualquier asiento con fecha igual o anterior: nadie puede meter
    una venta o compra con fecha vieja y distorsionar lo que ya se declaró a
    Hacienda. Cubre cierres mensuales o trimestrales con un solo mecanismo.

    Para corregir un error real, un gerente puede reabrir (marca activo=False y
    deja quién/cuándo/por qué). La fecha de bloqueo vigente es la mayor
    fecha_cierre entre los cierres activos."""

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="cierres")
    fecha_cierre = models.DateField(help_text="Se bloquea todo lo que tenga esta fecha o anterior")
    nota = models.CharField(max_length=200, blank=True, help_text="Ej. 'IVA I trimestre declarado'")
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cierres_hechos",
    )
    cerrado_en = models.DateTimeField(auto_now_add=True)
    # Reapertura auditada
    activo = models.BooleanField(default=True)
    reabierto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cierres_reabiertos",
    )
    reabierto_en = models.DateTimeField(null=True, blank=True)
    motivo_reapertura = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "cierre de período"
        verbose_name_plural = "cierres de período"
        ordering = ["-fecha_cierre", "-id"]

    def __str__(self):
        estado = "activo" if self.activo else "reabierto"
        return f"Cierre hasta {self.fecha_cierre:%d/%m/%Y} ({estado})"


class LineaAsiento(models.Model):
    asiento = models.ForeignKey(Asiento, on_delete=models.CASCADE, related_name="lineas")
    cuenta = models.ForeignKey(CuentaContable, on_delete=models.PROTECT, related_name="movimientos")
    debe = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    haber = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    detalle = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "línea de asiento"
        verbose_name_plural = "líneas de asiento"
        constraints = [
            # Una línea es o débito o crédito, nunca ambos ni ninguno; sin negativos.
            models.CheckConstraint(
                condition=(
                    (models.Q(debe__gt=0) & models.Q(haber=0))
                    | (models.Q(haber__gt=0) & models.Q(debe=0))
                ),
                name="linea_debe_o_haber",
            ),
        ]

    def __str__(self):
        return f"{self.cuenta.codigo} D:{self.debe} H:{self.haber}"
