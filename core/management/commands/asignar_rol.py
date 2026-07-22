"""Asigna un rol a un usuario (o crea el usuario de cajero rápido).

Ejemplos:
    python manage.py asignar_rol maria Cajero --crear --password "ClaveFuerte#2026"
    python manage.py asignar_rol juan Gerente
    python manage.py asignar_rol ALLPETCR Gerente --dueno

Roles válidos: Gerente, Cajero, Contador.

Seguridad (mínimo privilegio):
- Solo el DUEÑO (con --dueno) es superusuario de Django: control total, sin
  límites. Reservalo para tu propia cuenta.
- Un Gerente normal es 'staff' con permisos CONCRETOS (gestionar productos,
  clientes y proveedores desde el panel), pero NO puede borrar la base, tocar
  otros usuarios ni cambiar configuración del sistema.
- Cajero y Contador entran al sistema pero no llegan al panel de administración.
"""
from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand, CommandError

from core.roles import GERENTE, ROLES

# Lo que un Gerente (no dueño) puede administrar desde /admin/: alta y edición,
# nunca borrado. (app_label, modelo) -> acciones.
PERMISOS_GERENTE = {
    ("catalogo", "producto"): ["add", "change", "view"],
    ("catalogo", "categoria"): ["add", "change", "view"],
    ("catalogo", "cambioprecio"): ["view"],
    ("ventas", "cliente"): ["add", "change", "view"],
    ("compras", "proveedor"): ["add", "change", "view"],
}


def _sincronizar_permisos_gerente(grupo):
    """Deja el grupo Gerente exactamente con los permisos de la lista de arriba."""
    perms = []
    for (app_label, modelo), acciones in PERMISOS_GERENTE.items():
        for accion in acciones:
            p = Permission.objects.filter(
                content_type__app_label=app_label,
                content_type__model=modelo,
                codename=f"{accion}_{modelo}",
            ).first()
            if p:
                perms.append(p)
    grupo.permissions.set(perms)


class Command(BaseCommand):
    help = "Asigna un rol (Gerente/Cajero/Contador) a un usuario"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("rol", choices=ROLES)
        parser.add_argument("--crear", action="store_true", help="Crea el usuario si no existe")
        parser.add_argument("--password", default=None, help="Contraseña al crear el usuario")
        parser.add_argument("--dueno", action="store_true",
                            help="Marca al usuario como superusuario (acceso total). Solo para el dueño.")

    def handle(self, *args, **opts):
        username = opts["username"]
        rol = opts["rol"]
        es_dueno = opts["dueno"]

        try:
            usuario = User.objects.get(username=username)
        except User.DoesNotExist:
            if not opts["crear"]:
                raise CommandError(
                    f"El usuario '{username}' no existe. Agregá --crear para crearlo."
                )
            if not opts["password"]:
                raise CommandError(
                    "Al crear un usuario hay que indicar una contraseña fuerte con "
                    "--password \"...\" (mínimo 8 caracteres, que no sea obvia)."
                )
            usuario = User.objects.create_user(username=username, password=opts["password"])
            self.stdout.write(self.style.SUCCESS(f"Usuario '{username}' creado."))

        # Todo el que usa el sistema debe ser staff (para poder iniciar sesión).
        usuario.is_staff = True
        # Superusuario SOLO para el dueño. Un gerente normal ya NO es superusuario;
        # pero si el usuario ya era superusuario (p. ej. el dueño histórico), no se
        # le degrada por error.
        if rol == GERENTE and (es_dueno or usuario.is_superuser):
            usuario.is_superuser = True
        else:
            usuario.is_superuser = False
        usuario.save(update_fields=["is_staff", "is_superuser"])

        grupo, _ = Group.objects.get_or_create(name=rol)
        if rol == GERENTE:
            _sincronizar_permisos_gerente(grupo)
        # Un usuario tiene un solo rol a la vez: se limpian los otros.
        usuario.groups.remove(*usuario.groups.filter(name__in=ROLES))
        usuario.groups.add(grupo)

        nivel = "superusuario (dueño)" if usuario.is_superuser else rol
        self.stdout.write(self.style.SUCCESS(f"Listo: '{username}' ahora es {nivel}."))
