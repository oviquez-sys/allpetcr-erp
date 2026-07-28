import json
import os
from datetime import datetime

import anthropic
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from compras.models import Compra
from ventas.models import DevolucionVenta, FacturaVenta

from . import reportes as rep
from .chat_tools import ejecutar_herramienta, herramientas_para
from .dashboard import indicadores
from .models import ChatMensaje, Empresa
from .roles import GERENTE, es_gerente, rol_de, rol_requerido

# Cuántas preguntas por día puede hacer un mismo usuario. Frena tanto abuso
# como facturas sorpresa; configurable sin tocar código.
CHAT_LIMITE_DIARIO = int(os.environ.get("CHAT_LIMITE_DIARIO", "40"))
# Cuántas rondas de "usar herramienta -> ver resultado" se permiten antes de
# forzar una respuesta. Evita loops infinitos si el modelo insiste en pedir
# herramientas sin parar.
CHAT_MAX_RONDAS_HERRAMIENTAS = 4


@staff_member_required
def dashboard(request):
    empresa = Empresa.objects.first()
    ctx = {
        "es_gerente": es_gerente(request.user),
        "rol": rol_de(request.user),
    }
    if empresa is None:
        ctx["sin_empresa"] = True
        return render(request, "core/dashboard.html", ctx)
    ctx.update(indicadores(empresa))
    ctx["empresa"] = empresa
    return render(request, "core/dashboard.html", ctx)


@rol_requerido(GERENTE)
def actividad(request):
    """Bitácora de ventas y compras recientes con opción de anular, y un
    historial separado de anulaciones (quién, cuándo, por qué): la vista
    anti-fraude, porque anular es el punto donde se esconde el robo."""
    ventas = (FacturaVenta.objects
              .select_related("cliente", "usuario", "anulada_por")
              .order_by("-id")[:40])
    compras = (Compra.objects
               .select_related("proveedor", "usuario", "anulada_por")
               .order_by("-id")[:40])
    ventas_anuladas = (FacturaVenta.objects
                       .filter(estado=FacturaVenta.Estado.ANULADA)
                       .select_related("anulada_por").order_by("-anulada_en")[:50])
    compras_anuladas = (Compra.objects
                        .filter(estado=Compra.Estado.ANULADA)
                        .select_related("anulada_por").order_by("-anulada_en")[:50])
    devoluciones = (DevolucionVenta.objects
                    .select_related("factura", "usuario").order_by("-creado_en")[:50])
    return render(request, "core/actividad.html", {
        "ventas": ventas,
        "compras": compras,
        "ventas_anuladas": ventas_anuladas,
        "compras_anuladas": compras_anuladas,
        "devoluciones": devoluciones,
    })


# ==========================================================================
#  CENTRO DE REPORTES
#  Un solo lugar que agrupa todos los reportes del sistema y aloja los que
#  antes vivían fijos en el Inicio (más vendidos, stock, valor de inventario).
# ==========================================================================

def _parse_fecha(valor, por_defecto):
    """Convierte 'YYYY-MM-DD' del formulario a date; si viene vacío o mal, usa
    el valor por defecto. Nunca revienta por una fecha inválida del usuario."""
    if not valor:
        return por_defecto
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return por_defecto


@rol_requerido(GERENTE)
def reportes(request):
    """Hub del centro de reportes: enlaces organizados por categoría."""
    return render(request, "core/reportes.html", {})


@rol_requerido(GERENTE)
def reporte_mas_vendidos(request):
    empresa = Empresa.objects.first()
    if empresa is None:
        return render(request, "core/reporte_mas_vendidos.html", {"sin_empresa": True})
    desde_def, hasta_def = rep._rango_por_defecto()
    desde = _parse_fecha(request.GET.get("desde"), desde_def)
    hasta = _parse_fecha(request.GET.get("hasta"), hasta_def)
    ctx = rep.mas_vendidos(empresa, desde, hasta)
    return render(request, "core/reporte_mas_vendidos.html", ctx)


@rol_requerido(GERENTE)
def reporte_stock(request):
    empresa = Empresa.objects.first()
    if empresa is None:
        return render(request, "core/reporte_stock.html", {"sin_empresa": True})
    solo_bajo = request.GET.get("filtro") != "todos"
    ctx = rep.niveles_stock(empresa, solo_bajo=solo_bajo)
    ctx["solo_bajo"] = solo_bajo
    return render(request, "core/reporte_stock.html", ctx)


