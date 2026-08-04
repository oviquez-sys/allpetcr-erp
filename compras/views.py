import base64
import json
import logging
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
from core.tenancy import documento_de_empresa, empresa_actual

from . import services
from .models import Compra, Proveedor

logger = logging.getLogger(__name__)


def _generar_sku():
    """Código interno único con precisión de microsegundo; si por alguna
    razón ya existiera (reloj repetido), reintenta con un sufijo aleatorio."""
    from django.utils.crypto import get_random_string

    for _ in range(5):
        candidato = f"NP{timezone.now():%y%m%d%H%M%S%f}"
        if not Producto.objects.filter(sku=candidato).exists():
            return candidato
    return f"NP{get_random_string(12).upper()}"


# --- Validación de fotos subidas (auditoría 2026-07-28, hallazgo SEG-06) ---
#
# Antes se deducía la extensión del texto que mandaba el navegador
# (`data:image/XXX;base64`) y se escribía el archivo con ESE nombre, sin mirar
# el contenido ni limitar el tamaño. Tres agujeros:
#   1. Un cliente podía declarar `data:image/svg+xml` y subir un SVG con un
#      <script> dentro. Como MEDIA se sirve desde el mismo dominio del ERP,
#      abrir esa "foto" ejecutaba código con la sesión del usuario.
#   2. Igual con .html, .js o cualquier extensión inventada.
#   3. Sin tope de tamaño, un base64 grande llenaba el disco del servidor.
#
# Ahora no se le cree nada al cliente: el formato se deduce de los primeros
# bytes del archivo (la firma real), y solo se aceptan PNG, JPEG y WebP.
# Un SVG no tiene firma binaria: no pasa. Un HTML tampoco.
TAMANO_MAX_FOTO = 5 * 1024 * 1024  # 5 MB ya decodificados

# Firma binaria → extensión. Son los "números mágicos" del inicio del archivo.
_FIRMAS = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)


def _extension_real(img_bytes):
    """Extensión deducida del CONTENIDO, o None si no es una imagen aceptada.

    Devolver None significa "esto no es una foto válida" y el llamador debe
    rechazarlo, no adivinar.
    """
    for firma, ext in _FIRMAS:
        if img_bytes.startswith(firma):
            return ext
    # WebP: "RIFF" + 4 bytes de tamaño + "WEBP"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return ".webp"
    return None


def _validar_foto(img_bytes):
    """Devuelve la extensión a usar. Lanza ValidationError si algo no cuadra.

    Si Pillow está instalado se añade una segunda verificación: que el archivo
    se pueda abrir realmente como imagen. No es obligatorio —la firma binaria
    ya cierra el vector de ejecución— pero atrapa archivos corruptos.
    """
    if len(img_bytes) > TAMANO_MAX_FOTO:
        raise ValidationError(
            f"La foto pesa más de {TAMANO_MAX_FOTO // (1024 * 1024)} MB. Usá una más liviana."
        )
    ext = _extension_real(img_bytes)
    if ext is None:
        raise ValidationError("El archivo no es una imagen PNG, JPG o WebP válida.")
    try:
        from io import BytesIO

        from PIL import Image  # opcional: si no está instalado, se omite
    except ImportError:
        return ext
    try:
        Image.open(BytesIO(img_bytes)).verify()
    except Exception as e:  # noqa: BLE001 — cualquier fallo aquí es "no es imagen"
        raise ValidationError("La imagen está dañada o no se puede leer.") from e
    return ext


@rol_requerido(GERENTE)
def nueva(request):
    """Pantalla para registrar mercadería nueva: buscar productos (con foto,
    como en el POS), poner cantidad y costo, y registrar. Todo en un solo
    paso: crea la compra y la recibe de inmediato (sube stock, recalcula
    costo promedio y genera el asiento), para minimizar pasos y errores."""
    empresa = empresa_actual(request)
    # ── EXCEPCIÓN DELIBERADA a la regla "solo en existencia" del 02/08/2026 ──
    # Acá NO se usa catalogo.consultas.productos_visibles, y no es un olvido.
    # Esta es la pantalla que hace que un producto agotado deje de estarlo.
    # Si el filtro se aplicara: un producto que llega a cero no se podría
    # seleccionar para recibirlo, así que su stock nunca subiría, así que
    # nunca volvería a aparecer en ninguna pantalla. Se agota una vez y
    # desaparece del sistema para siempre. Está verificado en
    # core/test_arquitectura.py para que nadie lo "corrija" por consistencia.
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
    empresa = empresa_actual(request)
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
    empresa = empresa_actual(request)
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
        #
        # Seguir sin foto cuando algo falla es una decisión razonable: el
        # producto ya se creó y bloquear la compra por una imagen sería peor
        # servicio. Lo que NO es razonable es no dejar rastro (auditoría
        # 2026-07-28, hallazgo BE-03): antes esto era un `except Exception:
        # pass` mudo, así que las fotos que no aparecían no tenían explicación
        # posible. Ahora el fallo queda en el log y el usuario recibe el aviso.
        foto_base64 = datos.get("foto_base64")
        aviso_foto = ""
        if foto_base64:
            try:
                _, data = foto_base64.split(",", 1)
                img_data = base64.b64decode(data, validate=True)
                ext = _validar_foto(img_data)  # rechaza SVG, HTML y archivos enormes
                # El nombre lo arma el servidor a partir del SKU: el cliente no
                # elige ni el nombre ni la extensión del archivo en disco.
                archivo = f"{producto.sku}{ext}"
                destino = Path(settings.MEDIA_ROOT) / "productos"
                destino.mkdir(parents=True, exist_ok=True)
                (destino / archivo).write_bytes(img_data)
                producto.imagen = f"productos/{archivo}"
                producto.save(update_fields=["imagen"])
            except ValidationError as e:
                aviso_foto = " ".join(e.messages)
                logger.warning("Foto rechazada para %s: %s", producto.sku, aviso_foto)
            except (ValueError, OSError):
                aviso_foto = "No se pudo guardar la foto. El producto quedó creado sin imagen."
                logger.exception("Fallo al guardar la foto de %s", producto.sku)

    except (json.JSONDecodeError, KeyError, TypeError, InvalidOperation):
        return JsonResponse({"ok": False, "error": "Datos de producto inválidos."}, status=400)
    except ValidationError as e:
        return JsonResponse({"ok": False, "error": " ".join(e.messages)}, status=400)

    return JsonResponse({
        "ok": True,
        "aviso": aviso_foto,  # vacío si la foto se guardó bien o no se mandó
        "producto": {
            "id": producto.id, "sku": producto.sku, "nombre": producto.nombre,
            "codigo_barras": producto.codigo_barras, "costo_promedio": 0.0,
            "stock_actual": 0.0, "presentacion": producto.presentacion,
            "categoria": categoria.nombre if categoria else "Sin categoría",
            "imagen": (settings.MEDIA_URL + producto.imagen) if producto.imagen else "",
        },
    })
