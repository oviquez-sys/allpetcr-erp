import base64
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogo.models import Categoria, Producto
from core.models import Empresa, Sucursal
from core.roles import GERENTE, rol_requerido
from core.tenancy import documento_de_empresa

from . import services
from .models import Compra, Proveedor


def _generar_sku():
    """Código interno único con precisión de microsegundo; si por alguna
    razón ya existiera (reloj repetido), reintenta con un sufijo aleatorio."""
    from django.utils.crypto import get_random_string

    for _ in range(5):
        candidato = f"NP{timezone.now():%y%m%d%H%M%S%f}"
        if not Producto.objects.filter(sku=candidato).exists():
            return candidato
    return f"NP{get_random_string(12).upper()}"


def _extension_de_base64(b64_str):
    """Extrae la extensión del archivo de un data URL (ej. 'data:image/png;base64,...' -> '.png')."""
    try:
        tipo = b64_str.split(";")[0].split("/")[1]  # "image/png" -> "png"
        return f".{tipo}"
    except (IndexError, AttributeError):
        return ".png"


@rol_requerido(GERENTE)
def nueva(request):
    """Pantalla para registrar mercadería nueva: buscar productos (con foto,
    como en el POS), poner cantidad y costo, y registrar. Todo en un solo
    paso: crea la compra y la recibe de inmediato (sube stock, recalcula
    costo promedio y genera el asiento), para minimizar pasos y errores."""
    empresa = Empresa.objects.first()
    productos = list(
        Producto.objects.filter(activo=True, empresa=empresa)
        .select_related("categoria")
        .values("id", "sku", "nombre", "codigo_barras", "costo_promedio",
                "stock_actual", "presentacion", "categoria__nombre", "imagen")
    )
    for p in productos:
        p["costo_promedio"] = float(p["costo_promedio"])
        p["stock_actual"] = float(p["stock_actual"])
        p["categoria"] = p.pop("categoria__nombre") or "Sin categoría"
        p["presentacion"] = p.get("presentacion") or ""
        p["imagen"] = (settings.MEDIA_URL + p["imagen"]) if p.get("imagen") else ""
    proveedores = list(
        Proveedor.objects.filter(activo=True, empresa=empresa).values("id", "nombre").order_by("nombre")
    )
    return render(request, "compras/nueva.html", {
        "productos": productos,
        "proveedores": proveedores,
    })


@rol_requerido(GERENTE)
@require_POST
def registrar(request):
    empresa = Empresa.objects.first()
    try:
        datos = json.loads(request.body)
        sucursal = Sucursal.objects.filter(empresa=empresa, activa=True).first()
        if sucursal is None:
            return JsonResponse({"ok": False, "error": "No hay una sucursal activa configurada."}, status=400)

        proveedor_id = datos.get("proveedor_id")
        proveedor_nuevo = (datos.get("proveedor_nuevo") or "").strip()
        if proveedor_id:
            proveedor = Proveedor.objects.get(pk=proveedor_id, empresa=empresa)
        elif proveedor_nuevo:
            proveedor, _ = Proveedor.objects.get_or_create(empresa=empresa, nombre=proveedor_nuevo)
        else:
            return JsonResponse({"ok": False, "error": "Elegí un proveedor o escribí uno nuevo."}, status=400)

        lineas_in = datos.get("lineas", [])
        if not lineas_in:
            return JsonResponse({"ok": False, "error": "Agregá al menos un producto."}, status=400)
        lineas = []
        for l in lineas_in:
            producto = Producto.objects.get(pk=l["producto_id"], empresa=empresa)
            lineas.append({
                "producto": producto,
                "cantidad": l["cantidad"],
                "costo_unitario": l["costo_unitario"],
            })

        compra = services.crear_compra(
            proveedor=proveedor,
            sucursal=sucursal,
            lineas=lineas,
            forma_pago=datos.get("forma_pago", "CON"),
            factura_proveedor=datos.get("factura_proveedor", ""),
            usuario=request.user,
        )
        services.recibir_compra(compra=compra, usuario=request.user)
    except ValidationError as e:
        return JsonResponse({"ok": False, "error": " ".join(e.messages)}, status=400)
    except (json.JSONDecodeError, KeyError, Producto.DoesNotExist, Proveedor.DoesNotExist):
        return JsonResponse({"ok": False, "error": "Datos de compra inválidos."}, status=400)

    return JsonResponse({"ok": True, "numero": compra.numero, "total": float(compra.total)})


@rol_requerido(GERENTE)
@require_POST
def anular(request, compra_id):
    """Anula (reversa) una compra recibida por error."""
    compra = documento_de_empresa(Compra, request, pk=compra_id)
    try:
        services.anular_compra(compra=compra, motivo=request.POST.get("motivo", ""), usuario=request.user)
        messages.success(request, f"Compra {compra.numero} anulada: el inventario y la contabilidad se revirtieron.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect("core:actividad")


@rol_requerido(GERENTE)
@require_POST
def producto_nuevo(request):
    """Alta rápida de un producto que nunca se había comprado antes (no
    existe todavía en el catálogo). Se usa desde 'Recibir mercadería' cuando
    el buscador no lo encuentra, para no obligar a pasar por el admin."""
    empresa = Empresa.objects.first()
    try:
        datos = json.loads(request.body)
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            return JsonResponse({"ok": False, "error": "Ponele un nombre al producto."}, status=400)
        precio_venta = Decimal(str(datos.get("precio_venta") or "0"))
        if precio_venta <= 0:
            return JsonResponse({"ok": False, "error": "Poné un precio de venta válido."}, status=400)

        categoria = None
        cat_nombre = (datos.get("categoria") or "").strip()
        if cat_nombre:
            categoria, _ = Categoria.objects.get_or_create(nombre=cat_nombre)

        # Código interno autogenerado: el usuario no tiene que inventar un SKU.
        sku = _generar_sku()
        producto = Producto.objects.create(
            empresa=empresa, sku=sku, nombre=nombre, categoria=categoria,
            codigo_barras=sku, presentacion=(datos.get("presentacion") or "").strip(),
            precio_venta=precio_venta,
        )

        # Procesar foto si la hay (base64: "data:image/png;base64,...")
        foto_base64 = datos.get("foto_base64")
        if foto_base64:
            try:
                _, data = foto_base64.split(",", 1)
                img_data = base64.b64decode(data)
                ext = _extension_de_base64(foto_base64)
                archivo = f"{producto.sku}{ext}"
                destino = Path(settings.MEDIA_ROOT) / "productos"
                destino.mkdir(parents=True, exist_ok=True)
                (destino / archivo).write_bytes(img_data)
                producto.imagen = f"productos/{archivo}"
                producto.save(update_fields=["imagen"])
            except Exception:
                pass  # Si la foto no se puede procesar, simplemente seguir sin ella

    except (json.JSONDecodeError, KeyError, TypeError, InvalidOperation):
        return JsonResponse({"ok": False, "error": "Datos de producto inválidos."}, status=400)
    except ValidationError as e:
        return JsonResponse({"ok": False, "error": " ".join(e.messages)}, status=400)

    return JsonResponse({
        "ok": True,
        "producto": {
            "id": producto.id, "sku": producto.sku, "nombre": producto.nombre,
            "codigo_barras": producto.codigo_barras, "costo_promedio": 0.0,
            "stock_actual": 0.0, "presentacion": producto.presentacion,
            "categoria": categoria.nombre if categoria else "Sin categoría",
            "imagen": (settings.MEDIA_URL + producto.imagen) if producto.imagen else "",
        },
    })