@rol_requerido(GERENTE)
def reporte_inventario(request):
    empresa = Empresa.objects.first()
    if empresa is None:
        return render(request, "core/reporte_inventario.html", {"sin_empresa": True})
    ctx = rep.valor_inventario(empresa)
    return render(request, "core/reporte_inventario.html", ctx)


# Mapa real de navegación del sistema. El chat de ayuda solo debe hablar de
# lo que existe acá — nada de menús o pasos inventados.
SYSTEM_PROMPT_CHAT = """Eres el asistente de ayuda del ERP AllPet (allpetcr.com), \
una empresa costarricense de venta de productos para mascotas. Ayudás a \
cajeros y gerentes a usar el sistema.

REGLA MÁS IMPORTANTE: Solo conocés las secciones y rutas listadas abajo. Si te \
preguntan algo sobre una función que no está en esta lista, decí claramente que \
no existe o que no estás seguro — NUNCA inventes menús, botones o pasos que no \
se mencionan acá.

MAPA REAL DEL SISTEMA:

Inicio (/) — Panel principal: KPIs del mes (ganancia, ventas, efectivo en caja, \
por cobrar), accesos rápidos, gráfico de tendencia de ventas de los últimos 7 días.

Acceso Rápido desde Inicio:
- "Vender" → /pos/ — Punto de venta (POS). Todos los cajeros pueden vender acá.
- "Abrir caja" (/caja/abrir/) o "Cerrar caja" (/caja/cerrar/) según el estado actual.
- "Códigos" → /inventario/etiquetas/ — Generar/imprimir etiquetas con código de barras.
- "Recibir" → /compras/ — Registrar mercadería que llega de un proveedor \
(solo gerentes).
- "Reportes" → /reportes/ — Centro de reportes (solo gerentes).
- "Admin" → /admin/ — Panel de administración de Django (gestión de usuarios, \
productos, catálogo, configuración; solo gerentes).
- "Reversas" → /actividad/ — Ver actividad reciente y anular ventas (reversar \
una venta hecha por error).

Ventas (dentro de /pos/):
- Vender: se arma la venta en el POS, se elige medio de pago (efectivo, \
tarjeta, SINPE Móvil, o crédito/CxC) y se cobra.
- Después de cada venta se genera un tiquete térmico (para impresora de \
recibos) y también existe una "factura a color" en hoja completa (con logo y \
colores de marca) para enviar por correo o imprimir en impresora normal — hay \
un link para pasar de una versión a la otra.
- Se puede anular una venta completa, o hacer una devolución parcial de \
algunos productos/cantidades.
- Estado de cuenta de un cliente: para ver y cobrar saldos pendientes (crédito/CxC).

Precios (/precios/):
- Buscar un producto por nombre, código o código de barras.
- Ver costo promedio, precio de venta, margen % y markup % de cada producto.
- Entrar al detalle de un producto para cambiar su precio de venta (queda \
registrado el cambio, quién lo hizo y por qué) y ver su historial de precios \
y de costos (kardex).

Inventario:
- Ajuste de inventario (/inventario/ajuste/) — corregir el stock de un \
producto cuando no coincide con la realidad (rotura, pérdida, conteo físico).
- Etiquetas/códigos de barra (/inventario/etiquetas/) — generar e imprimir \
etiquetas para los productos.

Compras (/compras/, solo gerentes):
- Registrar una compra nueva (mercadería que entra) — esto sube el stock y \
recalcula el costo promedio del producto.
- Se puede dar de alta un producto nuevo desde ahí si no existe en el catálogo.
- Las compras también se pueden anular.

Reportes (/reportes/, solo gerentes):
- Más vendidos.
- Stock (niveles bajos de inventario).
- Valor de inventario.

Contabilidad (solo gerentes):
- Libro diario, balance de comprobación, cierres de período, estado de \
resultados, IVA trimestral.

Caja:
- Abrir caja al iniciar el turno (con un monto de apertura).
- Cerrar caja al finalizar, con el conteo de efectivo.

Roles del sistema:
- Cajero: puede vender, abrir/cerrar caja, generar etiquetas.
- Gerente: además puede recibir mercadería, ver reportes, hacer ajustes de \
inventario, anular ventas/compras, y entrar al panel de administración.

DATOS REALES: Además de explicar cómo se usa el sistema, tenés herramientas \
para consultar los números REALES del negocio (ventas de hoy, margen del \
mes, productos más vendidos, stock bajo, productos con menor margen, valor \
de inventario). Usalas cuando la pregunta sea sobre datos concretos del \
negocio, no solo sobre cómo navegar el sistema. Nunca inventes una cifra —
si la herramienta no cubre lo que preguntan, decilo.

ESTILO DE RESPUESTA:
- Español, tono cercano y directo.
- Pasos numerados cuando expliques cómo hacer algo, usando los nombres reales \
de botones y secciones de arriba.
- Si la pregunta es sobre algo que no está en este mapa (por ejemplo, una \
función que no existe en el sistema), decilo con honestidad en vez de \
inventar una respuesta.
- Respuestas cortas y prácticas, sin relleno."""


