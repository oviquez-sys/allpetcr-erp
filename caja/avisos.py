"""Aviso por correo cuando un cierre de caja no calza (02/11/2026, pedido de
Oscar: "si no calza, enviar un aviso de la diferencia, en qué medio y de
cuánto").

A quién: `CIERRE_AVISO_DESTINATARIOS`; si no está, los mismos del resumen
diario (`REPORTE_DIARIO_DESTINATARIOS`, los dos socios: es el mismo control
contra errores y fraude, FRA-004); si tampoco, los dueños (superusuarios)
que tengan correo. Así el aviso llega aunque nadie haya configurado nada.

Nunca tumba el cierre: si el correo no sale, la caja queda cerrada igual y
el motivo queda escrito en `SesionCaja.aviso_diferencia`, que se ve en el
admin y en el tiquete de cierre.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import SesionCaja
from .resumen import resumen_cierre, texto_diferencia

logger = logging.getLogger(__name__)


def destinatarios() -> list[str]:
    for nombre in ("CIERRE_AVISO_DESTINATARIOS", "REPORTE_DIARIO_DESTINATARIOS"):
        lista = [d for d in (getattr(settings, nombre, None) or []) if d]
        if lista:
            return lista
    return list(get_user_model().objects.filter(is_superuser=True, is_active=True)
                .exclude(email="").values_list("email", flat=True))


def asunto(datos) -> str:
    s = datos["sesion"]
    partes = [f"{d.get_medio_display()}: {texto_diferencia(d.diferencia).lower()}" for d in datos["diferencias"]]
    return f"Cierre de caja #{s.pk} no calzó — " + "; ".join(partes)


def avisar_diferencia(sesion_id: int) -> str:
    """Manda el aviso de un cierre con diferencias. Devuelve lo que quedó
    anotado en la sesión (para pruebas y para el mensaje en pantalla)."""
    sesion = (SesionCaja.objects.select_related("usuario", "cerrada_por", "sucursal__empresa")
              .get(pk=sesion_id))
    datos = resumen_cierre(sesion)
    if not datos["diferencias"]:
        return ""
    para = destinatarios()
    if not para:
        nota = "No se avisó: no hay a quién (falta CIERRE_AVISO_DESTINATARIOS)."
    else:
        datos["admin_url"] = getattr(settings, "ERP_URL", "").rstrip("/") + f"/admin/caja/sesioncaja/{sesion.pk}/change/"
        texto = render_to_string("caja/aviso_diferencia.txt", datos)
        html = render_to_string("caja/aviso_diferencia.html", datos)
        correo = EmailMultiAlternatives(subject=asunto(datos), body=texto, to=para)
        correo.attach_alternative(html, "text/html")
        try:
            correo.send(fail_silently=False)
            nota = "Aviso enviado a " + ", ".join(para)
        except Exception as e:  # noqa: BLE001 — cualquier falla del correo se anota, el cierre no se cae
            logger.exception("No salió el aviso de diferencia del cierre #%s", sesion.pk)
            nota = f"No salió el aviso a {', '.join(para)}: {e}"
    SesionCaja.objects.filter(pk=sesion.pk).update(aviso_diferencia=nota[:300])
    return nota
