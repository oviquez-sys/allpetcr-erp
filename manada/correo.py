"""Correo de bienvenida a la manada, con el código del cupón.

Para quien se registra con su correo (sin Google), este correo ES la
verificación: el código no se muestra en la página, solo llega acá. Así nadie
puede sacar cupones con correos inventados o ajenos.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def url_sitio() -> str:
    return getattr(settings, "SITIO_WEB_URL", "https://www.allpetcr.com").rstrip("/")


def enviar_bienvenida(resultado) -> bool:
    """Devuelve True si el correo salió. Un fallo NO revierte el registro: el
    cliente ya quedó en la base y el cupón existe; lo peor que pasa es que lo
    pida en caja por su correo y el cajero lo encuentra en el admin."""
    cliente, cupon, perfil = resultado.cliente, resultado.cupon, resultado.perfil
    if cupon is None and not perfil.token_mascotas:
        return False
    contexto = {
        "nombre": cliente.nombre.split(" ")[0] if cliente.nombre else "",
        "cupon": cupon if cupon is not None and cupon.estado == "DISPONIBLE" else None,
        "url_mascotas": (f"{url_sitio()}/manada/mascota?t={perfil.token_mascotas}"
                         if perfil.token_mascotas else ""),
        "url_sitio": url_sitio(),
    }
    asunto = ("Tu código de la manada AllPetcr.com" if contexto["cupon"]
              else "Bienvenido a la manada AllPetcr.com")
    mensaje = EmailMultiAlternatives(
        subject=asunto,
        body=render_to_string("manada/correo_bienvenida.txt", contexto),
        to=[cliente.email],
    )
    mensaje.attach_alternative(render_to_string("manada/correo_bienvenida.html", contexto), "text/html")
    try:
        mensaje.send()
        return True
    except OSError:
        logger.exception("No se pudo enviar la bienvenida de la manada a %s", cliente.email)
        return False