def _historial_valido(bruto):
    """Sanitiza el historial que manda el frontend: solo user/assistant con
    texto, tope de turnos para no dejar crecer el costo sin límite."""
    if not isinstance(bruto, list):
        return []
    limpio = []
    for turno in bruto[-20:]:  # últimos 10 intercambios (20 mensajes)
        if not isinstance(turno, dict):
            continue
        rol = turno.get("role")
        contenido = turno.get("content")
        if rol in ("user", "assistant") and isinstance(contenido, str) and contenido.strip():
            limpio.append({"role": rol, "content": contenido[:4000]})
    return limpio


@staff_member_required
@require_http_methods(["POST"])
def chat_claude(request):
    """API endpoint para el chat de ayuda con Claude.
    Recibe: {"message": "tu pregunta", "history": [{"role":"user"/"assistant","content":"..."}]}
    Retorna: {"response": "respuesta de claude"}

    Tiene memoria (recibe el historial y lo manda de vuelta a Claude), límite
    diario de preguntas por usuario, herramientas de datos reales, y deja
    registro de cada pregunta/respuesta en ChatMensaje.
    """
    hoy_count = ChatMensaje.objects.filter(
        usuario=request.user, creado_en__date=datetime.now().date()
    ).count()
    if hoy_count >= CHAT_LIMITE_DIARIO:
        return JsonResponse(
            {"error": f"Llegaste al límite de {CHAT_LIMITE_DIARIO} preguntas por hoy. Probá de nuevo mañana."},
            status=429,
        )

    try:
        datos = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    mensaje = (datos.get("message") or "").strip()
    if not mensaje:
        return JsonResponse({"error": "Mensaje vacío"}, status=400)
    mensaje = mensaje[:4000]

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JsonResponse(
            {"error": "Claude no está configurado. Contactá al administrador."},
            status=500,
        )

    historial = _historial_valido(datos.get("history"))
    mensajes = historial + [{"role": "user", "content": mensaje}]

    tokens_entrada = 0
    tokens_salida = 0
    texto_final = ""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        for _ in range(CHAT_MAX_RONDAS_HERRAMIENTAS):
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=SYSTEM_PROMPT_CHAT,
                # Solo las herramientas que este usuario puede usar: a un
                # cajero no se le ofrecen las que exponen costos y márgenes.
                tools=herramientas_para(request.user),
                messages=mensajes,
            )
            tokens_entrada += response.usage.input_tokens
            tokens_salida += response.usage.output_tokens

            if response.stop_reason != "tool_use":
                texto_final = "".join(
                    b.text for b in response.content if getattr(b, "type", None) == "text"
                )
                break

            # El modelo pidió usar una o más herramientas: ejecutarlas y
            # devolverle el resultado para que arme la respuesta final.
            mensajes.append({"role": "assistant", "content": response.content})
            resultados = []
            for bloque in response.content:
                if getattr(bloque, "type", None) != "tool_use":
                    continue
                salida = ejecutar_herramienta(
                    bloque.name, bloque.input or {}, usuario=request.user
                )
                resultados.append({
                    "type": "tool_result",
                    "tool_use_id": bloque.id,
                    "content": json.dumps(salida, ensure_ascii=False),
                })
            mensajes.append({"role": "user", "content": resultados})
        else:
            texto_final = "No pude terminar de procesar tu pregunta (demasiados pasos). Probá reformularla más simple."

        ChatMensaje.objects.create(
            usuario=request.user, pregunta=mensaje, respuesta=texto_final,
            tokens_entrada=tokens_entrada, tokens_salida=tokens_salida,
        )
        return JsonResponse({"response": texto_final})

    except anthropic.APIError as e:
        ChatMensaje.objects.create(usuario=request.user, pregunta=mensaje, error=str(e))
        return JsonResponse({"error": f"Error de Claude: {e}"}, status=500)
    except Exception as e:
        ChatMensaje.objects.create(usuario=request.user, pregunta=mensaje, error=str(e))
        return JsonResponse({"error": f"Error: {e}"}, status=500)
