import json
import logging
import smtplib
from datetime import datetime
from decimal import InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db.models import Q
from django.utils import timezone
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from caja.services import sesion_abierta_de
from catalogo.consultas import productos_visibles
from catalogo.models import Producto
from core.imagenes import completar_foto
from core.pdf import html_a_pdf, logo_data_uri
from core.roles import CAJERO, GERENTE, es_gerente, rol_requerido
from core.tenancy import documento_de_empresa
from impresion import servicio as impresion
from impresion.servicio import ErrorDeImpresion

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
    productos = _filas_pos(productos_visibles(empresa))
    clientes = list(
        Cliente.objects.filter(activo=True, empresa=empresa)
        .values("id", "nombre", "limite_credito", "saldo", "email")
    )
    for c in clientes:
        # La resta se hace en Decimal (regla de dinero del proyecto) y solo se
        # convierte a float al final, para no arrastrar imprecisión binaria.
        c["disponible"] = float(c["limite_credito"] - c["saldo"])
        c["limite_credito"] = float(c["limite_credito"])
        c["saldo"] = float(c["saldo"])
    # Se pasan como objetos Python; el filtro json_script del template los
    # serializa una sola vez (pasar json.dumps aquí los codificaba dos veces
    # y llegaban al navegador como texto en vez de lista).
    return render(request, "ventas/pos.html", {
        "sesion": sesion,
        "productos": productos,
        "clientes": clientes,
        "es_gerente": es_gerente(request.user),
        "tipos_identificacion": Cliente.TipoIdentificacion.choices,
    })


def _filas_pos(queryset):
    """Productos como los necesita el POS en el navegador (JSON)."""
    filas = list(
        queryset.select_related("categoria")
        .values("id", "sku", "nombre", "codigo_barras", "precio_venta",
                "stock_actual", "presentacion", "categoria__nombre", "imagen", "mascota",
                "descripcion", "actualizado_en")
    )
    for p in filas:  # JSON-serializable + normalizar nombres de campos
        p["precio_venta"] = float(p["precio_venta"])
        p["stock_actual"] = float(p["stock_actual"])
        p["categoria"] = p.pop("categoria__nombre") or "Sin categoría"
        p["presentacion"] = p.get("presentacion") or ""
        p["mascota"] = p.get("mascota") or ""
        p["descripcion"] = p.get("descripcion") or ""
        completar_foto(p)
    return filas


@rol_requerido(CAJERO, GERENTE)
def producto_por_codigo(request):
    """Busca en la base un código que el POS no tiene en su lista.

    El POS carga los productos al abrir la pantalla (auditoría 26/09/2026,
    VEN-05). Lo que se ingresó después —Francisco recibiendo mercadería desde
    el celular— no se podía escanear hasta recargar, y lo que el sistema tiene
    en 0 salía como «No encontré ese producto» aunque existiera. Ahora el POS
    pregunta acá antes de rendirse, y el mensaje dice la verdad."""
    codigo = (request.GET.get("q") or "").strip()
    sesion = sesion_abierta_de(request.user)
    if not codigo or sesion is None:
        return JsonResponse({"ok": False, "error": "Falta el código."}, status=400)
    empresa = sesion.sucursal.empresa
    qs = Producto.objects.filter(activo=True, empresa=empresa).filter(
        Q(codigo_barras=codigo) | Q(sku=codigo)
    )
    producto = qs.first()
    if producto is None:
        return JsonResponse({"ok": False, "existe": False,
                             "error": f"No hay ningún producto con el código {codigo}. "
                                      "Búsquelo por nombre, o pida que lo registren en «Recibir mercadería»."})
    if producto.stock_actual <= 0:
        return JsonResponse({"ok": False, "existe": True,
                             "error": f"«{producto.nombre}» existe, pero el sistema dice que hay 0. "
                                      "Un gerente tiene que registrar la entrada de mercadería "
                                      "(o un ajuste) antes de venderlo."})
    return JsonResponse({"ok": True, "producto": _filas_pos(qs.filter(pk=producto.pk))[0]})


