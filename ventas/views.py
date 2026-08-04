import json
import logging
import smtplib

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from caja.services import sesion_abierta_de
from catalogo.consultas import productos_visibles
from catalogo.models import Producto
from core.roles import CAJERO, GERENTE, es_gerente, rol_requerido
from core.tenancy import documento_de_empresa

from . import services
from .cxc import registrar_abono
from .devoluciones import registrar_devolucion
from .models import Cliente, DocumentoCxC, FacturaVenta

logger = logging.getLogger(__name__)


@rol_requerido(CAJERO, GERENTE)
def pos(request):
    sesion = sesion_abierta_de(request.user)
    if not sesion:
        return redirect("caja:abrir")
    empresa = sesion.sucursal.empresa
    # Solo lo que hay en existencia (regla del 02/08/2026, ver
    # catalogo/consultas.py). Sin excepción y sin botón para ver los agotados:
    # el POS existe para cobrar, y el servicio de inventario rechaza cualquier
    # venta que deje el stock en negativo. Ofrecer en pantalla lo que la venta
    # va a rechazar solo produce un error a mitad del cobro, con el cliente
    # esperando.
    productos = list(
        productos_visibles(empresa)
        .select_related("categoria")
        .values("id", "sku", "nombre", "codigo_barras", "precio_venta",
                "stock_actual", "presentacion", "categoria__nombre", "imagen")
    )
    for p in productos:  # JSON-serializable + normalizar nombres de campos
        p["precio_venta"] = float(p["precio_venta"])
        p["stock_actual"] = float(p["stock_actual"])
        p["categoria"] = p.pop("categoria__nombre") or "Sin categoría"
        p["presentacion"] = p.get("presentacion") or ""
        p["imagen"] = (settings.MEDIA_URL + p["imagen"]) if p.get("imagen") else ""
    clientes = list(
        Cliente.objects.filter(activo=True, empresa=empresa)
        .values("id", "nombre", "limite_credito", "saldo")
    )
    for c in clientes:
        c["disponible"] = float(c["limite_credito"]) - float(c["saldo"])
        c["limite_credito"] = float(c["limite_credito"])
        c["saldo"] = float(c["saldo"])
    # Se pasan como objetos Python; el filtro json_script del template los
    # serializa una sola vez (pasar json.dumps aquí los codificaba dos veces
    # y llegaban al navegador como texto en vez de lista).
    return render(request, "ventas/pos.html", {
        "sesion": sesion,
        "productos": productos,
        "clientes": clientes,
    })


@rol_requerido(CAJERO, GERENTE)
@require_POST
def vender(request):
    sesion = sesion_abierta_de(request.user)
    if not sesion:
        return JsonResponse({"ok": False, "error": "No tiene una caja abierta."}, status=400)
    try:
        datos = json.loads(request.body)
        cliente = None
        if datos.get("cliente_id"):
            cliente = Cliente.objects.get(pk=datos["cliente_id"], activo=True)
        factura = services.registrar_venta(
            sesion_caja=sesion,
            lineas=datos.get("lineas", []),
            medio_pago=datos.get("medio_pago", ""),
            cliente=cliente,
            usuario=request.user,
            permitir_bajo_costo=es_gerente(request.user),  # el gerente puede vender bajo costo
        )
    except ValidationError as e:
        return JsonResponse({"ok": False, "error": " ".join(e.messages)}, status=400)
    except (json.JSONDecodeError, KeyError, Producto.DoesNotExist, Cliente.DoesNotExist):
        return JsonResponse({"ok": False, "error": "Datos de venta inválidos."}, status=400)
    return JsonResponse({
        "ok": True,
        "numero": factura.numero,
        "total": float(factura.total),
        "tiquete_url": reverse("ventas:tiquete", args=[factura.pk]),
    })


@rol_requerido(CAJERO, GERENTE)
def tiquete(request, factura_id):
    factura = documento_de_empresa(
        FacturaVenta.objects.select_related("empresa", "sucursal", "cliente").prefetch_related("lineas__producto"),
        request,
        pk=factura_id,
    )
    return render(request, "ventas/tiquete.html", {"f": factura})


@rol_requerido(CAJERO, GERENTE)
def factura(request, factura_id):
    """Versión de la venta para hoja carta/A4 o PDF: con logo y colores de
    marca. Pensada para enviar por correo o imprimir en impresora normal
    (a diferencia del tiquete, que es para impresora térmica angosta)."""
    f = documento_de_empresa(
        FacturaVenta.objects.select_related("empresa", "sucursal", "cliente").prefetch_related("lineas__producto"),
        request,
        pk=factura_id,
    )
    return render(request, "ventas/factura.html", {"f": f})


