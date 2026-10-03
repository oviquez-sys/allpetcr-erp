from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods, require_POST

from catalogo.codigos import aplicar_conversion, plan_de_conversion
from catalogo.consultas import productos_visibles
from catalogo.models import Categoria, Producto
from core.imagenes import completar_foto, datos_foto
from core.roles import CAJERO, GERENTE, rol_requerido
from core.tenancy import empresa_actual

from . import agotados as ag
from .etiquetas import TOPE_ETIQUETAS, seleccionar_para_etiquetas, svg_barcode
from .forms import AjusteInventarioForm
from .models import Agotamiento
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
                motivo=f"[{datos['tipo']}] {datos['motivo']}"[:200],
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
    # Foto del producto elegido (20/09/2026): con ~500 nombres parecidos en
    # la lista, ver la foto evita ajustar el producto equivocado.
    fotos = {
        str(p.pk): {**datos_foto(p), "nombre": p.nombre, "stock": float(p.stock_actual)}
        for p in form.fields["producto"].queryset
    }
    return render(request, "inventario/ajuste.html", {
        "form": form, "title": "Ajuste de inventario", "fotos": fotos,
    })


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
                "presentacion", "marca", "categoria__nombre", "imagen",
                "descripcion", "actualizado_en", "etiqueta_impresa_en")
        .order_by("nombre")
    )
    for p in productos:  # JSON-serializable + nombres de campo para el navegador
        p["precio_venta"] = float(p["precio_venta"])
        p["stock_actual"] = float(p["stock_actual"])
        p["categoria"] = p.pop("categoria__nombre") or "Sin categoría"
        p["presentacion"] = p.get("presentacion") or ""
        p["marca"] = p.get("marca") or ""
        p["codigo_barras"] = p.get("codigo_barras") or ""
        p["descripcion"] = p.get("descripcion") or ""
        # ISO o None: lo único que usa el navegador es si hay valor o no
        # (pendiente / ya impresa) — ver la nota larga en marcar_etiqueta.
        p["etiqueta_impresa_en"] = (
            p["etiqueta_impresa_en"].isoformat() if p["etiqueta_impresa_en"] else None
        )
        completar_foto(p)

    return render(request, "inventario/etiquetas.html", {
        "productos": productos,
        "tope": TOPE_TARJETAS,
        "sin_codigo": sum(1 for p in productos if not p["codigo_barras"]),
    })


@rol_requerido(CAJERO, GERENTE)
@require_POST
def marcar_etiqueta(request, producto_id):
    """Marca o desmarca a mano la etiqueta de UN producto como impresa.

    No imprime nada — es solo el estado que separa "pendiente" de "ya
    impresa" en la pantalla de Etiquetas. Existe para dos casos que la
    marca automática (al imprimir, en impresion.servicio) no cubre:
    productos que ya tenían su etiqueta puesta en el estante ANTES de que
    existiera este campo (Oscar los pone al día a mano, una vez), y
    corregir un marcado que quedó mal (una etiqueta que se mandó a
    imprimir pero salió en blanco, por ejemplo).
    """
    producto = get_object_or_404(
        productos_visibles(empresa_actual(request), incluir_agotados=True),
        pk=producto_id,
    )
    impresa = request.POST.get("impresa") == "1"
    producto.etiqueta_impresa_en = timezone.now() if impresa else None
    producto.save(update_fields=["etiqueta_impresa_en"])
    return JsonResponse({
        "ok": True,
        "impresa": impresa,
        "en": producto.etiqueta_impresa_en.isoformat() if producto.etiqueta_impresa_en else None,
    })


@rol_requerido(CAJERO, GERENTE)
@require_POST
def marcar_etiquetas_lote(request):
    """Lo mismo que marcar_etiqueta, para varios productos de una vez —
    la lista que está filtrada en pantalla en ese momento. Pensado para
    "ya imprimí/etiqueté todo esto, marcalo de una sola vez" en vez de
    producto por producto."""
    ids = request.POST.getlist("ids")
    impresa = request.POST.get("impresa") == "1"
    productos = productos_visibles(empresa_actual(request), incluir_agotados=True).filter(pk__in=ids)
    # Solo los que cambian de estado. Así el que ya estaba puesto conserva su
    # fecha, y la pantalla sabe exactamente qué revertir con «Deshacer»: el
    # 27/09/2026 un clic con el buscador vacío marcó el catálogo entero y no
    # había forma de volver atrás.
    cambian = productos.filter(etiqueta_impresa_en__isnull=impresa)
    ids_cambiados = list(cambian.values_list("pk", flat=True))
    valor = timezone.now() if impresa else None
    total = cambian.update(etiqueta_impresa_en=valor)
    return JsonResponse({"ok": True, "impresa": impresa, "total": total, "ids": ids_cambiados})


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


@rol_requerido(GERENTE)
@require_http_methods(["GET", "POST"])
def agotados(request):
    """Productos que se agotaron y la decisión de qué hacer con cada uno.

    Solo gerente: la lista lleva el último costo de compra. El cajero se
    entera de que algo se agotó en el POS y en el Inicio, sin costos.
    """
    empresa = empresa_actual(request)
    vista = request.GET.get("ver", "pendientes")
    if vista not in ag.VISTAS:
        vista = "pendientes"
    if request.method == "POST":
        aviso = get_object_or_404(
            Agotamiento, pk=request.POST.get("aviso"), producto__empresa=empresa
        )
        decision = request.POST.get("decision", "")
        if decision not in Agotamiento.Decision.values:
            messages.error(request, "Elija una decisión de la lista.")
        else:
            aviso.decision = decision
            aviso.nota = (request.POST.get("nota") or "").strip()[:200]
            # Volver a "Por decidir" borra quién decidió: si no, la lista
            # diría que alguien decidió algo que en realidad quedó abierto.
            pendiente = decision == Agotamiento.Decision.PENDIENTE
            aviso.decidido_por = None if pendiente else request.user
            aviso.decidido_en = None if pendiente else timezone.now()
            aviso.save(update_fields=["decision", "nota", "decidido_por", "decidido_en"])
            messages.success(request, f"{aviso.producto.nombre}: {aviso.get_decision_display()}.")
        return redirect(f"{request.path}?ver={vista}")
    return render(request, "inventario/agotados.html", {
        "title": "Productos agotados",
        "filas": ag.filas(empresa, vista),
        "vista": vista,
        "vistas": ag.VISTAS,
        "por_decidir": ag.por_decidir(empresa),
        "decisiones": Agotamiento.Decision.choices,
        "dias": ag.DIAS_VENTANA,
    })


@rol_requerido(GERENTE)
def agotados_excel(request):
    empresa = empresa_actual(request)
    vista = request.GET.get("ver", "pendientes")
    if vista not in ag.VISTAS:
        vista = "pendientes"
    r = HttpResponse(
        ag.excel(empresa, vista),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    nombre = f"agotados_{timezone.localdate():%Y-%m-%d}.xlsx"
    r["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return r
