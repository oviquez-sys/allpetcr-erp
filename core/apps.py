from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Núcleo (empresa y auditoría)"

    def ready(self):
        # Los receptores se conectan modelo por modelo (auditoría 2026-07-28,
        # BE-01): antes se registraban globalmente y se ejecutaban en cada
        # save() del proyecto. Ver core/signals.py.
        from . import signals

        signals.conectar()
