from django.conf import settings
from django.db import models, transaction

from caja.models import SesionCaja
from catalogo.models import Producto
from core.models import Empresa, Sucursal


class Cliente(models.Model):
    """Cliente con control de crédito. `saldo` es denormalizado (lectura
    rápida); la fuente de verdad es la suma de documentos CxC pendientes."""

    class TipoIdentificacion(models.TextChoices):
        # Preparación para la factura electrónica (auditoría 26/09/2026,
        # FE-03): el receptor de una factura se identifica por tipo y número.
        # Los códigos oficiales de Hacienda se asignan al generar el XML, no
        # acá: así esta lista no depende de una versión del anexo técnico.
        FISICA = "FIS", "Cédula física"
        JURIDICA = "JUR", "Cédula jurídica"
        DIMEX = "DIM", "DIMEX"
        NITE = "NIT", "NITE"
        EXTRANJERO = "EXT", "Extranjero / pasaporte"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="clientes")
    nombre = models.CharField(max_length=150)
    tipo_identificacion = models.CharField(max_length=3, choices=TipoIdentificacion.choices, blank=True)
    identificacion = models.CharField(max_length=30, blank=True)
    provincia = models.CharField(max_length=40, blank=True)
    canton = models.CharField("cantón", max_length=60, blank=True)
    distrito = models.CharField(max_length=60, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    direccion = models.CharField(max_length=250, blank=True)
    notas = models.TextField(blank=True)
    limite_credito = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                         help_text="0 = no se le vende a crédito")
    saldo = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                help_text="Deuda pendiente (denormalizado)")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    @property
    def credito_disponible(self):
        return self.limite_credito - self.saldo


class Consecutivo(models.Model):
    """Numeración por empresa y tipo de documento. Se toma con bloqueo de
    fila: dos cajas nunca reciben el mismo número."""

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    tipo = models.CharField(max_length=4, default="FV")
    siguiente = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["empresa", "tipo"], name="consecutivo_unico"),
        ]

    @classmethod
    def tomar(cls, empresa, tipo="FV") -> str:
        with transaction.atomic():
            fila, _ = cls.objects.select_for_update().get_or_create(empresa=empresa, tipo=tipo)
            numero = fila.siguiente
            fila.siguiente = numero + 1
            fila.save(update_fields=["siguiente"])
        return f"{tipo}-{numero:08d}"


class FacturaVenta(models.Model):
    """Documento de venta. Inmutable una vez emitido: los errores se
    corrigen anulando (reversa de inventario y caja), nunca editando."""

    class Estado(models.TextChoices):
        EMITIDA = "EMI", "Emitida"
        ANULADA = "ANU", "Anulada"

    class MedioPago(models.TextChoices):
        EFECTIVO = "EFE", "Efectivo"
        TARJETA = "TAR", "Tarjeta"
        SINPE = "SIN", "SINPE Móvil"
        CREDITO = "CRE", "Crédito (CxC)"
        # Varios medios en la misma venta (auditoría 26/09/2026, VEN-04). El
        # detalle de cuánto entró por cada uno vive en PagoVenta; solo las
        # ventas mixtas tienen filas ahí, las de un solo medio siguen igual.
        MIXTO = "MIX", "Pago mixto"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT)
    sesion_caja = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name="ventas")
    numero = models.CharField(max_length=20, unique=True)
    cliente = models.ForeignKey(Cliente, null=True, blank=True, on_delete=models.PROTECT, related_name="compras")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.EMITIDA)
    medio_pago = models.CharField(max_length=3, choices=MedioPago.choices)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                    help_text="Suma de descuentos de las líneas")
    impuesto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    creado_en = models.DateTimeField(auto_now_add=True)
    motivo_anulacion = models.CharField(max_length=200, blank=True)
    anulada_en = models.DateTimeField(null=True, blank=True)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="ventas_anuladas")
    # Clave que el POS genera UNA vez por venta (auditoría 26/09/2026, VEN-02).
    # Si el mismo cobro llega dos veces —doble F1, un reintento de la red— la
    # segunda petición encuentra esta clave y devuelve la venta ya hecha en vez
    # de crear otra. Nula en las ventas anteriores y en las que no vienen del POS.
    clave_pos = models.CharField(max_length=40, null=True, blank=True, unique=True, editable=False)
    # Efectivo que entregó el cliente y vuelto que se le dio (VEN-03). Solo
    # informativos: la caja se mueve por lo cobrado, no por lo recibido.
    monto_recibido = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    vuelto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "factura de venta"
        verbose_name_plural = "facturas de venta"
        ordering = ["-id"]
        indexes = [
            # Todos los reportes de ventas filtran por fecha; sin índice, a
            # muchas filas cada reporte barre la tabla completa.
            models.Index(fields=["creado_en"], name="fv_creado_en_idx"),
            models.Index(fields=["empresa", "estado", "creado_en"], name="fv_emp_est_fecha_idx"),
        ]

    def __str__(self):
        return f"{self.numero} ({self.get_estado_display()}) ₡{self.total}"

    @property
    def estado_visual(self):
        """Estado para mostrar al cliente: Pagada / Pendiente / Anulada.

        FacturaVenta solo distingue Emitida/Anulada — "pagada" no es un campo
        propio, es "emitida y, si fue a crédito, ya sin saldo pendiente en su
        DocumentoCxC". Este helper traduce esa realidad para la factura a
        color, sin inventar un estado que el modelo no tiene.
        """
        if self.estado == self.Estado.ANULADA:
            return "ANU"
        cxc = getattr(self, "cxc", None)  # OneToOneField: no existe si fue de contado
        if cxc is not None and cxc.estado == cxc.Estado.PENDIENTE:
            return "PEN"
        return "PAG"

    ESTADO_VISUAL_LABEL = {"PAG": "Pagada", "PEN": "Pendiente", "ANU": "Anulada"}

    @property
    def estado_visual_display(self):
        return self.ESTADO_VISUAL_LABEL[self.estado_visual]

    def desglose_pagos(self):
        """[(medio, monto)] de esta venta. Una venta de un solo medio no tiene
        filas en PagoVenta: su único pago es el total."""
        if self.medio_pago == self.MedioPago.MIXTO:
            return [(p.medio, p.monto) for p in self.pagos.all()]
        return [(self.medio_pago, self.total)]


