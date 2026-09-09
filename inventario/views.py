from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from catalogo.codigos import aplicar_conversion, plan_de_conversion
from catalogo.consultas import productos_visibles
from catalogo.models import Categoria, Producto
from core.imagenes import url_imagen_producto
from core.roles import CAJERO, GERENTE, rol_requerido
from core.tenancy import empresa_actual

from .etiquetas import TOPE_ETIQUETAS, seleccionar_para_etiquetas, svg_barcode
from .forms import AjusteInventarioForm
from .services import registrar_movimiento

# Tope de tarjetas dibujadas de una vez. Igual que en el POS: más allá de esto
# el navegador de la caja se siente lento y nadie recorre 500 tarjetas a ojo
# —se busca o se escanea—.
TOPE_TARJETAS = 150


@rol_requerido(GERENTE)
def ajuste_inventario(request):
    """Único camino de ajuste manual: pasa por el servicio de dominio,
    exige motivo y queda auditado con usuario e IP."""
    form = AjusteInventarioForm(request.POST or None, empresa=empresa_actual(request))
    if request.method == "POST" and form.is_valid():
        datos = form.cleaned_data
        referencia = f"AJ-{timezone.now():%Y%m%d-%H%M%S}"
        try:
            mov = registrar_movimiento(
                producto=datos["producto"],
                bodega=datos["bodega"],
                tipo="AJU",
                cantidad=datos["cantidad"],
                costo_unitario=datos["costo_unitario"] or 0,
                referencia=referencia,
                motivo=datos["motivo"],
                usuario=request.user,
            )
            messages.success(
                request,
                f"Ajuste {referencia} registrado: {mov.cantidad:+} × {mov.producto.nombre}. "
                f"Stock resultante: {mov.stock_resultante}.",
            )
            return redirect("inventario:ajuste")
        except ValidationError as e:
            form.add_error(None, e)
    return render(request, "inventario/ajuste.html", {"form": form, "title": "Ajuste de inventario"})


@rol_requerido(CAJERO, GERENTE)
def etiquetas(request):
    """Etiquetas producto por producto, pensada para el conteo físico.

    El uso real (Oscar, 05/09/2026): se recorre la bodega con la pistola,
    se escanea un artículo, se compara lo que dice el sistema con lo que hay
    en el estante y se imprime la etiqueta de ese artículo antes de pasar al
    siguiente. Por eso la pantalla muestra foto, código y existencia, y por
    eso la cantidad se elige por producto y no para toda una tanda.

    **Muestra también los agotados**, a diferencia del resto del ERP (regla
    del 02/08/2026). En un conteo físico el producto en cero es justamente el
    que hay que ir a verificar: si el sistema dice cero y en el estante hay
    tres, ocultarlo es esconder el error que se salió a buscar. Es la misma
    razón por la que la pantalla de ajuste tampoco filtra por existencia.

    `?hoja=1` conserva la vista anterior: la hoja de etiquetas para imprimir
    en papel adhesivo desde el navegador, útil cuando hay que sacar una tanda
    grande de una sola categoría.
    """
    empresa = empresa_actual(request)

    if request.GET.get("hoja") == "1":
        return _hoja_de_etiquetas(request, empresa)

    productos = list(
        productos_visibles(empresa, incluir_agotados=True)
        .select_related("categoria")
        .values("id", "sku", "nombre", "codigo_barras", "precio_venta", "stock_actual",
                "presentacion", "marca", "categoria__nombre", "imagen")
        .order_by("nombre")
    )
    for p in productos:  # JSON-serializable + nombres de campo para el navegador
        p["precio_venta"] = float(p["precio_venta"])
        p["stock_actual"] = float(p["stock_actual"])
        p["categoria"] = p.pop("categoria__nombre") or "Sin categoría"
        p["presentacion"] = p.get("presentacion") or ""
        p["marca"] = p.get("marca") or ""
        p["codigo_barras"] = p.get("codigo_barras") or ""
        p["imagen"] = url_imagen_producto(p["imagen"])

    return render(request, "inventario/etiquetas.html", {
        "productos": productos,
        "tope": TOPE_TARJETAS,
        "sin_codigo": sum(1 for p in productos if not p["codigo_barras"]),
    })


def _hoja_de_etiquetas(request, empresa):
    """Vista anterior: una hoja imprimible desde el navegador."""
    seleccion = seleccionar_para_etiquetas(empresa, request.GET)

    # Un SVG por producto, repetido por copia: generar el código de barras es
    # lo caro, repetir el mismo texto no.
    etiquetas_render = []
    for producto, copias in seleccion.pares:
        svg = mark_safe(svg_barcode(producto.codigo_barras))
        for _ in range(copias):
            etiquetas_render.append({
                "nombre": producto.nombre,
                "precio": producto.precio_venta,
                "sku": producto.sku,
                "svg": svg,
            })

    return render(request, "inventario/etiquetas_hoja.html", {
        "etiquetas": etiquetas_render,
        "total": len(etiquetas_render),
        "faltan_codigo": seleccion.faltan_codigo,
        "recortado": seleccion.recortado,
        "tope": TOPE_ETIQUETAS,
        "categorias": Categoria.objects.all().order_by("nombre"),
        "cat_actual": seleccion.categoria,
        "copias": seleccion.copias,
        "segun_stock": seleccion.segun_stock,
        "solo_faltantes": seleccion.solo_faltantes,
        "agotados": seleccion.agotados,
    })


@rol_requerido(GERENTE)
@require_http_methods(["GET", "POST"])
def codigos_barras(request):
    """Censo y conversión de los códigos de barras del catálogo.

    Vive dentro del ERP y no solo como comando de consola por una razón
    práctica: en la máquina de la tienda el antivirus bloquea los .bat, así
    que la consola no siempre está disponible. Esta pantalla corre en el
    proceso que ya está encendido.

    Qué hace: deja quietos los códigos que son un EAN legítimo —el de
    fábrica, que la caja lee del empaque sin pegar nada— y cambia el resto por
    un EAN-8 interno. El porqué del EAN-8 está en catalogo/codigos.py.
    """
    productos = list(
        productos_visibles(empresa_actual(request), incluir_agotados=True)
        .order_by("sku")
    )
    # Los códigos ocupados se miran en TODO el catálogo, incluidos los
    # productos inactivos: el escáner no sabe de estados, y dos productos con
    # el mismo código serían ambiguos en la caja.
    usados = set(Producto.objects.values_list("codigo_barras", flat=True))
    plan = plan_de_conversion(productos, usados)

    if request.method == "POST":
        if request.POST.get("confirmar") != "si":
            messages.warning(request, "No se cambió nada: falta confirmar.")
            return redirect("inventario:codigos")
        destino = Path(settings.BASE_DIR) / "codigos_anteriores.csv"
        cuantos = aplicar_conversion(plan, destino)
        messages.success(
            request,
            f"Listo: {cuantos} producto(s) recibieron código interno. "
            f"El respaldo del código anterior de cada uno quedó en {destino.name}.",
        )
        return redirect("inventario:codigos")

    return render(request, "inventario/codigos.html", {
        "conservados": plan["conservados"],
        "ya_internos": plan["ya_internos"],
        "cambios": plan["cambios"],
        "total": len(productos),
    })
