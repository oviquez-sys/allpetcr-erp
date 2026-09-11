"""Cola de trabajos de impresión, para cuando el ERP no ve las impresoras.

POR QUÉ EXISTE (10/09/2026)
    Hasta el 09/09/2026 el ERP corría en la misma computadora que las
    impresoras de la tienda, así que imprimir era llamar a Windows y listo.
    Desde el despliegue en DigitalOcean el ERP corre en un servidor Linux en
    Nueva York: no ve —ni va a ver nunca— el USB del mostrador de Heredia.
    `impresion/windows.py` ya lo anticipaba en su comentario de cabecera.

    La solución es un agente: un programa chiquito que corre en la
    computadora de la tienda, le pregunta al ERP «¿hay algo que imprimir?» y
    lo manda a la impresora de al lado. Esta tabla es el buzón entre los dos.

    El ERP arma el trabajo completo —los bytes del tiquete, la imagen de la
    etiqueta— y el agente solo los entrega a la impresora. Así, el día que
    cambie el diseño de la etiqueta, se cambia en el servidor y no hay que ir
    a actualizar nada en la tienda.

POR QUÉ LOS TRABAJOS VENCEN
    Si la computadora de la tienda estuvo apagada toda la mañana y se
    enciende a mediodía, lo último que quiere el cajero es que salgan de
    golpe los treinta tiquetes de las ventas del día. Un tiquete que no se
    imprimió en el momento ya no sirve: la venta está registrada y el
    comprobante se puede volver a mandar a mano desde la factura. Por eso el
    trabajo se descarta solo pasado un rato.

UNA SOLA TIENDA, POR AHORA
    No hay campo de sucursal a propósito: hay un local y un agente. El día
    que haya un segundo local, acá va la sucursal y el agente se identifica
    con la suya al pedir trabajo.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class TrabajoImpresion(models.Model):
    """Un trabajo esperando a que el agente de la tienda lo imprima."""

    TIQUETE = "tiquete"
    ETIQUETA = "etiqueta"
    PRUEBA = "prueba"
    TIPOS = [
        (TIQUETE, "Tiquete de venta"),
        (ETIQUETA, "Etiqueta de producto"),
        (PRUEBA, "Impresión de prueba"),
    ]

    # `crudo` = los bytes van tal cual a la impresora (ESC/POS de la térmica).
    # `imagen` = es un PNG que el agente manda por el driver de Windows, que es
    # el único camino que funciona con la Xprinter XP-360B (ver windows.py).
    CRUDO = "crudo"
    IMAGEN = "imagen"
    FORMATOS = [
        (CRUDO, "Bytes crudos (ESC/POS)"),
        (IMAGEN, "Imagen por el driver"),
    ]

    PENDIENTE = "pendiente"
    TOMADO = "tomado"
    IMPRESO = "impreso"
    ERROR = "error"
    VENCIDO = "vencido"
    ESTADOS = [
        (PENDIENTE, "Esperando al agente"),
        (TOMADO, "El agente lo tomó"),
        (IMPRESO, "Impreso"),
        (ERROR, "Falló"),
        (VENCIDO, "Venció sin imprimirse"),
    ]

    tipo = models.CharField(max_length=12, choices=TIPOS)
    formato = models.CharField(max_length=8, choices=FORMATOS)
    impresora = models.CharField(
        max_length=120,
        help_text="Nombre de la cola en Windows, tal como la ve la computadora de la tienda.",
    )
    titulo = models.CharField(max_length=120, blank=True)
    contenido = models.BinaryField(
        help_text="Los bytes a imprimir: ESC/POS si el formato es crudo, PNG si es imagen.",
    )
    # Solo para el formato imagen: el tamaño del papel que hay que pedirle a
    # Windows. Van acá y no en la configuración del agente porque el tamaño es
    # del diseño de la etiqueta, no de la máquina.
    ancho_mm = models.FloatField(null=True, blank=True)
    alto_mm = models.FloatField(null=True, blank=True)

    estado = models.CharField(max_length=10, choices=ESTADOS, default=PENDIENTE)
    detalle = models.TextField(blank=True, help_text="El mensaje de error, si falló.")

    creado_en = models.DateTimeField(auto_now_add=True)
    vence_en = models.DateTimeField()
    tomado_en = models.DateTimeField(null=True, blank=True)
    terminado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "trabajo de impresión"
        verbose_name_plural = "trabajos de impresión"
        ordering = ["creado_en"]
        indexes = [
            # El agente pregunta por lo pendiente muchas veces por minuto.
            models.Index(fields=["estado", "creado_en"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.get_estado_display()}"

    def save(self, *args, **kwargs):
        if not self.vence_en:
            minutos = getattr(settings, "IMPRESION_VIGENCIA_MINUTOS", 15)
            self.vence_en = timezone.now() + timedelta(minutes=minutos)
        super().save(*args, **kwargs)

    @property
    def vencido(self) -> bool:
        return timezone.now() > self.vence_en
