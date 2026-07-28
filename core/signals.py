"""Auditoría automática por señales del ORM.

Cada create/update/delete de los modelos listados en AUDITED escribe un
AuditLog con el estado anterior, el nuevo, el usuario y la IP de la
petición (vía core.middleware). Regla de la especificación: "todo cambio
debe quedar auditado" — sin que ningún módulo lo pida.
"""
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.forms.models import model_to_dict

from .middleware import get_current_ip, get_current_user

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
    "ventas.lineaventa",
    "ventas.documentocxc",
    "ventas.abono",
    "contabilidad.asiento",
    "contabilidad.lineaasiento",
    "contabilidad.cuentacontable",
    "compras.proveedor",
    "compras.compra",
    "compras.lineacompra",
}


def _label(sender):
    return f"{sender._meta.app_label}.{sender._meta.model_name}"


def _snapshot(instance):
    try:
        return model_to_dict(instance)
    except Exception:
        return None


@receiver(pre_save)
def _capturar_estado_previo(sender, instance, raw=False, **kwargs):
    # raw=True significa que el objeto viene de un fixture (loaddata). Cargar un
    # respaldo no es una acción de usuario y no debe generar auditoría: además de
    # ensuciar el historial, colisiona con los AuditLog que trae el propio
    # respaldo, porque los id se pisan.
    if raw or _label(sender) not in AUDITED or instance.pk is None:
        return
    try:
        anterior = sender.objects.get(pk=instance.pk)
        instance._audit_antes = _snapshot(anterior)
    except sender.DoesNotExist:
        instance._audit_antes = None


@receiver(post_save)
def _auditar_guardado(sender, instance, created, raw=False, **kwargs):
    if raw or _label(sender) not in AUDITED:
        return
    from core.models import AuditLog

    AuditLog.objects.create(
        usuario=get_current_user(),
        ip=get_current_ip(),
        tabla=_label(sender),
        objeto_id=str(instance.pk),
        accion="crear" if created else "editar",
        antes=None if created else getattr(instance, "_audit_antes", None),
        despues=_snapshot(instance),
    )


@receiver(post_delete)
def _auditar_borrado(sender, instance, **kwargs):
    if _label(sender) not in AUDITED:
        return
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