@rol_requerido(CAJERO, GERENTE)
@require_POST
def cliente_rapido(request):
    """Crea un cliente desde el POS sin salir de la venta (FE-03, TIQ-03).

    Solo los datos que sirven hoy: nombre, identificación y correo (para
    mandarle el recibo). Nace sin crédito: dar crédito es una decisión del
    gerente y se hace en el admin."""
    sesion = sesion_abierta_de(request.user)
    if sesion is None:
        return JsonResponse({"ok": False, "error": "No tiene una caja abierta."}, status=400)
    try:
        datos = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Datos inválidos."}, status=400)
    nombre = (datos.get("nombre") or "").strip()[:150]
    if not nombre:
        return JsonResponse({"ok": False, "error": "Escriba el nombre del cliente."}, status=400)
    email = (datos.get("email") or "").strip()[:254]
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({"ok": False, "error": "Ese correo no parece válido."}, status=400)
    tipo = datos.get("tipo_identificacion") or ""
    if tipo not in Cliente.TipoIdentificacion.values:
        tipo = ""
    identificacion = (datos.get("identificacion") or "").strip()[:30]
    empresa = sesion.sucursal.empresa
    if identificacion:
        existente = Cliente.objects.filter(empresa=empresa, identificacion=identificacion, activo=True).first()
        if existente is not None:
            return JsonResponse({"ok": True, "ya_existia": True, "cliente": _cliente_json(existente)})
    cliente = Cliente.objects.create(
        empresa=empresa, nombre=nombre, email=email, tipo_identificacion=tipo,
        identificacion=identificacion, telefono=(datos.get("telefono") or "").strip()[:30],
    )
    return JsonResponse({"ok": True, "ya_existia": False, "cliente": _cliente_json(cliente)})


def _cliente_json(c):
    return {"id": c.id, "nombre": c.nombre, "email": c.email,
            "limite_credito": float(c.limite_credito), "saldo": float(c.saldo),
            "disponible": float(c.limite_credito - c.saldo)}


@rol_requerido(CAJERO, GERENTE)
def historial(request):
    """Historial de ventas con buscador, para reimprimir o reenviar un
    tiquete (auditoría 26/09/2026, TIQ-03).

    Antes la única lista era «Actividad»: solo gerente, las últimas 40 y sin
    ningún enlace al tiquete. Un cajero no tenía cómo reimprimir. Acá el
    cajero ve y reimprime; devolver y anular siguen siendo del gerente."""
    from django.core.paginator import Paginator
    from django.db.models import Count

    from core.tenancy import empresa_actual

    empresa = empresa_actual(request)
    hoy = timezone.localdate()
    q = (request.GET.get("q") or "").strip()
    fecha_txt = request.GET.get("fecha")
    facturas = (
        FacturaVenta.objects.filter(empresa=empresa)
        .select_related("cliente", "usuario")
        .annotate(n_devoluciones=Count("devoluciones"))
        .order_by("-id")
    )
    fecha = None
    if q:
        # Un número suelto ("48") también encuentra FV-00000048.
        numero = f"FV-{int(q):08d}" if q.isdigit() else q
        facturas = facturas.filter(
            Q(numero__iexact=numero) | Q(numero__icontains=q) | Q(cliente__nombre__icontains=q)
            | Q(cliente__identificacion__icontains=q)
        )
    else:
        try:
            fecha = datetime.strptime(fecha_txt, "%Y-%m-%d").date() if fecha_txt else hoy
        except ValueError:
            fecha = hoy
        facturas = facturas.filter(creado_en__date=fecha)
    pagina = Paginator(facturas, 50).get_page(request.GET.get("pagina"))
    return render(request, "ventas/historial.html", {
        "pagina": pagina, "q": q, "fecha": fecha, "hoy": hoy,
        "es_gerente": es_gerente(request.user),
    })