@rol_requerido(CAJERO, GERENTE)
@require_POST
def factura_enviar(request, factura_id):
    """Manda la factura a color por correo, en vez de solo poder verla en
    pantalla. Reusa la misma plantilla, oculta el botón de imprimir/enviar
    (que no tiene sentido dentro de un correo) con es_email=True."""
    f = documento_de_empresa(
        FacturaVenta.objects.select_related("empresa", "sucursal", "cliente").prefetch_related("lineas__producto"),
        request,
        pk=factura_id,
    )
    destinatario = (request.POST.get("destinatario") or "").strip()
    ctx = {"f": f}

    # El código de estado tiene que decir la verdad (auditoría 2026-07-28,
    # hallazgo BE-07). Antes se respondía 200 en los tres casos —éxito, fallo
    # del servidor de correo y falta de destinatario— y el problema se
    # señalaba solo con una variable de contexto. Consecuencia: ningún
    # monitoreo externo podía detectar que las facturas habían dejado de
    # salir, y en una venta a crédito una factura no entregada debilita la
    # posición de cobro. El mensaje en pantalla sigue siendo igual de amable;
    # lo que cambia es lo que la máquina reporta.
    if not destinatario:
        ctx["enviado_error"] = "Falta el correo del destinatario."
        return render(request, "ventas/factura.html", ctx, status=400)

    try:
        html = render_to_string("ventas/factura.html", {"f": f, "es_email": True})
        correo = EmailMessage(
            subject=f"Tu factura {f.numero} — {f.empresa.nombre}",
            body=html,
            to=[destinatario],
        )
        correo.content_subtype = "html"
        correo.send(fail_silently=False)
    except (smtplib.SMTPException, OSError) as e:
        # 502: el fallo no es del usuario ni de esta aplicación, sino del
        # servicio de correo del que dependemos.
        logger.exception("No se pudo enviar la factura %s a %s", f.numero, destinatario)
        ctx["enviado_error"] = str(e)
        return render(request, "ventas/factura.html", ctx, status=502)

    ctx["enviado_ok"] = True
    ctx["enviado_a"] = destinatario
    return render(request, "ventas/factura.html", ctx)


@rol_requerido(GERENTE)
@require_POST
def anular(request, factura_id):
    """Anula (reversa) una venta desde el sistema, con motivo obligatorio."""
    factura = documento_de_empresa(FacturaVenta, request, pk=factura_id)
    try:
        services.anular_factura(
            factura=factura, motivo=request.POST.get("motivo", ""), usuario=request.user,
        )
        messages.success(request, f"Venta {factura.numero} anulada: el inventario y la caja se revirtieron.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect("core:actividad")


@rol_requerido(GERENTE)
def devolver(request, factura_id):
    """Formulario para devolver solo algunos productos (o algunas unidades)
    de una venta, aunque sea días después. Distinto de anular: la factura
    sigue vigente, solo se reversan las líneas y cantidades que el cajero
    marque."""
    factura = documento_de_empresa(
        FacturaVenta.objects.select_related("cliente").prefetch_related("lineas__producto", "lineas__devoluciones"),
        request,
        pk=factura_id,
    )
    if request.method == "POST":
        lineas = []
        for linea in factura.lineas.all():
            cantidad = request.POST.get(f"cant_{linea.id}", "").strip()
            if cantidad:
                lineas.append({"linea_venta_id": linea.id, "cantidad": cantidad})
        try:
            dev = registrar_devolucion(
                factura=factura, lineas=lineas,
                motivo=request.POST.get("motivo", ""), usuario=request.user,
            )
            messages.success(
                request,
                f"Devolución {dev.numero} registrada por ₡{dev.total:.0f} sobre la venta {factura.numero}."
            )
            return redirect("core:actividad")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    filas = []
    for linea in factura.lineas.all():
        ya_devuelta = sum((d.cantidad for d in linea.devoluciones.all()), 0)
        disponible = linea.cantidad - ya_devuelta
        filas.append({
            "linea": linea,
            "ya_devuelta": ya_devuelta,
            "disponible": disponible,
        })
    return render(request, "ventas/devolver.html", {"factura": factura, "filas": filas})


@rol_requerido(CAJERO, GERENTE)
def estado_cuenta(request, cliente_id):
    cliente = documento_de_empresa(Cliente, request, pk=cliente_id)
    documentos = (
        cliente.cxc.select_related("factura")
        .prefetch_related("abonos")
        .order_by("-id")
    )
    return render(request, "ventas/estado_cuenta.html", {
        "cliente": cliente,
        "documentos": documentos,
    })


@rol_requerido(CAJERO, GERENTE)
@require_POST
def abonar(request, documento_id):
    # DocumentoCxC no tiene FK directa a empresa: se alcanza vía el cliente.
    documento = documento_de_empresa(
        DocumentoCxC, request, campo_empresa="cliente__empresa", pk=documento_id
    )
    try:
        registrar_abono(
            documento=documento,
            monto=request.POST.get("monto", "0"),
            medio=request.POST.get("medio", "EFE"),
            referencia=request.POST.get("referencia", ""),
            usuario=request.user,
        )
        messages.success(request, f"Abono registrado a {documento.factura.numero}.")
    except (ValidationError, ValueError) as e:
        msg = " ".join(e.messages) if isinstance(e, ValidationError) else "Monto inválido."
        messages.error(request, msg)
    return redirect("ventas:estado_cuenta", cliente_id=documento.cliente_id)
