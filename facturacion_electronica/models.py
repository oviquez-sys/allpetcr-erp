"""Modelos de facturación electrónica v4.4 — Bloque 4, 2026-08-28.

LEER ANTES DE TOCAR ESTE ARCHIVO
=================================
Esta app construye SOLO modelos, estados y el flujo de envío. **No genera
XML** porque el Anexo de Estructuras v4.4 y los XSD oficiales de Hacienda no
están en el repositorio (se buscaron en todo el proyecto, no solo acá).
Ver `REPORTE-NOCHE.md` para la lista exacta de qué descargar y dónde
ponerlo antes de escribir el generador.

Por qué esto no bloquea el resto del ERP
-----------------------------------------
Hoy la empresa opera en Régimen Simplificado (`Empresa.regimen == 'RTS'`),
que NO emite comprobante electrónico (ver `catalogo.Impuesto` y
`HALLAZGOS.md`). Estos modelos quedan APAGADOS por defecto: no los crea
ni los usa ningún flujo de venta existente. Son la preparación para el día
que el negocio pase a régimen tradicional — el propio `core.Empresa.Regimen`
ya tenía ese cambio anotado ("IVA + FE v4.4") antes de esta noche.

Por qué `clave` y `numero_interno` son texto
----------------------------------------------
Regla no negociable del proyecto: la clave del comprobante y las
identificaciones se guardan como TEXTO. Hacienda ya permite claves
alfanuméricas y, en el 4.º trimestre de 2026, las cédulas jurídicas pasan a
un formato alfanumérico de seis caracteres. Modelarlo como entero obligaría
a rehacerlo en pocos meses.

`clave` queda VACÍA hasta que exista el generador real: no se inventa su
formato (50 caracteres con una estructura exacta que define el Anexo) sin
el documento oficial delante. `numero_interno` SÍ se genera ya —es un
consecutivo interno del ERP, no el consecutivo de 20 dígitos que Hacienda
exige incrustado en la clave, cuya estructura tampoco se inventa acá—, y
sirve para tener trazabilidad y probar la regla de unicidad bajo
concurrencia (ítem 23) sin depender de la parte que falta.
"""
from django.conf import settings
from django.db import models

from core.models import Empresa
from ventas.models import Consecutivo, FacturaVenta


class TipoComprobante(models.TextChoices):
    FACTURA = "FE", "Factura electrónica"
    TIQUETE = "TE", "Tiquete electrónico"
    NOTA_CREDITO = "NC", "Nota de crédito electrónica"
    NOTA_DEBITO = "ND", "Nota de débito electrónica"
    RECIBO_PAGO = "REP", "Recibo electrónico de pago"


class EstadoComprobante(models.TextChoices):
    PENDIENTE_FIRMA = "PEF", "Pendiente de firma"
    FIRMADO = "FIR", "Firmado, pendiente de envío"
    ENVIADO = "ENV", "Enviado, sin respuesta de Hacienda"
    ACEPTADO = "ACE", "Aceptado por Hacienda"
    RECHAZADO = "REC", "Rechazado por Hacienda"
    ERROR_ENVIO = "ERR", "Reintentos agotados, requiere atención manual"


class ComprobanteElectronico(models.Model):
    """Campos comunes a los cinco tipos de comprobante. Abstracta: cada
    tipo concreto (ver abajo) es su propia tabla con su propia numeración,
    porque cada uno se numera con una serie de Hacienda independiente."""

    TIPO: str = ""  # cada subclase concreta lo fija (usado por Consecutivo.tomar)
    MAXIMO_REINTENTOS = 5

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="+")
    numero_interno = models.CharField(
        max_length=20, unique=True,
        help_text="Consecutivo interno del ERP (texto). NO es el consecutivo "
                  "de 20 dígitos que exige la clave de Hacienda.",
    )
    clave = models.CharField(
        max_length=50, blank=True,
        help_text="Clave del comprobante ante Hacienda. Vacía hasta que exista "
                  "el generador de XML (requiere el Anexo v4.4 + XSD oficiales).",
    )
    estado = models.CharField(max_length=3, choices=EstadoComprobante.choices, default=EstadoComprobante.PENDIENTE_FIRMA)

    # Firma XAdES-EPES: el PUNTO DE CONEXIÓN existe (ver
    # facturacion_electronica/services.py::firmar_xades_epes), la carga real
    # del .p12 es configuración pendiente (HACIENDA_P12_PATH / _PASSWORD).
    firmado_en = models.DateTimeField(null=True, blank=True)

    # Envío asíncrono: el comprobante NO es válido por haberse enviado, solo
    # por haber sido ACEPTADO (ver la propiedad `valido` abajo).
    intentos_envio = models.PositiveIntegerField(default=0)
    ultimo_intento_en = models.DateTimeField(null=True, blank=True)
    mensaje_hacienda = models.TextField(blank=True, help_text="Detalle de aceptación o rechazo, tal cual lo devuelve Hacienda")
    fecha_aceptacion = models.DateTimeField(null=True, blank=True)

    # Conservación del XML (ítem 26). Rutas relativas, guardadas con el
    # mismo `default_storage` configurable por variable de entorno que ya
    # usan las fotos de producto (ver core/imagenes.py y
    # config/settings.py::MEDIA_STORAGE_BACKEND): local en desarrollo,
    # S3-compatible en producción sin cambiar código.
    ruta_xml_firmado = models.CharField(max_length=250, blank=True)
    ruta_xml_respuesta_hacienda = models.CharField(max_length=250, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.TIPO} {self.numero_interno} ({self.get_estado_display()})"

    @property
    def valido(self):
        """Un comprobante enviado no es válido todavía: solo lo es cuando
        Hacienda respondió aceptándolo (ítem 25)."""
        return self.estado == EstadoComprobante.ACEPTADO

    @property
    def puede_reintentar(self):
        return self.estado in (EstadoComprobante.ENVIADO, EstadoComprobante.ERROR_ENVIO) and \
            self.intentos_envio < self.MAXIMO_REINTENTOS


