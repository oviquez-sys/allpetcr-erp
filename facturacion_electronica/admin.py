from django.contrib import admin

from .models import (
    FacturaElectronica,
    NotaCreditoElectronica,
    NotaDebitoElectronica,
    ReciboElectronicoPago,
    TiqueteElectronico,
)

CAMPOS_COMUNES = ("numero_interno", "clave", "estado", "intentos_envio", "creado_en")


class _ComprobanteAdmin(admin.ModelAdmin):
    list_display = CAMPOS_COMUNES
    list_filter = ("estado",)
    search_fields = ("numero_interno", "clave")

    def get_readonly_fields(self, request, obj=None):
        # Todo comprobante es de solo lectura desde el admin: nace y cambia
        # de estado por services.py (numeración y flujo de envío), nunca a mano.
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        # Un comprobante nace de una venta real (services.crear_*), no a mano.
        return False


@admin.register(FacturaElectronica)
class FacturaElectronicaAdmin(_ComprobanteAdmin):
    list_display = CAMPOS_COMUNES + ("factura_venta",)


@admin.register(TiqueteElectronico)
class TiqueteElectronicoAdmin(_ComprobanteAdmin):
    list_display = CAMPOS_COMUNES + ("factura_venta",)


@admin.register(NotaCreditoElectronica)
class NotaCreditoElectronicaAdmin(_ComprobanteAdmin):
    list_display = CAMPOS_COMUNES + ("motivo",)


@admin.register(NotaDebitoElectronica)
class NotaDebitoElectronicaAdmin(_ComprobanteAdmin):
    list_display = CAMPOS_COMUNES + ("motivo",)


@admin.register(ReciboElectronicoPago)
class ReciboElectronicoPagoAdmin(_ComprobanteAdmin):
    list_display = CAMPOS_COMUNES + ("factura_electronica", "monto")
