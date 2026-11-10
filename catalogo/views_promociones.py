"""Pantallas de promociones (04/11/2026, pedido de Oscar). Solo gerente.

- Lista: vigentes, programadas, borradores y terminadas.
- Una promoción: datos (nombre, %, fechas), lista armada con la pistola,
  % por producto, avisos (bajo costo, precio subido, otra promoción),
  sugeridos (lo que no se vende), resultados y etiquetas de oferta.

Las reglas viven en catalogo/promociones.py; aquí solo se muestran y se
llaman. Las acciones de la lista (escanear, cambiar %, quitar) responden
JSON con la tabla ya armada, para que la pistola pueda seguir disparando sin
que la página se recargue en cada producto.

Buscar por nombre (09/11/2026, pedido de Oscar: un producto cuyo código de
barras no estaba registrado no se podía agregar): al escribir en el mismo
campo aparece una lista con foto, nombre, precio y existencia, con la
búsqueda inteligente de siempre (catalogo/palabras_clave). Se elige con un
clic; la pistola sigue funcionando igual.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.roles import GERENTE, rol_requerido
from core.tenancy import empresa_actual

from . import promociones as P
from .models import Producto, Promocion, PromocionProducto


def _fecha(texto, defecto):
    try:
        return datetime.strptime((texto or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return defecto


PLURAL = {"Vigente": "Vigentes", "Programada": "Programadas", "Borrador": "Borradores",
          "Vencida": "Ya pasaron", "Terminada": "Terminadas"}


@rol_requerido(GERENTE)
def lista(request):
    empresa = empresa_actual(request)
    if request.method == "POST":
        hoy = timezone.localdate()
        promo = Promocion.objects.create(
            empresa=empresa, nombre=(request.POST.get("nombre") or "Nueva promoción").strip()[:60],
            descuento_pct=20, inicio=hoy, fin=hoy + timedelta(days=6), creada_por=request.user)
        return redirect("catalogo:promocion", pk=promo.pk)
    promos = list(Promocion.objects.filter(empresa=empresa).prefetch_related("items"))
    grupos = {"Vigente": [], "Programada": [], "Borrador": [], "Vencida": [], "Terminada": []}
    for p in promos:
        p.estado_txt = P.estado_visible(p)
        p.n_items = len(p.items.all())
        grupos[p.estado_txt].append(p)
    return render(request, "catalogo/promociones.html", {
        "grupos": [(PLURAL[k], v) for k, v in grupos.items() if v], "hay": bool(promos),
    })


def _contexto(request, promo):
    items = list(promo.items.select_related("producto__empresa", "producto__impuesto", "promocion"))
    filas = [P.fila(i) for i in items]
    filas.reverse()   # lo último escaneado, arriba
    return {"promo": promo, "filas": filas, "resumen": P.resumen(filas), "estado": P.estado_visible(promo),
            "editable": promo.estado != Promocion.Estado.TERMINADA}


def _json(request, promo, aviso="", error="", nuevo=None, resultados=None):
    ctx = _contexto(request, promo)
    ctx["nuevo"] = nuevo
    return JsonResponse({
        "ok": not error, "aviso": aviso, "error": error, "resultados": resultados,
        "tabla": render_to_string("catalogo/_promo_tabla.html", ctx, request=request),
        "resumen": render_to_string("catalogo/_promo_resumen.html", ctx, request=request),
    })


@rol_requerido(GERENTE)
def detalle(request, pk):
    empresa = empresa_actual(request)
    promo = get_object_or_404(Promocion, pk=pk, empresa=empresa)
    if request.method == "POST":
        return _accion(request, promo)
    ctx = _contexto(request, promo)
    if request.GET.get("sugeridos"):
        ctx["sugeridos"] = P.sugeridos(empresa, promo)
    if promo.estado != Promocion.Estado.BORRADOR:
        ctx["resultados"] = P.resultados(promo)
    ctx["vencida"] = promo.estado == Promocion.Estado.TERMINADA or promo.fin < timezone.localdate()
    ctx["hoy"] = timezone.localdate()
    ctx["con_etiquetas"] = settings.PROMO_ETIQUETAS
    return render(request, "catalogo/promocion.html", ctx)


@rol_requerido(GERENTE)
def lista_para_marcar(request, pk):
    """Hoja para imprimir en carta y recorrer la tienda poniendo los puntos
    rojos (04/11/2026, pedido de Oscar: "comparar físicamente cuáles ya están
    marcados y cuáles faltan"). Va agrupada por categoría porque así está
    acomodada la exhibición: se marca un estante entero sin ir y venir."""
    empresa = empresa_actual(request)
    promo = get_object_or_404(Promocion, pk=pk, empresa=empresa)
    items = list(promo.items.select_related("producto__categoria__padre", "producto__impuesto", "promocion"))

    def grupo(p):
        c = p.categoria
        if c is None:
            return "Sin categoría"
        return f"{c.padre.nombre} › {c.nombre}" if c.padre_id else c.nombre

    grupos = {}
    for item in sorted(items, key=lambda i: (grupo(i.producto), i.producto.nombre.lower())):
        p = item.producto
        grupos.setdefault(grupo(p), []).append({
            "producto": p, "pct": item.pct, "precio": p.precio_venta,
            "oferta": P.precio_oferta(p.precio_venta, item.pct), "stock": p.stock_actual,
        })
    return render(request, "catalogo/promocion_lista.html", {
        "promo": promo, "grupos": list(grupos.items()), "total": len(items),
        "unidades": sum((i.producto.stock_actual for i in items), 0),
        "impreso": timezone.localtime(),
    })


def _accion(request, promo):
    accion = request.POST.get("accion", "")
    es_json = request.headers.get("Accept", "").startswith("application/json")
    try:
        if accion == "datos":
            if promo.estado == Promocion.Estado.TERMINADA:
                raise ValidationError("La promoción ya terminó: no se puede cambiar.")
            promo.nombre = (request.POST.get("nombre") or promo.nombre).strip()[:60]
            promo.etiqueta = (request.POST.get("etiqueta") or "").strip()[:24]
            pct = int(request.POST.get("descuento_pct") or promo.descuento_pct)
            if not 1 <= pct <= 90:
                raise ValidationError("El descuento tiene que estar entre 1 % y 90 %.")
            promo.descuento_pct = pct
            promo.inicio = _fecha(request.POST.get("inicio"), promo.inicio)
            promo.fin = _fecha(request.POST.get("fin"), promo.fin)
            if promo.fin < promo.inicio:
                raise ValidationError("La fecha de fin no puede ser antes que la de inicio.")
            promo.en_ofertas = request.POST.get("en_ofertas") == "on"
            promo.save()
            messages.success(request, "Datos guardados.")
        elif accion == "agregar":
            producto = P.buscar_producto(promo.empresa, request.POST.get("codigo"))
            if producto is None and es_json:
                # No es un código: puede ser un nombre («special»). Enter con
                # un nombre muestra la lista para elegir, no un error (Oscar,
                # 09/11/2026: escribía el nombre y apretaba Enter por costumbre).
                encontrados = _resultados(promo, request.POST.get("codigo"))
                if encontrados:
                    return _json(request, promo, aviso="Elegí el producto de la lista.", resultados=encontrados)
            if producto is None:
                raise ValidationError(f"No encontré el código «{request.POST.get('codigo', '').strip()}». "
                                      "Escribí parte del nombre y elegilo de la lista.")
            item, creado = P.agregar(promo, producto, request.user)
            aviso = f"{producto.nombre} agregado." if creado else f"{producto.nombre} ya estaba en la lista."
            if es_json:
                return _json(request, promo, aviso=aviso, nuevo=item.pk)
            messages.success(request, aviso)
        elif accion == "agregar_id":
            producto = Producto.objects.filter(pk=request.POST.get("producto") or 0, empresa=promo.empresa,
                                               activo=True).first()
            if producto is None:
                raise ValidationError("Ese producto ya no está disponible.")
            item, creado = P.agregar(promo, producto, request.user)
            aviso = f"{producto.nombre} agregado." if creado else f"{producto.nombre} ya estaba en la lista."
            if es_json:
                return _json(request, promo, aviso=aviso, nuevo=item.pk)
            messages.success(request, aviso)
        elif accion in ("agregar_varios",):
            agregados = 0
            for pid in request.POST.getlist("producto"):
                producto = Producto.objects.filter(pk=pid, empresa=promo.empresa, activo=True).first()
                if producto:
                    _, creado = P.agregar(promo, producto, request.user)
                    agregados += int(creado)
            messages.success(request, f"{agregados} producto(s) agregado(s).")
        elif accion in ("pct", "quitar", "bajo_costo"):
            item = get_object_or_404(PromocionProducto, pk=request.POST.get("item"), promocion=promo)
            if promo.estado == Promocion.Estado.TERMINADA:
                raise ValidationError("La promoción ya terminó.")
            if accion == "quitar":
                nombre = item.producto.nombre
                item.delete()
                aviso = f"{nombre} quitado."
            elif accion == "pct":
                valor = (request.POST.get("valor") or "").strip().replace("%", "")
                if not valor or int(valor) == promo.descuento_pct:
                    item.descuento_pct = None
                else:
                    pct = int(valor)
                    if not 1 <= pct <= 90:
                        raise ValidationError("El descuento tiene que estar entre 1 % y 90 %.")
                    item.descuento_pct = pct
                item.save(update_fields=["descuento_pct"])
                aviso = ""
            else:
                item.permitir_bajo_costo = request.POST.get("valor") == "1"
                item.save(update_fields=["permitir_bajo_costo"])
                aviso = ""
            if es_json:
                return _json(request, promo, aviso=aviso)
        elif accion == "activar":
            P.activar(promo, request.user)
            promo.refresh_from_db()
            messages.success(request, f"Promoción {P.estado_visible(promo).lower()}: "
                                      f"del {promo.inicio:%d/%m} al {promo.fin:%d/%m/%Y}.")
        elif accion == "pausar":
            # Volver a borrador (para corregir algo antes de que empiece, o
            # sacarla un rato). Las ventas hechas quedan como fueron.
            promo.estado = Promocion.Estado.BORRADOR
            promo.save(update_fields=["estado"])
            messages.info(request, "La promoción quedó en borrador: ya no se aplica hasta volver a activarla.")
        elif accion == "terminar":
            P.terminar(promo, request.user)
            messages.success(request, "Promoción terminada. Abajo está la lista de etiquetas de oferta para quitar."
                             if settings.PROMO_ETIQUETAS else "Promoción terminada: los precios vuelven a la normalidad.")
        elif accion == "eliminar":
            if promo.estado != Promocion.Estado.BORRADOR or promo.lineas_venta.exists():
                raise ValidationError("Solo se borra un borrador que nunca vendió nada.")
            promo.delete()
            messages.success(request, "Borrador eliminado.")
            return redirect("catalogo:promociones")
        elif accion == "etiquetas":
            if not settings.PROMO_ETIQUETAS:
                raise ValidationError("Las etiquetas de oferta están apagadas por ahora.")
            return _etiquetas(request, promo)
        else:
            raise ValidationError("Acción desconocida.")
    except (ValidationError, ValueError) as e:
        texto = " ".join(e.messages) if isinstance(e, ValidationError) else "Ese número no es válido."
        if es_json:
            return _json(request, promo, error=texto)
        messages.error(request, texto)
    return redirect("catalogo:promocion", pk=promo.pk)


def _etiquetas(request, promo):
    """Imprime una etiqueta de oferta por unidad en existencia (o 1)."""
    from impresion.servicio import ErrorDeImpresion, imprimir_etiquetas_oferta

    pares = []
    for item in promo.items.select_related("producto", "promocion"):
        p = item.producto
        precio = P.precio_oferta(p.precio_venta, item.pct)
        oferta = {"precio": precio, "precio_antes": p.precio_venta, "pct": item.pct,
                  "nombre": promo.texto, "hasta": promo.fin}
        copias = max(1, int(p.stock_actual)) if request.POST.get("por_unidad") else 1
        pares.append((p, oferta, copias))
    try:
        n = imprimir_etiquetas_oferta(pares)
    except ErrorDeImpresion as e:
        messages.error(request, f"No se pudieron imprimir: {e}")
    else:
        messages.success(request, f"{n} etiqueta(s) de oferta enviada(s) a la impresora de etiquetas.")
    return redirect("catalogo:promocion", pk=promo.pk)


@rol_requerido(GERENTE)
def buscar(request, pk):
    """Productos que coinciden con lo escrito, para elegirlos por nombre y
    foto. Máximo 12: si son más, se sigue escribiendo."""
    empresa = empresa_actual(request)
    promo = get_object_or_404(Promocion, pk=pk, empresa=empresa)
    return JsonResponse({"resultados": _resultados(promo, request.GET.get("q"))})


def _resultados(promo, q):
    """Lo que coincide por nombre/descripción (búsqueda inteligente), con foto."""
    from core.imagenes import datos_foto
    from core.templatetags.formato import crc

    from .palabras_clave import filtrar
    q = (q or "").strip()
    if len(q) < 2:
        return []
    qs = Producto.objects.filter(empresa=promo.empresa, activo=True, precio_venta__gt=0).order_by("nombre")
    ya = set(promo.items.values_list("producto_id", flat=True))
    return [{"id": p.pk, "nombre": p.nombre, "sku": p.sku, "presentacion": p.presentacion,
             "precio": crc(p.precio_venta), "stock": crc(p.stock_actual), "ya": p.pk in ya, **datos_foto(p)}
            for p in filtrar(qs, q, limite=12)]
