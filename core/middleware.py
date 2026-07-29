"""Middleware que expone el usuario y la IP de la petición actual a las
señales de auditoría, sin acoplar los modelos al request."""
import threading

from django.conf import settings
from django.shortcuts import redirect

_local = threading.local()


def get_current_user():
    return getattr(_local, "user", None)


def get_current_ip():
    return getattr(_local, "ip", None)


def ip_de_la_peticion(request):
    """IP de origen CONFIABLE para la bitácora de auditoría.

    Por qué no basta leer X-Forwarded-For (auditoría 2026-07-28, SEG-05)
    -------------------------------------------------------------------
    Esa cabecera la escribe el cliente. Antes tomábamos su primer valor sin
    verificar nada, así que cualquiera podía mandar `X-Forwarded-For: 8.8.8.8`
    y esa IP falsa quedaba grabada en el AuditLog. El usuario sí quedaba bien
    identificado (viene de la sesión firmada, no es manipulable así), pero la
    evidencia de origen quedaba contaminada — justo lo que se necesita limpio
    cuando hay que investigar una anulación sospechosa.

    Regla que aplicamos
    -------------------
    1. Si la conexión NO viene de un proxy conocido, se ignora la cabecera y
       se usa REMOTE_ADDR, que la fija el servidor y el cliente no controla.
    2. Si viene de un proxy conocido, se toma la ÚLTIMA entrada de la lista,
       no la primera: las anteriores pudo escribirlas el cliente; la última la
       anexó nuestro propio proxy.

    `DJANGO_PROXIES_CONFIABLES` lista las IP de los proxies inversos (nginx).
    Vacía por defecto: sin proxy declarado no se confía en nadie, que es el
    valor seguro. En el VPS se define con la IP del nginx que termina el TLS.
    """
    remote = request.META.get("REMOTE_ADDR")
    confiables = getattr(settings, "PROXIES_CONFIABLES", ())
    if not confiables or remote not in confiables:
        return remote
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if not xff:
        return remote
    return xff.split(",")[-1].strip() or remote


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        _local.user = user if (user is not None and user.is_authenticated) else None
        _local.ip = ip_de_la_peticion(request)
        try:
            return self.get_response(request)
        finally:
            _local.user = None
            _local.ip = None


class AdminSoloGerente:
    """Cierra el panel de administración a quien no sea gerente. Un cajero
    necesita ser 'staff' para entrar al sistema, y eso, por defecto, le deja
    alcanzable /admin/ (aunque vería poco). Este guard lo redirige al inicio.
    Deja libres el login y el logout, que todos necesitan."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ruta = request.path
        if ruta.startswith("/admin/") and not ruta.startswith(("/admin/login", "/admin/logout")):
            from .roles import es_gerente
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated and not es_gerente(user):
                return redirect("core:dashboard")
        return self.get_response(request)
