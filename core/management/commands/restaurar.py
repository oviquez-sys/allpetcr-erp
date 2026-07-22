"""Restaurar el sistema desde un respaldo (Sprint G).

Devuelve la base de datos y las fotos al estado guardado en un respaldo. Es una
operación delicada, así que el comando:

  1. Exige que el servidor esté APAGADO (SQLite no se puede reemplazar en uso).
  2. Antes de tocar nada, guarda una copia del estado ACTUAL (por si el respaldo
     elegido no era el que querías: siempre hay marcha atrás).
  3. Pide confirmación explícita con --confirmar; sin eso, solo muestra qué haría.

Uso:
    python manage.py restaurar                 # lista los respaldos disponibles
    python manage.py restaurar --archivo respaldo_allpetcr_20260721_200000.zip
    python manage.py restaurar --archivo ...zip --confirmar
"""
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .respaldar import PREFIJO, carpeta_respaldos


class Command(BaseCommand):
    help = "Restaura la base de datos y las fotos desde un respaldo (con copia de seguridad previa)."

    def add_arguments(self, parser):
        parser.add_argument("--archivo", type=str, default=None,
                            help="Nombre (o ruta) del zip de respaldo a restaurar.")
        parser.add_argument("--destino", type=str, default=None,
                            help="Carpeta de respaldos donde buscar. Por defecto ./respaldos.")
        parser.add_argument("--confirmar", action="store_true",
                            help="Ejecuta la restauración de verdad. Sin esto, solo muestra qué haría.")

    def handle(self, *args, **opts):
        engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite3" not in engine:
            raise CommandError("La restauración automática es para SQLite (uso local).")

        carpeta = carpeta_respaldos(opts["destino"])
        disponibles = sorted(
            carpeta.glob(f"{PREFIJO}*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not opts["archivo"]:
            if not disponibles:
                raise CommandError(f"No hay respaldos en {carpeta}.")
            self.stdout.write("Respaldos disponibles (del más nuevo al más viejo):\n")
            for p in disponibles:
                tam = p.stat().st_size / (1024 * 1024)
                cuando = datetime.fromtimestamp(p.stat().st_mtime)
                self.stdout.write(f"  {p.name}   ({tam:.1f} MB, {cuando:%d/%m/%Y %H:%M})")
            self.stdout.write(
                "\nPara restaurar uno:\n"
                "  python manage.py restaurar --archivo NOMBRE.zip --confirmar"
            )
            return

        # Resolver el zip: nombre suelto -> dentro de la carpeta de respaldos.
        zip_path = Path(opts["archivo"])
        if not zip_path.is_absolute() and not zip_path.exists():
            zip_path = carpeta / opts["archivo"]
        if not zip_path.exists():
            raise CommandError(f"No se encontró el respaldo: {zip_path}")
        if not zipfile.is_zipfile(zip_path):
            raise CommandError(f"El archivo no es un zip válido: {zip_path}")
        with zipfile.ZipFile(zip_path) as z:
            if "db.sqlite3" not in z.namelist():
                raise CommandError("El respaldo no contiene la base de datos (db.sqlite3). ¿Es un respaldo de AllPetcr?")

        db_path = Path(settings.DATABASES["default"]["NAME"])
        media = Path(settings.MEDIA_ROOT)

        if not opts["confirmar"]:
            self.stdout.write(self.style.WARNING(
                f"[SIMULACIÓN] Restauraría desde {zip_path.name}:\n"
                f"  - reemplazaría la base {db_path}\n"
                f"  - reemplazaría las fotos en {media}\n"
                f"Primero guardaría una copia del estado actual.\n\n"
                "Si estás seguro y el servidor está APAGADO, repetí con --confirmar."
            ))
            return

        # 1) Copia de seguridad del estado actual, por si acaso.
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        previa = carpeta / f"antes_de_restaurar_{sello}"
        previa.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            shutil.copy2(db_path, previa / "db.sqlite3")
        if media.exists():
            shutil.copytree(media, previa / "media", dirs_exist_ok=True)

        # 2) Extraer el respaldo a un temporal y mover a su lugar.
        with zipfile.ZipFile(zip_path) as z:
            tmp = carpeta / f"_restaurando_{sello}"
            z.extractall(tmp)
            # Base
            db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp / "db.sqlite3", db_path)
            # Fotos: reemplazar la carpeta media completa
            origen_media = tmp / "media"
            if origen_media.exists():
                if media.exists():
                    shutil.rmtree(media)
                shutil.copytree(origen_media, media)
            shutil.rmtree(tmp, ignore_errors=True)

        self.stdout.write(self.style.SUCCESS(
            f"Restaurado desde {zip_path.name}.\n"
            f"El estado anterior quedó guardado en: {previa}\n"
            "Ya podés encender el sistema (python manage.py runserver)."
        ))
