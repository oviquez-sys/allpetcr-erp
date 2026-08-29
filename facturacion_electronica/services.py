"""Flujo de facturación electrónica: numeración, firma y envío.

Ver el encabezado de `models.py` antes de tocar este archivo — en
particular, por qué NO hay ningún generador de XML acá.
"""
import os

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from ventas.models import Consecutivo

from .models import ComprobanteElectronico, EstadoComprobante

CARPETA_COMPROBANTES = "comprobantes_electronicos"


class ConfiguracionPendiente(Exception):
    """La operación no se puede hacer todavía porque falta configurar algo
    (la llave .p12, el generador de XML). No es un error del código: es un
    trámite pendiente de Oscar. Ver REPORTE-NOCHE.md."""


@transaction.atomic
def _crear_comprobante(modelo, empresa, **campos):
    """Numera (consecutivo interno, único bajo concurrencia — ítem 23,
    reutiliza el mismo Consecutivo que ya usan FacturaVenta y Compra) y crea
    el comprobante en PENDIENTE_FIRMA."""
    numero_interno = Consecutivo.tomar(empresa, modelo.TIPO)
    return modelo.objects.create(empresa=empresa, numero_interno=numero_interno, **campos)


def crear_factura_electronica(factura_venta):
    from .models import FacturaElectronica
    return _crear_comprobante(FacturaElectronica, factura_venta.empresa, factura_venta=factura_venta)


def crear_tiquete_electronico(factura_venta):
    from .models import TiqueteElectronico
    return _crear_comprobante(TiqueteElectronico, factura_venta.empresa, factura_venta=factura_venta)


def crear_nota_credito(*, empresa, motivo, factura_electronica=None, tiquete_electronico=None):
    from .models import NotaCreditoElectronica
    if bool(factura_electronica) == bool(tiquete_electronico):
        raise ValidationError("La nota de crédito debe referenciar exactamente un comprobante (factura O tiquete).")
    return _crear_comprobante(
        NotaCreditoElectronica, empresa, motivo=motivo,
        factura_electronica=factura_electronica, tiquete_electronico=tiquete_electronico,
    )


def crear_nota_debito(*, empresa, motivo, factura_electronica=None, tiquete_electronico=None):
    from .models import NotaDebitoElectronica
    if bool(factura_electronica) == bool(tiquete_electronico):
        raise ValidationError("La nota de débito debe referenciar exactamente un comprobante (factura O tiquete).")
    return _crear_comprobante(
        NotaDebitoElectronica, empresa, motivo=motivo,
        factura_electronica=factura_electronica, tiquete_electronico=tiquete_electronico,
    )


def crear_recibo_pago(*, factura_electronica, monto):
    from .models import ReciboElectronicoPago
    return _crear_comprobante(
        ReciboElectronicoPago, factura_electronica.empresa,
        factura_electronica=factura_electronica, monto=monto,
    )


# ─────────────────────────────────────────────────────────────────────────
#  Firma XAdES-EPES — PUNTO DE CONEXIÓN (ítem 24)
# ─────────────────────────────────────────────────────────────────────────
def firmar_xades_epes(comprobante: ComprobanteElectronico):
    """Punto único por el que cualquier comprobante se firma.

    La carga de la llave criptográfica (.p12) es CONFIGURACIÓN PENDIENTE a
    propósito: se lee de `HACIENDA_P12_PATH` / `HACIENDA_P12_PASSWORD` y,
    si no están definidas, esta función avisa con claridad en vez de fallar
    con un traceback de "archivo no encontrado". Cuando exista el .p12 real
    Y el generador de XML (que necesita el Anexo v4.4 + XSD, ver
    REPORTE-NOCHE.md), acá adentro va la firma XAdES-EPES de verdad —no
    antes: firmar un XML que no se generó correctamente no tiene sentido.
    """
    ruta_p12 = os.environ.get("HACIENDA_P12_PATH")
    clave_p12 = os.environ.get("HACIENDA_P12_PASSWORD")
    if not ruta_p12 or not clave_p12:
        raise ConfiguracionPendiente(
            "Falta configurar la llave criptográfica de Hacienda. Definí "
            "HACIENDA_P12_PATH (ruta al archivo .p12) y HACIENDA_P12_PASSWORD "
            "en el entorno. Sin eso no se puede firmar ningún comprobante."
        )
    raise ConfiguracionPendiente(
        "El generador de XML todavía no existe (falta el Anexo de "
        "Estructuras v4.4 y los XSD oficiales de Hacienda — ver "
        "REPORTE-NOCHE.md). Sin el XML correcto no hay nada que firmar."
    )


