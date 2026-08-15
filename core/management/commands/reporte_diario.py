"""Reporte diario automático a ambos socios (FRA-004, auditoría 2026-08-15).

Es un control DETECTIVO, no preventivo: no bloquea nada, solo hace que una
anomalía (fraude o simple error) no dependa de que alguien entre a revisar
por su cuenta. Resume ventas, regalías/descuentos que necesitaron
autorización de gerente, arqueo de caja, y ediciones/borrados de AuditLog
sobre documentos financieros.

Pensado para correr una vez al día vía el Programador de tareas de Windows
(mismo mecanismo que reconciliar, ver PRODUCCION.txt) — no requiere Celery
ni ningún servicio nuevo.

Uso:
    python manage.py reporte_diario
    python manage.py reporte_diario --fecha 2026-08-14
    python manage.py reporte_diario --destinatarios a@x.com,b@x.com
"""
import smtplib
from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.utils import timezone


class Command(BaseCommand):
    help = "Manda por correo el resumen del día a los destinatarios configurados (FRA-004)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha", type=str, default=None,
            help="Día a resumir, AAAA-MM-DD. Por defecto: ayer.",
        )
        parser.add_argument(
            "--destinatarios", type=str, default=None,
            help="Correos separados por coma. Por defecto: REPORTE_DIARIO_DESTINATARIOS del entorno.",
        )

    def handle(self, *args, **opciones):
        from core.models import Empresa
        from core.reportes import resumen_diario

        if opciones["fecha"]:
            try:
                fecha = datetime.strptime(opciones["fecha"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--fecha debe tener el formato AAAA-MM-DD.")
        else:
            fecha = timezone.localdate() - timedelta(days=1)

        if opciones["destinatarios"]:
            destinatarios = [d.strip() for d in opciones["destinatarios"].split(",") if d.strip()]
        else:
            destinatarios = list(settings.REPORTE_DIARIO_DESTINATARIOS)

        if not destinatarios:
            # No es un error: un día sin la variable configurada no debe
            # tumbar la tarea programada, solo avisar por qué no mandó nada.
            self.stdout.write(self.style.WARNING(
                "No hay destinatarios configurados (REPORTE_DIARIO_DESTINATARIOS "
                "vacío y sin --destinatarios). No se mandó ningún correo."
            ))
            return

        hubo_error = False
        for empresa in Empresa.objects.all():
            resumen = resumen_diario(empresa, fecha)
            html = render_to_string("core/reporte_diario_email.html", resumen)
            asunto = f"Resumen {fecha:%d/%m/%Y} — {empresa.nombre}"
            correo = EmailMessage(subject=asunto, body=html, to=destinatarios)
            correo.content_subtype = "html"
            try:
                correo.send(fail_silently=False)
            except (smtplib.SMTPException, OSError):
                # No revienta el proceso completo (si hay varias empresas,
                # que el fallo de una no impida el resumen de las demás),
                # pero el código de salida distinto de cero deja que el
                # Programador de tareas marque la corrida como fallida.
                self.stderr.write(self.style.ERROR(
                    f"No se pudo enviar el resumen de {empresa.nombre} a {', '.join(destinatarios)}."
                ))
                hubo_error = True
                continue
            self.stdout.write(self.style.SUCCESS(
                f"Resumen de {empresa.nombre} ({fecha:%d/%m/%Y}) enviado a {', '.join(destinatarios)}."
            ))

        if hubo_error:
            raise CommandError("Al menos un envío falló. Revisá el log para el detalle.")
