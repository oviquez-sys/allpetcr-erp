"""Roles y permisos del sistema.

Se apoya en los Grupos de Django (auth.Group): cada usuario pertenece a uno
o varios grupos, y aquí se traduce eso a "roles" con nombre claro. El
superusuario (el dueño, ALLPETCR) siempre tiene nivel de gerente.

Roles:
- Gerente: control total (vender, anular, devolver, compras, contabilidad,
  ajustes, administración). Es quien autoriza las operaciones sensibles.
- Cajero: vende en el POS y maneja su caja. NO puede anular ni devolver
  ventas, ni recibir mercadería, ni ver la contabilidad. Este límite es la
  defensa anti-fraude: el hueco típico de robo (anular una venta y quedarse
  el efectivo) le queda cerrado.
- Contador: ve reportes y contabilidad; no vende ni mueve inventario.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect

GERENTE = "Gerente"
CAJERO = "Cajero"
CONTADOR = "Contador"
ROLES = [GERENTE, CAJERO, CONTADOR]


def es_gerente(usuario) -> bool:
    return usuario.is_superuser or usuario.groups.filter(name=GERENTE).exists()


def es_contador(usuario) -> bool:
    return usuario.groups.filter(name=CONTADOR).exists()


def es_cajero(usuario) -> bool:
    return usuario.groups.filter(name=CAJERO).exists()


def en_roles(usuario, *roles) -> bool:
    """True si el usuario es superusuario o pertenece a alguno de los roles."""
    if usuario.is_superuser:
        return True
    return usuario.groups.filter(name__in=roles).exists()


def rol_de(usuario) -> str:
    if usuario.is_superuser or es_gerente(usuario):
        return GERENTE
    if es_cajero(usuario):
        return CAJERO
    if es_contador(usuario):
        return CONTADOR
    return "Sin rol"


def rol_requerido(*roles):
    """Protege una vista: exige estar logueado (staff) y pertenecer a uno de
    los roles. Si no, redirige al inicio con un mensaje amable en vez de un
    error técnico feo."""
    def decorador(view):
        @wraps(view)
        @staff_member_required
        def envuelta(request, *args, **kwargs):
            if en_roles(request.user, *roles):
                return view(request, *args, **kwargs)
            messages.error(
                request,
                "No tenés permiso para esta acción. Pedile a un gerente que la haga "
                "o que te habilite el permiso.",
            )
            return redirect("core:dashboard")
        return envuelta
    return decorador