# ─────────────────────────────────────────────────────────────────────────
#  Envío asíncrono (ítem 25): el comprobante solo es válido cuando Hacienda
#  responde ACEPTADO. Enviarlo no lo vuelve válido — ver
#  ComprobanteElectronico.valido en models.py.
# ─────────────────────────────────────────────────────────────────────────
def enviar_a_hacienda(comprobante: ComprobanteElectronico):
    """Marca el intento de envío. NO llama a Hacienda de verdad todavía
    (no hay XML firmado que enviar — ver `firmar_xades_epes`); lo que sí
    implementa de verdad es el ESTADO del flujo: cuántos intentos lleva,
    cuándo fue el último, y cuándo se agotan los reintentos.

    Ojo con dónde se lanza el ValidationError de reintentos agotados: tiene
    que ser DESPUÉS de que la transacción que guarda ERROR_ENVIO ya haya
    salido del `with` y confirmado — lanzar la excepción todavía adentro de
    `transaction.atomic()` revierte también ese guardado, y el comprobante
    quedaría en ENVIADO en vez de ERROR_ENVIO aunque el mensaje de error
    diga lo contrario.
    """
    tipo = type(comprobante)
    with transaction.atomic():
        comprobante = tipo.objects.select_for_update().get(pk=comprobante.pk)
        if comprobante.estado not in (EstadoComprobante.FIRMADO, EstadoComprobante.ENVIADO, EstadoComprobante.ERROR_ENVIO):
            raise ValidationError(
                f"No se puede enviar un comprobante en estado '{comprobante.get_estado_display()}'."
            )
        reintentos_agotados = comprobante.intentos_envio >= comprobante.MAXIMO_REINTENTOS
        if reintentos_agotados:
            comprobante.estado = EstadoComprobante.ERROR_ENVIO
            comprobante.save(update_fields=["estado"])
        else:
            comprobante.estado = EstadoComprobante.ENVIADO
            comprobante.intentos_envio += 1
            comprobante.ultimo_intento_en = timezone.now()
            comprobante.save(update_fields=["estado", "intentos_envio", "ultimo_intento_en"])

    if reintentos_agotados:
        raise ValidationError(
            f"Se agotaron los {comprobante.MAXIMO_REINTENTOS} reintentos de envío de "
            f"{comprobante.numero_interno}. Requiere revisión manual."
        )
    return comprobante


@transaction.atomic
def registrar_respuesta_hacienda(comprobante: ComprobanteElectronico, *, aceptado: bool, mensaje: str = ""):
    """Aplica la respuesta de Hacienda cuando llega (vía consulta periódica
    o webhook, según se implemente el día que haya API real de Hacienda
    conectada). Este es el ÚNICO lugar que marca un comprobante ACEPTADO."""
    tipo = type(comprobante)
    comprobante = tipo.objects.select_for_update().get(pk=comprobante.pk)
    if comprobante.estado != EstadoComprobante.ENVIADO:
        raise ValidationError(
            f"No se puede registrar una respuesta de Hacienda para un comprobante "
            f"en estado '{comprobante.get_estado_display()}' (debe estar ENVIADO)."
        )
    comprobante.estado = EstadoComprobante.ACEPTADO if aceptado else EstadoComprobante.RECHAZADO
    comprobante.mensaje_hacienda = mensaje
    if aceptado:
        comprobante.fecha_aceptacion = timezone.now()
    comprobante.save(update_fields=["estado", "mensaje_hacienda", "fecha_aceptacion"])
    return comprobante


# ─────────────────────────────────────────────────────────────────────────
#  Conservación del XML (ítem 26)
# ─────────────────────────────────────────────────────────────────────────
def guardar_xml_firmado(comprobante: ComprobanteElectronico, contenido: bytes) -> str:
    ruta = f"{CARPETA_COMPROBANTES}/{comprobante.TIPO}/{comprobante.numero_interno}.xml"
    ruta_guardada = default_storage.save(ruta, ContentFile(contenido))
    comprobante.ruta_xml_firmado = ruta_guardada
    comprobante.firmado_en = timezone.now()
    comprobante.estado = EstadoComprobante.FIRMADO
    comprobante.save(update_fields=["ruta_xml_firmado", "firmado_en", "estado"])
    return ruta_guardada


def guardar_xml_respuesta(comprobante: ComprobanteElectronico, contenido: bytes) -> str:
    ruta = f"{CARPETA_COMPROBANTES}/{comprobante.TIPO}/{comprobante.numero_interno}-respuesta.xml"
    ruta_guardada = default_storage.save(ruta, ContentFile(contenido))
    comprobante.ruta_xml_respuesta_hacienda = ruta_guardada
    comprobante.save(update_fields=["ruta_xml_respuesta_hacienda"])
    return ruta_guardada
