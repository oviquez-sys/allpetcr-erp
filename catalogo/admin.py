from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path

from core.admin_fotos import columna_foto
from core.templatetags.fotos import foto_producto
from core.templatetags.formato import crc as _crc  # formato CR (miles con punto)

from .models import CambioPrecio, Categoria, FichaAlimento, Impuesto, Producto


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "padre")
    search_fields = ("nombre",)


@admin.register(Impuesto)
class ImpuestoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tarifa", "vigente_desde", "vigente_hasta")


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = "__all__"

    def clean_codigo_barras(self):
        """Un código de barras, un producto (auditoría 26/09/2026, INV-10).

        El escáner del POS toma el PRIMER producto con ese código: con dos,
        se vende el equivocado al precio equivocado. Se valida acá y no con
        una restricción de la base porque no se puede confirmar que la base
        de producción no tenga ya algún repetido; la restricción de base se
        agrega cuando `censo_codigos` lo confirme."""
        codigo = (self.cleaned_data.get("codigo_barras") or "").strip()
        if codigo:
            otros = Producto.objects.filter(codigo_barras=codigo).exclude(pk=self.instance.pk)
            if otros.exists():
                raise forms.ValidationError(f"Ese código ya lo tiene «{otros.first().nombre}».")
        return codigo


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    form = ProductoForm
    list_display = ("foto", "sku", "nombre", "categoria", "stock_fmt", "minimo_fmt", "costo_fmt", "precio_fmt", "margen_fmt", "markup_fmt", "activo", "destacado_home", "orden_home")
    # "Destacado en home" y "Orden en home" (26/09/2026, a pedido de Oscar):
    # editables directo en la lista, sin entrar a cada ficha, porque armar la
    # vitrina de la portada es probar un orden, mirar el sitio, y ajustar —
    # entrar y salir del formulario de cada producto para eso sería
    # impracticable con más de dos o tres destacados.
    list_editable = ("destacado_home", "orden_home")
    # La ficha de alimento se elige buscando por nombre, no en un desplegable
    # de ~130 fórmulas.
    autocomplete_fields = ("ficha_alimento",)

    @admin.display(description="Stock actual", ordering="stock_actual")
    def stock_fmt(self, obj):
        return _crc(obj.stock_actual, 0)

    @admin.display(description="Stock mínimo", ordering="stock_minimo")
    def minimo_fmt(self, obj):
        return _crc(obj.stock_minimo, 0)

    @admin.display(description="Costo promedio", ordering="costo_promedio")
    def costo_fmt(self, obj):
        return f"₡{_crc(obj.costo_promedio, 2)}"

    @admin.display(description="Precio venta", ordering="precio_venta")
    def precio_fmt(self, obj):
        return f"₡{_crc(obj.precio_venta, 2)}"

    @admin.display(description="Margen %")
    def margen_fmt(self, obj):
        if obj.margen_pct is None:
            return "—"
        return f"{obj.margen_pct}%"

    @admin.display(description="Markup %")
    def markup_fmt(self, obj):
        if obj.markup_pct is None:
            return "—"
        return f"{obj.markup_pct}%"

    list_display_links = ("sku", "nombre")
    list_filter = ("categoria", "activo", "destacado_home", ("cabys", admin.EmptyFieldListFilter))
    # CABYS en la búsqueda (21/09/2026): cuando el contador diga "cambien
    # todos los 3694000999900", se encuentran escribiendo el código.
    search_fields = ("sku", "nombre", "codigo_barras", "categoria_original", "cabys")
    list_per_page = 50
    # El margen de cada fila necesita empresa (régimen) e impuesto (tarifa).
    list_select_related = ("categoria", "empresa", "impuesto")
    # Stock y costo solo cambian por movimientos de inventario (kardex),
    # nunca editados a mano: única fuente de verdad.
    readonly_fields = ("stock_actual", "costo_promedio", "creado_en", "actualizado_en", "foto_grande")
    change_form_template = "admin/catalogo/producto/change_form.html"

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                "<path:object_id>/entrada/",
                self.admin_site.admin_view(self.entrada_view),
                name="catalogo_producto_entrada",
            ),
        ]
        return extra + urls

    def entrada_view(self, request, object_id):
        """Entrada rápida de mercadería para ESTE producto: registra una compra
        de una línea y la recibe de inmediato, usando el mismo motor que
        'Recibir mercadería' (sube stock, recalcula costo promedio y genera el
        asiento contable). No se edita el stock a mano: pasa por el kardex."""
        from compras import services
        from compras.models import Proveedor
        from core.models import Sucursal

        producto = get_object_or_404(Producto, pk=object_id)
        empresa = producto.empresa

        if request.method == "POST":
            try:
                cantidad = Decimal(str(request.POST.get("cantidad") or "0"))
                costo = Decimal(str(request.POST.get("costo_unitario") or "0"))
                if cantidad <= 0:
                    raise ValidationError("La cantidad debe ser mayor que cero.")
                if costo < 0:
                    raise ValidationError("El costo no puede ser negativo.")
                sucursal = Sucursal.objects.filter(empresa=empresa, activa=True).first()
                if sucursal is None:
                    raise ValidationError("No hay una sucursal activa configurada.")
                prov_id = request.POST.get("proveedor_id")
                prov_nuevo = (request.POST.get("proveedor_nuevo") or "").strip()
                if prov_id:
                    proveedor = Proveedor.objects.get(pk=prov_id, empresa=empresa)
                elif prov_nuevo:
                    proveedor, _ = Proveedor.objects.get_or_create(empresa=empresa, nombre=prov_nuevo)
                else:
                    raise ValidationError("Elegí un proveedor de la lista o escribí uno nuevo.")

                compra = services.crear_compra(
                    proveedor=proveedor, sucursal=sucursal,
                    lineas=[{"producto": producto, "cantidad": cantidad, "costo_unitario": costo}],
                    forma_pago=request.POST.get("forma_pago", "CON"),
                    factura_proveedor=(request.POST.get("factura_proveedor") or "").strip(),
                    usuario=request.user,
                )
                services.recibir_compra(compra=compra, usuario=request.user)
                messages.success(
                    request,
                    f"Entrada registrada: +{cantidad:g} de «{producto.nombre}» a ₡{costo:g} "
                    f"(compra {compra.numero}). El stock y el costo promedio ya se actualizaron.",
                )
                return redirect("admin:catalogo_producto_change", object_id)
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
            except Proveedor.DoesNotExist:
                messages.error(request, "Ese proveedor no existe.")

        contexto = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "producto": producto,
            "proveedores": Proveedor.objects.filter(empresa=empresa, activo=True).order_by("nombre"),
            "title": f"Registrar entrada — {producto.nombre}",
        }
        return render(request, "admin/catalogo/producto/entrada.html", contexto)

    @admin.display(description="")
    def foto(self, obj):
        return foto_producto(obj, 40, "clickable-product-img")

    @admin.display(description="Foto")
    def foto_grande(self, obj):
        return foto_producto(obj, 160, "clickable-product-img")

    def has_delete_permission(self, request, obj=None):
        # Los productos no se borran (integridad histórica); se desactivan.
        return False

    def get_ordering(self, request):
        """Los destacados de home arriba de todo, en su propio orden, para
        poder armar y revisar la vitrina de un vistazo (26/09/2026). El resto
        de la lista sigue alfabético debajo, como siempre — esto es solo el
        orden en que se VE en el admin, no toca Producto.Meta.ordering ni
        ninguna consulta del sitio."""
        return ("-destacado_home", "orden_home", "nombre")


