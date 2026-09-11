"""Las dos puertas por las que entra el agente de impresión de la tienda.

Son las ÚNICAS vistas del ERP que no las usa una persona con sesión abierta,
sino un programa. Por eso:

  - No piden sesión ni rol: el agente no es un usuario, es la computadora del
    mostrador. Se identifica con una llave compartida (IMPRESION_AGENTE_TOKEN).
  - No pasan por CSRF: esa protección existe para que otro sitio no le haga
    hacer cosas al navegador de un usuario logueado. Acá no hay navegador ni
    sesión que robar; lo que protege es la llave.
  - La llave se compara con `compare_digest` y no con `==`. La diferencia se
    mide en microsegundos, pero es la diferencia entre una llave que se puede
    adivinar letra por letra midiendo tiempos y una que no.

Si la llave no está configurada, las puertas quedan CERRADAS en vez de
abiertas: un despliegue al que se le olvidó la variable no debe quedar con la
cola de impresión expuesta a internet.
"""
from __future__ import annotations

import base64
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import cola

logger = logging.getLogger(__name__)


def _autorizado(request) -> bool:
    esperado = getattr(settings, "IMPRESION_AGENTE_TOKEN", "") or ""
    if not esperado:
        logger.warning(
            "Un agente intentó conectarse pero IMPRESION_AGENTE_TOKEN no está "
            "configurada en el servidor."
        )
        return False
    recibido = request.headers.get("X-Agente-Token", "")
    return hmac.compare_digest(recibido, esperado)


def _no_autorizado():
    return JsonResponse({"ok": False, "error": "Llave inválida."}, status=401)


@csrf_exempt
@require_GET
def pendientes(request):
    """Le entrega al agente los trabajos que le tocan y los marca tomados.

    El contenido va en base64 porque JSON no sabe llevar bytes crudos, y el
    tiquete ESC/POS son bytes crudos de punta a punta."""
    if not _autorizado(request):
        return _no_autorizado()
    try:
        cuantos = max(1, min(20, int(request.GET.get("cuantos", "5"))))
    except (TypeError, ValueError):
        cuantos = 5

    trabajos = cola.tomar_pendientes(cuantos)
    return JsonResponse({
        "ok": True,
        "trabajos": [
            {
                "id": t.pk,
                "tipo": t.tipo,
                "formato": t.formato,
                "impresora": t.impresora,
                "titulo": t.titulo,
                "ancho_mm": t.ancho_mm,
                "alto_mm": t.alto_mm,
                "contenido_b64": base64.b64encode(bytes(t.contenido)).decode("ascii"),
            }
            for t in trabajos
        ],
    })


@csrf_exempt
@require_POST
def resultado(request):
    """El agente dice si el trabajo salió o no."""
    if not _autorizado(request):
        return _no_autorizado()
    try:
        datos = json.loads(request.body or b"{}")
        trabajo_id = int(datos["id"])
        ok = bool(datos.get("ok"))
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "Datos inválidos."}, status=400)

    encontrado = cola.reportar(trabajo_id, ok, str(datos.get("detalle", "")))
    if not encontrado:
        return JsonResponse({"ok": False, "error": "Ese trabajo no existe."}, status=404)
    return JsonResponse({"ok": True})