@rol_requerido(CAJERO, GERENTE)
@require_POST
def vender(request):
    sesion = sesion_abierta_de(request.user)
    if not sesion:
        return JsonResponse({"ok": False, "error": "No tiene una caja abierta."}, status=400)
    clave_pos = None
    try:
        datos = json.loads(request.body)
        clave_pos = (str(datos.get("clave") or "").strip()[:40]) or None
        cliente = None
        if datos.get("cliente_id"):
            cliente = Cliente.objects.get(pk=datos["cliente_id"], activo=True, empresa=sesion.sucursal.empresa)
        factura = services.registrar_venta(
            sesion_caja=sesion,
            lineas=datos.get("lineas", []),
            medio_pago=datos.get("medio_pago", ""),
            cliente=cliente,
            usuario=request.user,
            permitir_bajo_costo=es_gerente(request.user),  # el gerente puede vender bajo costo
            permitir_descuento_alto=es_gerente(request.user),  # el gerente puede autorizar descuentos > 15% (SEC-001)
            permitir_regalia_alta=es_gerente(request.user),  # el gerente puede autorizar regalías > ₡5000 (SEC-006)
            pagos=datos.get("pagos"),
            clave_pos=clave_pos,
            monto_recibido=datos.get("recibido"),
        )
    except ValidationError as e:
        return JsonResponse({"ok": False, "error": " ".join(e.messages)}, status=400)
    except IntegrityError:
        # Dos envíos del mismo cobro chocaron en la base (VEN-02): el otro ya
        # quedó guardado. Se contesta con esa venta; nunca se crea una segunda.
        factura = FacturaVenta.objects.filter(clave_pos=clave_pos).first() if clave_pos else None
        if factura is None:
            logger.exception("Error de integridad al registrar una venta")
            return JsonResponse({"ok": False, "error": "No se pudo registrar la venta. Intente de nuevo."}, status=400)
        return _respuesta_venta(factura, repetida=True)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation):
        return JsonResponse({"ok": False, "error": "Datos de venta inválidos."}, status=400)
    except Producto.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Uno de los productos ya no está a la venta (lo desactivaron). "
                                                   "Quítelo de la venta y vuelva a cobrar."}, status=400)
    except Cliente.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Ese cliente ya no existe o está inactivo. Elija otro."}, status=400)

    # Un reenvío del mismo cobro (doble F1, la red que reintenta) trae la venta
    # que ya existía: se contesta igual, pero sin volver a imprimir.
    if getattr(factura, "repetida", False):
        return _respuesta_venta(factura, repetida=True)
    # Tiquete automático (decisión de Oscar, 05/09/2026): sale del rollo sin
    # que el cajero toque nada. Si la impresora falla —sin papel, apagada, el
    # cable flojo— la venta YA está registrada y NO se revierte por eso: se
    # avisa y el POS abre el tiquete en pantalla como respaldo. Anular una
    # venta buena porque no había papel sería mucho peor que un tiquete menos.
    #
    # Desde el 10/09/2026 el ERP corre en la nube y no ve la térmica: el
    # tiquete queda en una cola y lo saca el agente de la tienda. Por eso hay
    # que distinguir «impreso» de «encolado». Decirle al cajero «Tiquete
    # impreso» cuando en realidad quedó en cola sería mentirle: si el agente
    # está cerrado, él se entera cuando el cliente pide el comprobante.
    impreso, error_impresion, trabajo = False, "", None
    if settings.TIQUETE_AUTOMATICO:
        try:
            trabajo = impresion.imprimir_tiquete(factura)
            impreso = True
        except ErrorDeImpresion as e:
            error_impresion = str(e)
            logger.warning("Venta %s registrada pero sin tiquete: %s", factura.numero, e)
    return _respuesta_venta(factura, impreso=impreso, error_impresion=error_impresion, trabajo=trabajo)


