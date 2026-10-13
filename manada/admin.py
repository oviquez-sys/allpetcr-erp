from io import BytesIO

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone

from core.tenancy import empresa_actual

from .models import Cupon, Mascota, PerfilManada, Regalia


@admin.register(Regalia)
class RegaliaAdmin(admin.ModelAdmin):
    """Donde Oscar cambia lo que se regala, sin tocar código."""

    list_display = ("nombre", "porcentaje", "texto_cliente", "dias_vigencia", "activa",
                    "cupones_emitidos", "cupones_usados")
    fields = ("nombre", "porcentaje", "texto_cliente", "dias_vigencia", "activa")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _emitidos=Count("cupones"), _usados=Count("cupones", filter=Q(cupones__usado_en__isnull=False)),
        )

    @admin.display(description="Cupones entregados", ordering="_emitidos")
    def cupones_emitidos(self, obj):
        return obj._emitidos

    @admin.display(description="Cupones usados", ordering="_usados")
    def cupones_usados(self, obj):
        return obj._usados

    def save_model(self, request, obj, form, change):
        if not change:
            obj.empresa = empresa_actual(request)
        with transaction.atomic():
            # Solo una activa: activar esta apaga la anterior, en vez de
            # obligar a Oscar a desactivarla primero a mano.
            if obj.activa:
                Regalia.objects.filter(empresa=obj.empresa, activa=True).exclude(pk=obj.pk).update(activa=False)
            super().save_model(request, obj, form, change)
        messages.info(request, "Los cupones que ya se entregaron conservan su porcentaje; "
                               "el cambio aplica a los que se registren desde ahora.")


def _exportar_excel(filas, encabezados, nombre):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    libro = Workbook()
    hoja = libro.active
    hoja.append(encabezados)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in filas:
        hoja.append(fila)
    for columna in hoja.columns:
        hoja.column_dimensions[columna[0].column_letter].width = max(
            12, min(45, max(len(str(c.value or "")) for c in columna) + 2))
    salida = BytesIO()
    libro.save(salida)
    respuesta = HttpResponse(
        salida.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}-{timezone.localdate():%Y-%m-%d}.xlsx"'
    return respuesta


@admin.register(PerfilManada)
class PerfilManadaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "correo", "whatsapp", "origen", "acepta_promociones", "fuente",
                    "mascotas", "cupon", "creado_en")
    list_filter = ("origen", "acepta_promociones", "fuente", "correo_verificado", "creado_en")
    search_fields = ("cliente__nombre", "cliente__email", "cliente__telefono", "cliente__mascotas__nombre")
    readonly_fields = ("cliente", "origen", "correo_verificado", "consentimiento_en", "fuente",
                       "mascotas_registradas_en", "creado_en", "acepta_promociones")
    fields = readonly_fields
    actions = ["exportar_excel"]
    list_select_related = ("cliente",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_mascotas=Count("cliente__mascotas"))

    def has_add_permission(self, request):
        # Un miembro nace del registro en la página web, no a mano.
        return False

    @admin.display(description="Nombre", ordering="cliente__nombre")
    def nombre(self, obj):
        return obj.cliente.nombre

    @admin.display(description="Correo", ordering="cliente__email")
    def correo(self, obj):
        return obj.cliente.email

    @admin.display(description="WhatsApp")
    def whatsapp(self, obj):
        return obj.cliente.telefono

    @admin.display(description="Mascotas", ordering="_mascotas")
    def mascotas(self, obj):
        return obj._mascotas

    @admin.display(description="Cupón")
    def cupon(self, obj):
        c = obj.cliente.cupones.filter(tipo=Cupon.Tipo.BIENVENIDA).first()
        return f"{c.codigo} ({c.estado_display})" if c else "—"

    @admin.action(description="Exportar los seleccionados a Excel")
    def exportar_excel(self, request, queryset):
        filas = []
        for p in queryset.select_related("cliente").prefetch_related("cliente__mascotas", "cliente__cupones"):
            c = p.cliente
            cupon = next((x for x in c.cupones.all() if x.tipo == Cupon.Tipo.BIENVENIDA), None)
            mascotas = "; ".join(
                f"{m.nombre} ({m.get_especie_display()}{', ' + m.raza if m.raza else ''}"
                f"{', ' + m.edad_texto if m.edad_texto else ''}{', ' + str(m.peso_kg) + ' kg' if m.peso_kg else ''})"
                for m in c.mascotas.all()
            )
            filas.append([
                c.nombre, c.email, c.telefono, p.get_origen_display(),
                "Sí" if p.acepta_promociones else "No", p.fuente,
                timezone.localtime(p.creado_en).strftime("%d/%m/%Y %H:%M"), mascotas,
                cupon.codigo if cupon else "", cupon.estado_display if cupon else "",
            ])
        return _exportar_excel(
            filas,
            ["Nombre", "Correo", "WhatsApp", "Se registró con", "Acepta promociones", "Fuente",
             "Fecha de registro", "Mascotas", "Cupón", "Estado del cupón"],
            "manada",
        )


@admin.register(Cupon)
class CuponAdmin(admin.ModelAdmin):
    list_display = ("codigo", "cliente", "porcentaje", "estado", "creado_en", "vence_en", "usado_en", "factura")
    list_filter = ("tipo", ("usado_en", admin.EmptyFieldListFilter), "creado_en")
    search_fields = ("codigo", "cliente__nombre", "cliente__email", "factura__numero")
    readonly_fields = ("codigo", "cliente", "tipo", "regalia", "porcentaje", "descripcion",
                       "creado_en", "usado_en", "factura")
    # Lo único editable a mano es la fecha de vencimiento (por si hay que
    # darle unos días más a un cliente). Usado/no usado lo decide la caja.
    fields = readonly_fields + ("vence_en",)
    list_select_related = ("cliente", "factura")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Estado")
    def estado(self, obj):
        return obj.estado_display


@admin.register(Mascota)
class MascotaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "especie", "raza", "edad", "peso_kg", "cliente", "creada_en")
    list_filter = ("especie", "creada_en")
    search_fields = ("nombre", "raza", "cliente__nombre", "cliente__email")
    list_select_related = ("cliente",)
    readonly_fields = ("cliente", "creada_en")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Edad (aprox.)", ordering="-fecha_nacimiento_aprox")
    def edad(self, obj):
        return obj.edad_texto
