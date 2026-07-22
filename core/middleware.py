"""Middleware que expone el usuario y la IP de la petición actual a las
señales de auditoría, sin acoplar los modelos al request."""
import threading

from django.shortcuts import redirect

_local = threading.local()


def get_current_user():
    return getattr(_local, "user", None)


def get_current_ip():
    return getattr(_local, "ip", None)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        _local.user = user if (user is not None and user.is_authenticated) else None
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        _local.ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
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