def _respuesta_venta(factura, *, impreso=False, error_impresion="", trabajo=None, repetida=False):
    """Lo que el POS necesita para cerrar la venta en pantalla: número, total,
    vuelto y cómo seguir el tiquete (reimprimir, enviar, ¿salió?)."""
    return JsonResponse({
        "ok": True,
        "repetida": repetida,
        "id": factura.pk,
        "numero": factura.numero,
        "total": float(factura.total),
        "vuelto": float(factura.vuelto) if factura.vuelto is not None else None,
        "recibido": float(factura.monto_recibido) if factura.monto_recibido is not None else None,
        "correo_cliente": factura.cliente.email if factura.cliente_id else "",
        "tiquete_url": reverse("ventas:tiquete", args=[factura.pk]),
        "reimprimir_url": reverse("impresion:tiquete", args=[factura.pk]),
        "enviar_url": reverse("ventas:factura_enviar", args=[factura.pk]),
        "impreso": impreso,
        # Por la cola del agente: lo único seguro es que quedó encolado. El POS
        # pregunta a `trabajo_url` si salió de verdad (TIQ-02).
        "encolado": trabajo is not None,
        "trabajo_url": reverse("impresion:estado_trabajo", args=[trabajo.pk]) if trabajo else "",
        "error_impresion": error_impresion,
    })


