"""Auditoría automática por señales del ORM.

Cada create/update/delete de los modelos listados en AUDITED escribe un
AuditLog con el estado anterior, el nuevo, el usuario y la IP de la
petición (vía core.middleware). Regla de la especificación: "todo cambio
debe quedar auditado" — sin que ningún módulo lo pida.

Qué cambió y por qué (auditoría 2026-07-28, hallazgos BE-01 y PERF-02)
---------------------------------------------------------------------
La medición del auditor: una venta simple —una línea, pago en efectivo—
generaba 13 filas de AuditLog y 66 consultas SQL. Eso se paga en la ruta más
caliente del sistema: mientras el cliente espera el tiquete. A 50 ventas
diarias son ~191 000 filas y ~41 MB al año, sin política de retención.

Tres causas, tres correcciones:

1. Los receptores se registraban SIN `sender`, así que Django los ejecutaba
   en cada save() de CUALQUIER modelo del proyecto —incluidos los que no se
   auditan— y recién ahí se filtraba por el conjunto AUDITED. Ahora se
   conectan modelo por modelo desde CoreConfig.ready(): los no auditados no
   pagan nada.

2. Se auditaban las líneas de detalle (LineaVenta, LineaAsiento,
   LineaCompra) una por una. Son hijas de un documento que YA se audita y que
   es inmutable: si querés saber qué se vendió, mirás la factura. Auditarlas
   aparte duplicaba la información sin añadir capacidad real de investigación,
   y era la mayor parte de esas 13 filas.

3. El campo `antes` guardaba el objeto COMPLETO con model_to_dict. Ahora
   guarda solo los campos que efectivamente cambiaron. Un cambio de precio
   deja constancia de precio_venta, no de las otras veinte columnas.

Lo que NO se tocó, a propósito: el kardex (MovimientoInventario) y los
documentos siguen auditados por completo. Son la evidencia sobre la que se
apoya el control anti-fraude, y ahí el costo está justificado.
"""
import logging

from django.apps import apps
from django.db.models.signals import post_delete, post_save, pre_save
from django.forms.models import model_to_dict

from .middleware import get_current_ip, get_current_user

logger = logging.getLogger(__name__)

AUDITED = {
    "catalogo.categoria",
    "catalogo.impuesto",
    "catalogo.producto",
    "inventario.bodega",
    "inventario.movimientoinventario",
    "caja.sesioncaja",
    "caja.movimientocaja",
    "ventas.cliente",
    "ventas.facturaventa",
    "ventas.documentocxc",
    "ventas.abono",
    "ventas.devolucionventa",
    "contabilidad.asiento",
    "contabilidad.cuentacontable",
    "compras.proveedor",
    "compras.compra",
}

# Modelos de detalle que se dejaron FUERA de AUDITED a propósito (BE-01).
# Se listan explícitamente para que quede constancia de que es una decisión,
# no un olvido: ventas.lineaventa, contabilidad.lineaasiento,
# compras.lineacompra. Su documento padre sí queda auditado y es inmutable.
NO_AUDITADOS_A_PROPOSITO = {
    "ventas.lineaventa",
    "contabilidad.lineaasiento",
    "compras.lineacompra",
}


def _label(sender):
    return f"{sender._meta.app_label}.{sender._meta.model_name}"


def _snapshot(instance):
    """Estado del objeto como diccionario serializable.

    Si falla, se registra en el log en vez de devolver None en silencio
    (auditoría 2026-07-28, BE-03). Una auditoría con campos en blanco es
    justo lo que no sirve cuando hay que investigar un faltante de caja, así
    que al menos tiene que quedar el rastro de por qué quedó vacía.
    """
    try:
        return model_to_dict(instance)
    except Exception:
        logger.exception(
            "No se pudo serializar %s#%s para la auditoría; el registro queda sin detalle.",
            _label(type(instance)),
            getattr(instance, "pk", "?"),
        )
        return None


def _solo_lo_que_cambio(antes, despues):
    """Del estado anterior, únicamente los campos que efectivamente cambiaron.

    Guardar el objeto entero en cada edición multiplica el tamaño de la
    bitácora sin añadir información: para investigar hace falta saber QUÉ
    cambió, y el estado final ya está en `despues`.
    """
    if not antes or not despues:
        return antes
    return {k: v for k, v in antes.items() if k in despues and despues[k] != v} or None


def _capturar_estado_previo(sender, instance, raw=False, **kwargs):
    # raw=True significa que el objeto viene de un fixture (loaddata). Cargar un
    # respaldo no es una acción de usuario y no debe generar auditoría: además de
    # ensuciar el historial, colisiona con los AuditLog que trae el propio
    # respaldo, porque los id se pisan.
    if raw or instance.pk is None:
        return
    try:
        anterior = sender.objects.get(pk=instance.pk)
        instance._audit_antes = _snapshot(anterior)
    except sender.DoesNotExist:
        instance._audit_antes = None


def _auditar_guardado(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    from core.models import AuditLog

    despues = _snapshot(instance)
    antes = None
    if not created:
        antes = _solo_lo_que_cambio(getattr(instance, "_audit_antes", None), despues)
        # Edición que no cambió nada (un save() de más): no ensucia la bitácora.
        if antes is None:
            return

    AuditLog.objects.create(
        usuario=get_current_user(),
        ip=get_current_ip(),
        tabla=_label(sender),
        objeto_id=str(instance.pk),
        accion="crear" if created else "editar",
        antes=antes,
        despues=despues,
    )


def _auditar_borrado(sender, instance, **kwargs):
    from core.models import AuditLog

    AuditLog.objects.create(
        usuario=get_current_user(),
        ip=get_current_ip(),
        tabla=_label(sender),
        objeto_id=str(instance.pk),
        accion="borrar",
        antes=_snapshot(instance),
        despues=None,
    )


def conectar():
    """Engancha los receptores SOLO a los modelos auditados.

    Se llama desde CoreConfig.ready(). Registrar por `sender` explícito es lo
    que evita que cada save() del proyecto pase por estas funciones (BE-01).
    `dispatch_uid` hace la conexión idempotente: si ready() corriera dos veces
    no se duplicarían los registros de auditoría.
    """
    for etiqueta in AUDITED:
        try:
            modelo = apps.get_model(etiqueta)
        except LookupError:
            logger.error("Modelo auditado inexistente en AUDITED: %s", etiqueta)
            continue
        pre_save.connect(
            _capturar_estado_previo, sender=modelo, dispatch_uid=f"audit_pre_{etiqueta}"
        )
        post_save.connect(
            _auditar_guardado, sender=modelo, dispatch_uid=f"audit_post_{etiqueta}"
        )
        post_delete.connect(
            _auditar_borrado, sender=modelo, dispatch_uid=f"audit_del_{etiqueta}"
        )
