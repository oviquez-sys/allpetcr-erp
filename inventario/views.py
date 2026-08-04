from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe

from catalogo.consultas import pidio_agotados, productos_visibles
from catalogo.models import Categoria
from core.roles import CAJERO, GERENTE, rol_requerido
from core.tenancy import empresa_actual

from .etiquetas import svg_barcode
from .forms import AjusteInventarioForm
from .services import registrar_movimiento

# Máximo de etiquetas que una sola petición puede generar. Cubre cualquier
# tanda de impresión real; por encima de esto la página deja de ser imprimible
# y el navegador se traba, así que recortar es mejor servicio que cumplir.
TOPE_ETIQUETAS = 500


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
    """Genera etiquetas imprimibles con código de barras.

    Filtros por querystring:
      ?categoria=<id>   solo esa familia (por defecto: todas)
      ?copias=<n>       n etiquetas por producto (por defecto 1)
      ?segun_stock=1    una etiqueta por unidad en existencia
      ?solo_faltantes=1 solo productos en/ bajo el mínimo
      ?agotados=1       incluir también los que están sin existencias
    """
    # Solo lo que hay en existencia (regla del 02/08/2026, ver
    # catalogo/consultas.py): una etiqueta es para pegarla en un artículo que
    # está en la góndola. `?agotados=1` la levanta para el caso de imprimir
    # por adelantado las etiquetas de un pedido que viene en camino.
    solo_faltantes = bool(request.GET.get("solo_faltantes"))
    # `solo_faltantes` levanta el filtro de existencias por su cuenta: un
    # producto en cero es el más faltante de todos, y filtrarlo antes dejaría
    # a "solo faltantes" mostrando justo lo que no falta. Los dos filtros
    # miden lo mismo y en direcciones opuestas; gana el que el usuario pidió
    # explícitamente.
    agotados = pidio_agotados(request) or solo_faltantes
    productos = (
        productos_visibles(empresa_actual(request), incluir_agotados=agotados)
        .select_related("categoria")
        .order_by("nombre")
    )

    cat_id = request.GET.get("categoria")
    if cat_id:
        productos = productos.filter(categoria_id=cat_id)
    if solo_faltantes:
        productos = [p for p in productos if p.stock_actual <= p.stock_minimo]

    segun_stock = request.GET.get("segun_stock") == "1"
    try:
        copias = max(1, min(50, int(request.GET.get("copias", "1"))))
    except ValueError:
        copias = 1

    etiquetas_render = []
    faltan_codigo = 0
    recortado = False
    for p in productos:
        # Tope global: sin él, "una etiqueta por unidad en existencia" sobre un
        # producto con stock alto construye una página de cientos de MB que
        # tumba el proceso (medido: stock 99.999 => 207 MB en una sola
        # respuesta). El tope corta ahí y avisa, en vez de reventar.
        if len(etiquetas_render) >= TOPE_ETIQUETAS:
            recortado = True
            break
        if not p.codigo_barras:
            faltan_codigo += 1
            continue
        pedidas = max(1, int(p.stock_actual) if segun_stock else copias)
        # Nunca pasar del tope, aunque este producto solo pida más. Se compara
        # ANTES de recortar: si se pidió más de lo que cabe, hubo recorte real
        # aunque el bucle termine aquí y no vuelva a entrar (caso de un único
        # producto con stock enorme, que es justo el que provocaba el fallo).
        n = min(pedidas, TOPE_ETIQUETAS - len(etiquetas_render))
        if n < pedidas:
            recortado = True
        if n <= 0:
            break
        svg = mark_safe(svg_barcode(p.codigo_barras))
        for _ in range(n):
            etiquetas_render.append({
                "nombre": p.nombre,
                "precio": p.precio_venta,
                "sku": p.sku,
                "svg": svg,
            })

    return render(request, "inventario/etiquetas.html", {
        "etiquetas": etiquetas_render,
        "total": len(etiquetas_render),
        "faltan_codigo": faltan_codigo,
        "recortado": recortado,
        "tope": TOPE_ETIQUETAS,
        "categorias": Categoria.objects.all().order_by("nombre"),
        "cat_actual": cat_id or "",
        "copias": copias,
        "segun_stock": segun_stock,
        "solo_faltantes": bool(request.GET.get("solo_faltantes")),
    })