@rol_requerido(CAJERO, GERENTE)
def tiquete(request, factura_id):
    factura = documento_de_empresa(
        FacturaVenta.objects.select_related("empresa", "sucursal", "cliente", "usuario")
        .prefetch_related("lineas__producto", "pagos"),
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


def _correo_configurado() -> bool:
    """¿Este servidor manda correos de verdad?

    Sin clave de correo, Django usa el backend de consola: "envía" a la
    terminal y no a nadie. En la computadora de desarrollo eso está bien; en
    la tienda significaba que la pantalla decía «enviado» y el cliente nunca
    recibía nada (auditoría 26/09/2026, TIQ-06)."""
    return not settings.EMAIL_BACKEND.endswith("console.EmailBackend") or settings.DEBUG


def _enviar_recibo(f, destinatario):
    """Arma y manda el recibo. Lanza OSError/SMTPException si el servicio de
    correo falla; quien llama decide cómo contarlo."""
    # El recibo va como PDF ADJUNTO, no como cuerpo del correo (02/09/2026).
    #
    # Antes el HTML del recibo era el cuerpo del mensaje. Se veía bien en el
    # navegador y descuadrado en Outlook, que dibuja los correos con el
    # motor de Word y no entiende flexbox: las columnas se montaban unas
    # sobre otras y el logo salía como un cuadrito roto.
    #
    # En PDF el diseño llega idéntico a cualquier cliente de correo, en el
    # celular y al imprimirlo. Y es lo que la gente espera de un recibo.
    html = render_to_string(
        "ventas/factura.html",
        {"f": f, "es_email": True, "logo_src": logo_data_uri()},
    )
    pdf = html_a_pdf(html)

    if pdf:
        cuerpo = render_to_string("ventas/correo_recibo.txt", {"f": f})
        correo = EmailMessage(
            subject=f"Tu recibo {f.numero} — {f.empresa.nombre}",
            body=cuerpo,
            to=[destinatario],
        )
        correo.attach(f"Recibo-{f.numero}.pdf", pdf, "application/pdf")
    else:
        # Sin Chromium instalado se manda como antes: feo pero llega.
        # Ver core/pdf.py para el porqué de no abortar.
        logger.warning("Recibo %s enviado sin PDF: Chromium no disponible.", f.numero)
        correo = EmailMessage(
            subject=f"Tu recibo {f.numero} — {f.empresa.nombre}",
            body=html,
            to=[destinatario],
        )
        correo.content_subtype = "html"
    correo.send(fail_silently=False)


@rol_requerido(CAJERO, GERENTE)
@require_POST
def factura_enviar(request, factura_id):
    """Manda el recibo a color por correo, en vez de solo poder verlo en
    pantalla. Reusa la misma plantilla, oculta el botón de imprimir/enviar
    (que no tiene sentido dentro de un correo) con es_email=True.

    Contesta en JSON si la llamada viene del POS (26/09/2026, TIQ-03): así se
    manda desde la misma pantalla de cobro, sin salir de la venta. El correo
    va en su propia petición, DESPUÉS de cobrar: si falla, la venta ya está
    hecha y no se toca."""
    f = documento_de_empresa(
        FacturaVenta.objects.select_related("empresa", "sucursal", "cliente").prefetch_related("lineas__producto"),
        request,
        pk=factura_id,
    )
    destinatario = (request.POST.get("destinatario") or "").strip()
    quiere_json = "application/json" in request.headers.get("Accept", "")
    ctx = {"f": f}

    def responder(error="", status=200):
        if quiere_json:
            return JsonResponse({"ok": not error, "error": error, "enviado_a": destinatario}, status=status)
        if error:
            ctx["enviado_error"] = error
        else:
            ctx["enviado_ok"] = True
            ctx["enviado_a"] = destinatario
        return render(request, "ventas/factura.html", ctx, status=status)

    # El código de estado tiene que decir la verdad (auditoría 2026-07-28,
    # hallazgo BE-07). Antes se respondía 200 en los tres casos —éxito, fallo
    # del servidor de correo y falta de destinatario— y el problema se
    # señalaba solo con una variable de contexto. Consecuencia: ningún
    # monitoreo externo podía detectar que las facturas habían dejado de
    # salir, y en una venta a crédito una factura no entregada debilita la
    # posición de cobro. El mensaje en pantalla sigue siendo igual de amable;
    # lo que cambia es lo que la máquina reporta.
    if not destinatario:
        return responder("Falta el correo del destinatario.", 400)
    try:
        validate_email(destinatario)
    except ValidationError:
        return responder("Ese correo no parece válido. Revíselo.", 400)
    if not _correo_configurado():
        logger.error("Recibo %s NO enviado: el servidor no tiene correo configurado.", f.numero)
        return responder("El envío de correos no está configurado en el servidor. "
                         "Avísele al administrador; mientras tanto, imprima el tiquete.", 503)
    try:
        _enviar_recibo(f, destinatario)
    except (smtplib.SMTPException, OSError) as e:
        # 502: el fallo no es del usuario ni de esta aplicación, sino del
        # servicio de correo del que dependemos.
        logger.exception("No se pudo enviar la factura %s a %s", f.numero, destinatario)
        return responder(f"No se pudo enviar el correo: {e}", 502)

    # Si el cliente no tenía correo guardado, se le guarda: la próxima vez ya
    # aparece puesto.
    if f.cliente_id and not f.cliente.email:
        Cliente.objects.filter(pk=f.cliente_id).update(email=destinatario)
    return responder()


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
    # Vuelve a la pantalla desde donde se anuló (Actividad o el Historial).
    # Solo rutas internas: un "volver" con http:// sería un redirector abierto.
    volver = (request.POST.get("volver") or "").strip()
    if volver.startswith("/") and not volver.startswith("//"):
        return redirect(volver)
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
def historial_compras(request, cliente_id):
    """Todas las compras del cliente (contado y crédito), a diferencia de
    `estado_cuenta` que solo muestra los documentos de CxC (venta a
    crédito). Bloque 1, 2026-08-28: no existía una vista con el historial
    completo — `Cliente.compras` (FacturaVenta.cliente, related_name
    "compras") ya traía el dato, solo faltaba la pantalla."""
    cliente = documento_de_empresa(Cliente, request, pk=cliente_id)
    # Se muestran también las anuladas (marcadas con su insignia): un
    # historial que las esconde no es un historial completo, y el resto del
    # sistema (facturas, devoluciones) sigue el mismo criterio de dejar todo
    # a la vista en vez de ocultarlo.
    facturas = (
        cliente.compras
        .prefetch_related("lineas__producto")
        .order_by("-creado_en")
    )
    return render(request, "ventas/historial_compras.html", {
        "cliente": cliente,
        "facturas": facturas,
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
