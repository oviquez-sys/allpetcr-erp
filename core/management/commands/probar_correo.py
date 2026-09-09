"""Prueba de verdad si el ERP puede mandar correos, y dice por qué no.

Uso:
    python manage.py probar_correo                       # se lo manda al remitente
    python manage.py probar_correo --a oscar@ejemplo.com

Por qué existe (02/09/2026)
---------------------------
El síntoma era "la factura dice que se envió y no llega". La causa: sin
`EMAIL_HOST_PASSWORD` configurada, Django usa el backend de CONSOLA. El correo
se imprime en la terminal del servidor, la pantalla dice "Factura enviada", y
nunca sale a Internet. Todo funciona; nada llega.

Ese es exactamente el peor tipo de falla: la que no falla. Este comando la
vuelve visible en diez segundos, y traduce los errores de SMTP —que vienen en
inglés y llenos de códigos— a algo que se pueda accionar.

NUNCA imprime la contraseña. Solo dice si está puesta o no.
"""
import smtplib

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Manda un correo de prueba y explica en castellano qué pasó."

    def _quien_firma(self):
        """Muestra quien emitio el certificado que llega de verdad.

        Se conecta sin verificar —solo para MIRAR el certificado, no se manda
        nada por esa conexion— y dice de quien es. Es la forma de pasar de
        "algo se mete en el medio" a "es tal programa", sin adivinar.
        """
        import ssl

        from django.conf import settings as cfg

        w = self.stdout.write
        try:
            srv = smtplib.SMTP(cfg.EMAIL_HOST, cfg.EMAIL_PORT, timeout=15)
            srv.ehlo()
            srv.starttls(context=ssl._create_unverified_context())
            der = srv.sock.getpeercert(binary_form=True)
            srv.quit()
        except Exception as e:  # noqa: BLE001 - es un diagnostico, no puede tumbar el comando
            w(f"\n  (No se pudo mirar el certificado: {e})")
            return

        try:
            from cryptography import x509

            cert = x509.load_der_x509_certificate(der)
            w("\n  El certificado que esta llegando lo emitio:")
            w(f"    {cert.issuer.rfc4514_string()}")
            w(f"  Y dice ser para: {cert.subject.rfc4514_string()}")
            w("\n  Si ahi NO dice Microsoft ni DigiCert, ese es el programa que se")
            w("  esta metiendo en el medio.")
        except ImportError:
            pem = ssl.DER_cert_to_PEM_cert(der)
            w("\n  Certificado recibido (pegaselo a Claude y te dice de quien es):")
            w(pem)

    def add_arguments(self, parser):
        parser.add_argument("--a", default=None,
                            help="A quién mandarlo. Por defecto, al mismo remitente.")
        parser.add_argument("--adjunto", type=int, default=0, metavar="KB",
                            help="Adjunta un archivo de prueba de este tamaño en KB. "
                                 "Sirve para reproducir el envío de una factura: el PDF "
                                 "es lo que hacía fallar por tiempo cuando el envío "
                                 "simple funcionaba.")

    def handle(self, *args, **op):
        w = self.stdout.write
        backend = getattr(settings, "EMAIL_BACKEND", "")
        usuario = getattr(settings, "EMAIL_HOST_USER", "")
        clave_puesta = bool(getattr(settings, "EMAIL_HOST_PASSWORD", ""))

        w(self.style.SUCCESS("\nConfiguracion de correo del ERP"))
        w(f"  Backend .............. {backend}")
        w(f"  Servidor ............. {getattr(settings, 'EMAIL_HOST', '(ninguno)')}")
        w(f"  Puerto ............... {getattr(settings, 'EMAIL_PORT', '(ninguno)')}")
        w(f"  TLS .................. {getattr(settings, 'EMAIL_USE_TLS', False)}")
        w(f"  Usuario .............. {usuario or '(vacio)'}")
        w(f"  Contrasena ........... {'PUESTA' if clave_puesta else 'NO ESTA'}")
        w(f"  Remite como .......... {getattr(settings, 'DEFAULT_FROM_EMAIL', '(ninguno)')}")

        if "console" in backend:
            w(self.style.ERROR(
                "\n  ESTE ES EL PROBLEMA.\n"
                "  El ERP esta en modo consola: los correos se imprimen en la ventana\n"
                "  del servidor y NO salen a Internet. Por eso la pantalla dice\n"
                "  'enviada' y el cliente nunca recibe nada.\n\n"
                "  Se arregla definiendo EMAIL_HOST_USER y EMAIL_HOST_PASSWORD como\n"
                "  variables de entorno de Windows (setx) y reiniciando el ERP.\n"
            ))
            return

        destino = op["a"] or usuario
        if not destino:
            w(self.style.ERROR("\n  No hay a quien mandarle la prueba. Usa --a tu-correo@ejemplo.com\n"))
            return

        w(f"\n  Mandando una prueba a {destino}...")
        mensaje = EmailMessage(
            subject="Prueba de correo del ERP AllPetCR",
            body=(
                "Si estas leyendo esto, el ERP ya puede enviar los recibos a los clientes.\n\n"
                "Enviado automaticamente por el comando probar_correo."
            ),
            to=[destino],
        )
        kb = op["adjunto"]
        if kb:
            # Datos incompresibles a proposito: un PDF real tampoco se comprime,
            # y lo que se quiere medir es el tiempo de subir ese tamano de verdad.
            import os as _os
            mensaje.attach("prueba.pdf", _os.urandom(kb * 1024), "application/pdf")
            w(f"  Con un adjunto de {kb} KB, como una factura.")
        try:
            enviados = mensaje.send(fail_silently=False)
        except smtplib.SMTPAuthenticationError as e:
            w(self.style.ERROR("\n  EL SERVIDOR RECHAZO EL USUARIO O LA CONTRASENA."))
            w("  Las dos causas casi siempre son estas:")
            w("   1. Se puso la contrasena normal de la cuenta. Office 365 exige una")
            w("      'contrasena de aplicacion' aparte, que se genera en la cuenta.")
            w("   2. La cuenta tiene SMTP AUTH desactivado. Microsoft lo apaga por")
            w("      defecto en las cuentas nuevas y hay que habilitarlo en el panel")
            w("      de administracion de Microsoft 365, mailbox por mailbox.")
            w(f"\n  Respuesta cruda del servidor: {e}\n")
            return
        except smtplib.SMTPException as e:
            texto = str(e)
            if "timed out" in texto.lower() or "unexpectedly closed" in texto.lower():
                w(self.style.ERROR("\n  SE ACABO EL TIEMPO DE ESPERA."))
                w(f"  El limite actual es de {getattr(settings, 'EMAIL_TIMEOUT', '?')} segundos.")
                w("  Si el envio SIN adjunto funciona y con adjunto no, es el antivirus")
                w("  escaneando el archivo: tiene que descifrar, revisar y volver a")
                w("  cifrar el PDF, y eso toma segundos de mas.")
                w("\n  Que hacer:")
                w("   1. Reinicia el ERP: el limite subio a 60 s y hay que recargarlo.")
                w("   2. Si sigue, subilo mas:  setx EMAIL_TIMEOUT \"120\"")
                w("   3. Si con 120 tampoco, excluí smtp.office365.com de la")
                w("      inspeccion SSL del antivirus.")
                w(f"\n  Error crudo: {texto}\n")
            else:
                w(self.style.ERROR(f"\n  FALLO EL SERVIDOR DE CORREO: {texto}"))
                w("  Revisa el servidor y el puerto. Para Office 365 son")
                w("  smtp.office365.com y 587 con TLS.\n")
            return
        except OSError as e:
            texto = str(e)
            if "CERTIFICATE_VERIFY_FAILED" in texto:
                w(self.style.ERROR("\n  ALGO SE METE EN EL MEDIO DE LA CONEXION CIFRADA."))
                w("  El servidor de Microsoft respondio, o sea que internet y el puerto")
                w("  estan bien. Lo que fallo es el certificado: el que llego NO es el de")
                w("  Microsoft. Casi siempre es el antivirus, que inspecciona el trafico")
                w("  cifrado poniendose en el medio con su propio certificado.")
                w("  Windows confia en ese certificado (por eso el navegador anda), pero")
                w("  Python trae su propia lista y no lo conoce.")
                w(f"\n  Error crudo: {texto}")
                self._quien_firma()
                w("\n  Como se arregla, en orden de preferencia:")
                w("   1. Instalar `truststore` para que Python valide contra el almacen")
                w("      de Windows. Es lo que hace INSTALAR_ARREGLO_CORREO.bat.")
                w("   2. Excluir smtp.office365.com de la inspeccion SSL del antivirus.")
                w("  Lo que NO se hace: apagar la verificacion del certificado. Eso")
                w("  dejaria las facturas legibles para cualquiera en el camino.\n")
            else:
                w(self.style.ERROR(f"\n  NO SE PUDO CONECTAR: {e}"))
                w("  Puede ser el internet, un firewall, o el antivirus bloqueando el")
                w("  puerto 587.\n")
            return

        if enviados:
            w(self.style.SUCCESS(
                f"\n  ENVIADO. Revisa la bandeja de {destino} (y la carpeta de correo\n"
                "  no deseado la primera vez). Si llego, los recibos ya funcionan.\n"
            ))
        else:
            w(self.style.WARNING(
                "\n  El servidor acepto la conexion pero no envio nada. Raro:\n"
                "  volve a correrlo y, si se repite, mostrale esta salida a Claude.\n"
            ))
