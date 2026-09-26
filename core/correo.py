"""Envío de correo por HTTPS a un servicio transaccional (26/09/2026, TIQ-06).

POR QUÉ
-------
El ERP corre en DigitalOcean y manda los recibos por SMTP a Office 365. Los
proveedores de nube suelen bloquear el correo saliente por SMTP para frenar
el spam, y no se pudo confirmar que ese camino funcione desde el servidor.
Un servicio transaccional recibe el correo por HTTPS —el mismo puerto que
cualquier página web—, que ningún proveedor de nube bloquea.

Se eligió Resend por tener la API más simple (un POST con JSON). Los precios
y el plan gratuito vigentes hay que confirmarlos en su sitio antes de abrir
la cuenta. Cambiar de proveedor es reemplazar este archivo: el resto del ERP
sigue usando `EmailMessage` de Django como siempre.

CÓMO SE ACTIVA
--------------
Con la variable `RESEND_API_KEY` en el servidor (y `DEFAULT_FROM_EMAIL` con
una dirección de un dominio verificado en Resend, p. ej.
`AllPetcr <recibos@allpetcr.com>`). Sin la variable, todo sigue como antes.
"""
import base64
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

URL_RESEND = "https://api.resend.com/emails"


class ResendBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        enviados = 0
        for mensaje in email_messages:
            try:
                self._enviar(mensaje)
                enviados += 1
            except OSError:
                if not self.fail_silently:
                    raise
                logger.exception("No se pudo enviar el correo «%s»", mensaje.subject)
        return enviados

    def _enviar(self, mensaje):
        cuerpo = {
            "from": mensaje.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(mensaje.to),
            "subject": mensaje.subject,
        }
        if mensaje.cc:
            cuerpo["cc"] = list(mensaje.cc)
        if mensaje.bcc:
            cuerpo["bcc"] = list(mensaje.bcc)
        if getattr(mensaje, "content_subtype", "plain") == "html":
            cuerpo["html"] = mensaje.body
        else:
            cuerpo["text"] = mensaje.body
        for alternativa, tipo in getattr(mensaje, "alternatives", []) or []:
            if tipo == "text/html":
                cuerpo["html"] = alternativa
        adjuntos = []
        for adjunto in mensaje.attachments:
            nombre, contenido, _tipo = adjunto
            if isinstance(contenido, str):
                contenido = contenido.encode("utf-8")
            adjuntos.append({"filename": nombre, "content": base64.b64encode(contenido).decode("ascii")})
        if adjuntos:
            cuerpo["attachments"] = adjuntos

        peticion = urllib.request.Request(
            URL_RESEND,
            data=json.dumps(cuerpo).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=getattr(settings, "EMAIL_TIMEOUT", 20)) as r:
                r.read()
        except urllib.error.HTTPError as e:
            # El detalle del proveedor (dominio sin verificar, clave vencida)
            # es lo único que explica un rechazo: se conserva en el error.
            detalle = e.read().decode("utf-8", errors="replace")[:300]
            raise OSError(f"El servicio de correo rechazó el envío ({e.code}): {detalle}") from e