class PagoVenta(models.Model):
    """Una parte del cobro de una venta con pago mixto (VEN-04). Inmutable,
    igual que la factura."""

    factura = models.ForeignKey(FacturaVenta, on_delete=models.CASCADE, related_name="pagos")
    medio = models.CharField(max_length=3, choices=FacturaVenta.MedioPago.choices)
    monto = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "pago de venta"
        verbose_name_plural = "pagos de venta"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name="pago_venta_positivo"),
        ]

    def __str__(self):
        return f"{self.get_medio_display()} ₡{self.monto} ({self.factura.numero})"


class LineaVenta(models.Model):
    factura = models.ForeignKey(FacturaVenta, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    descuento_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                        help_text="Porcentaje de descuento (0-100)")
    descuento_monto = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                          help_text="Monto en colones aplicado (calculado automáticamente)")
    es_regalia = models.BooleanField(default=False,
                                     help_text="Producto entregado gratis: sin ingreso, pero su costo sale a gasto")
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    # Foto fiscal de la línea AL MOMENTO de la venta (auditoría 26/09/2026,
    # VEN-08 / FE-04). Antes solo la factura guardaba totales: si mañana cambia
    # la tarifa o el CABYS de un producto, las ventas viejas ya no se podrían
    # desglosar. Nulos en las ventas anteriores a este cambio.
    tarifa_iva = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                   help_text="Total de la línea sin IVA")
    impuesto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cabys = models.CharField(max_length=13, blank=True)

    class Meta:
        verbose_name = "línea de venta"
        verbose_name_plural = "líneas de venta"
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_venta_positiva"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.producto.nombre}"


class DocumentoCxC(models.Model):
    """Cuenta por cobrar generada por una venta a crédito. Su saldo baja con
    abonos hasta quedar en cero (pagada). Al anular la factura se cancela."""

    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Pendiente"
        PAGADO = "PAG", "Pagado"
        ANULADO = "ANU", "Anulado"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="cxc")
    factura = models.OneToOneField(FacturaVenta, on_delete=models.PROTECT, related_name="cxc")
    monto_original = models.DecimalField(max_digits=12, decimal_places=2)
    saldo = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "documento por cobrar"
        verbose_name_plural = "documentos por cobrar"
        ordering = ["-id"]

    def __str__(self):
        return f"CxC {self.factura.numero} — {self.cliente.nombre}: ₡{self.saldo}/{self.monto_original}"


class DevolucionVenta(models.Model):
    """Devolución PARCIAL de una venta: a diferencia de anular_factura (que
    revierte TODO el documento y lo marca ANULADA), una devolución no cambia
    el estado de la factura — puede devolverse días después, y solo algunos
    productos o algunas unidades, no necesariamente el tiquete completo."""

    factura = models.ForeignKey(FacturaVenta, on_delete=models.PROTECT, related_name="devoluciones")
    numero = models.CharField(max_length=20, unique=True)
    motivo = models.CharField(max_length=200)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                help_text="Monto reembolsado (no incluye líneas de regalía)")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "devolución de venta"
        verbose_name_plural = "devoluciones de venta"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.numero} — devolución de {self.factura.numero}"


class LineaDevolucion(models.Model):
    devolucion = models.ForeignKey(DevolucionVenta, on_delete=models.CASCADE, related_name="lineas")
    linea_venta = models.ForeignKey(LineaVenta, on_delete=models.PROTECT, related_name="devoluciones")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    monto = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "línea de devolución"
        verbose_name_plural = "líneas de devolución"
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cantidad_devolucion_positiva"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.linea_venta.producto.nombre} (devuelto)"


class Abono(models.Model):
    """Pago parcial o total de una cuenta por cobrar. Inmutable."""

    class Medio(models.TextChoices):
        EFECTIVO = "EFE", "Efectivo"
        TARJETA = "TAR", "Tarjeta"
        SINPE = "SIN", "SINPE Móvil"
        TRANSFERENCIA = "TRA", "Transferencia"

    documento = models.ForeignKey(DocumentoCxC, on_delete=models.PROTECT, related_name="abonos")
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    medio = models.CharField(max_length=3, choices=Medio.choices, default=Medio.EFECTIVO)
    referencia = models.CharField(max_length=60, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name="abono_positivo"),
        ]

    def __str__(self):
        return f"Abono ₡{self.monto} a {self.documento.factura.numero}"