class FacturaElectronica(ComprobanteElectronico):
    TIPO = TipoComprobante.FACTURA
    factura_venta = models.OneToOneField(FacturaVenta, on_delete=models.PROTECT, related_name="factura_electronica")

    class Meta:
        verbose_name = "factura electrónica"
        verbose_name_plural = "facturas electrónicas"


class TiqueteElectronico(ComprobanteElectronico):
    """Para venta a consumidor final sin identificación (no requiere la
    cédula del cliente, a diferencia de la factura electrónica)."""

    TIPO = TipoComprobante.TIQUETE
    factura_venta = models.OneToOneField(FacturaVenta, on_delete=models.PROTECT, related_name="tiquete_electronico")

    class Meta:
        verbose_name = "tiquete electrónico"
        verbose_name_plural = "tiquetes electrónicos"


class NotaCreditoElectronica(ComprobanteElectronico):
    """Corrige un comprobante ya emitido (FE o TE) — devolución, error de
    monto, anulación fiscal. Referencia a UNO de los dos, nunca ninguno ni
    los dos (constraint abajo)."""

    TIPO = TipoComprobante.NOTA_CREDITO
    factura_electronica = models.ForeignKey(
        FacturaElectronica, null=True, blank=True, on_delete=models.PROTECT, related_name="notas_credito",
    )
    tiquete_electronico = models.ForeignKey(
        TiqueteElectronico, null=True, blank=True, on_delete=models.PROTECT, related_name="notas_credito",
    )
    motivo = models.CharField(max_length=200)

    class Meta:
        verbose_name = "nota de crédito electrónica"
        verbose_name_plural = "notas de crédito electrónicas"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(factura_electronica__isnull=False, tiquete_electronico__isnull=True)
                    | models.Q(factura_electronica__isnull=True, tiquete_electronico__isnull=False)
                ),
                name="nc_referencia_exactamente_un_comprobante",
            ),
        ]


class NotaDebitoElectronica(ComprobanteElectronico):
    """Igual que la nota de crédito pero para AUMENTAR lo facturado (un
    cobro que quedó de menos, un cargo adicional)."""

    TIPO = TipoComprobante.NOTA_DEBITO
    factura_electronica = models.ForeignKey(
        FacturaElectronica, null=True, blank=True, on_delete=models.PROTECT, related_name="notas_debito",
    )
    tiquete_electronico = models.ForeignKey(
        TiqueteElectronico, null=True, blank=True, on_delete=models.PROTECT, related_name="notas_debito",
    )
    motivo = models.CharField(max_length=200)

    class Meta:
        verbose_name = "nota de débito electrónica"
        verbose_name_plural = "notas de débito electrónicas"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(factura_electronica__isnull=False, tiquete_electronico__isnull=True)
                    | models.Q(factura_electronica__isnull=True, tiquete_electronico__isnull=False)
                ),
                name="nd_referencia_exactamente_un_comprobante",
            ),
        ]


class ReciboElectronicoPago(ComprobanteElectronico):
    """Confirma el pago de una factura electrónica que se vendió a crédito.
    Siempre referencia una FE (no un tiquete: el tiquete es de contado)."""

    TIPO = TipoComprobante.RECIBO_PAGO
    factura_electronica = models.ForeignKey(FacturaElectronica, on_delete=models.PROTECT, related_name="recibos_pago")
    monto = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "recibo electrónico de pago"
        verbose_name_plural = "recibos electrónicos de pago"
