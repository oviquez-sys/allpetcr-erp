from decimal import Decimal

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils.html import format_html

from core.templatetags.formato import crc as _crc  # formato CR (miles con punto)

from .models import CambioPrecio, Categoria, Impuesto, Producto


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "padre")
    search_fields = ("nombre",)


@admin.register(Impuesto)
class ImpuestoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tarifa", "vigente_desde", "vigente_hasta")


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("foto", "sku", "nombre", "categoria", "stock_fmt", "minimo_fmt", "costo_fmt", "precio_fmt", "margen_fmt", "markup_fmt", "activo")

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
    list_filter = ("categoria", "activo")
    search_fields = ("sku", "nombre", "codigo_barras", "categoria_original")
    list_per_page = 50
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
        if obj.imagen:
            return format_html(
                '<img src="/media/{}" class="clickable-product-img" '
                'style="width:36px;height:36px;border-radius:7px;object-fit:cover">',
                obj.imagen,
            )
        return "🐾"

    @admin.display(description="Foto")
    def foto_grande(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="/media/{}" class="clickable-product-img" '
                'style="width:140px;height:140px;border-radius:14px;object-fit:cover">',
                obj.imagen,
            )
        return "Sin foto"

    def has_delete_permission(self, request, obj=None):
        # Los productos no se borran (integridad histórica); se desactivan.
        return False


@admin.register(CambioPrecio)
class CambioPrecioAdmin(admin.ModelAdmin):
    """Bitácora de solo lectura de cambios de precio de venta."""

    list_display = ("producto", "valor_anterior", "valor_nuevo", "costo_al_momento", "usuario", "fecha")
    search_fields = ("producto__sku", "producto__nombre", "motivo")
    date_hierarchy = "fecha"
    readonly_fields = [f.name for f in CambioPrecio._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