@admin.register(CambioPrecio)
class CambioPrecioAdmin(admin.ModelAdmin):
    """Bitácora de solo lectura de cambios de precio de venta."""

    foto = columna_foto("producto", 32)
    list_display = ("foto", "producto", "valor_anterior", "valor_nuevo", "costo_al_momento", "usuario", "fecha")
    search_fields = ("producto__sku", "producto__nombre", "motivo")
    date_hierarchy = "fecha"
    readonly_fields = [f.name for f in CambioPrecio._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class VerificacionFilter(admin.SimpleListFilter):
    """Antigüedad de la última verificación contra la fuente oficial. Sirve
    para sacar la lista de "fichas que no se revisan hace más de un año"
    sin construir un sistema de alertas."""

    title = "última verificación"
    parameter_name = "verificacion"

    def lookups(self, request, model_admin):
        return [("nunca", "Nunca"), ("6m", "Hace más de 6 meses"), ("12m", "Hace más de 12 meses")]

    def queryset(self, request, queryset):
        from datetime import date, timedelta

        if self.value() == "nunca":
            return queryset.filter(verificado_en__isnull=True)
        if self.value() in ("6m", "12m"):
            dias = 183 if self.value() == "6m" else 365
            return queryset.filter(verificado_en__lt=date.today() - timedelta(days=dias))
        return queryset


@admin.register(FichaAlimento)
class FichaAlimentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "marca", "especie", "tipo", "estado", "verificado_en", "presentaciones")
    list_filter = ("estado", VerificacionFilter, "especie", "tipo", "marca")
    search_fields = ("nombre", "marca", "linea", "clave")
    readonly_fields = ("creado_en", "actualizado_en")

    @admin.display(description="Presentaciones")
    def presentaciones(self, obj):
        return obj.productos.count()
