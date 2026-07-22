"""Respaldo automático del sistema (Sprint G).

Hace una copia SEGURA de todo lo que no se puede perder:
  - la base de datos (ventas, inventario, contabilidad, clientes…),
  - las fotos de los productos (carpeta media/).

Puntos clave del diseño:
  * La base SQLite se copia con la API de respaldo en caliente de SQLite
    (connection.backup), NO copiando el archivo a lo bruto. Así el respaldo
    queda consistente aunque el sistema esté encendido y alguien esté vendiendo
    en ese momento (copiar el archivo a mano puede guardar una base a medio
    escribir = corrupta).
  * Todo queda en UN zip con fecha y hora en el nombre.
  * Se rotan los respaldos: se conservan los últimos N (por defecto 30) y los
    más viejos se borran solos, para no llenar el disco.
  * La carpeta de respaldos vive dentro del proyecto (que OneDrive sincroniza),
    así que además queda una copia fuera de la computadora.

Uso:
    python manage.py respaldar
    python manage.py respaldar --conservar 60
    python manage.py respaldar --destino "D:\\RespaldosAllpet"
"""
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PREFIJO = "respaldo_allpetcr_"


def carpeta_respaldos(destino=None) -> Path:
    if destino:
        return Path(destino)
    env = os.environ.get("ALLPETCR_RESPALDOS")
    if env:
        return Path(env)
    return Path(settings.BASE_DIR) / "respaldos"


def _copia_consistente_sqlite(db_path: Path, salida: Path):
    """Copia la base SQLite en caliente, consistente, usando la API oficial."""
    origen = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        destino = sqlite3.connect(str(salida))
        try:
            with destino:
                origen.backup(destino)
        finally:
            destino.close()
    finally:
        origen.close()


class Command(BaseCommand):
    help = "Crea un respaldo (base de datos + fotos) en un zip con fecha, y rota los viejos."

    def add_arguments(self, parser):
        parser.add_argument("--conservar", type=int, default=30,
                            help="Cuántos respaldos conservar (los más viejos se borran). Por defecto 30.")
        parser.add_argument("--destino", type=str, default=None,
                            help="Carpeta donde guardar los respaldos. Por defecto ./respaldos.")

    def handle(self, *args, **opts):
        engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite3" not in engine:
            raise CommandError(
                "Este respaldo está hecho para SQLite (el uso local). La base actual "
                f"usa {engine}. En un servidor con Postgres se respalda distinto (pg_dump)."
            )

        db_path = Path(settings.DATABASES["default"]["NAME"])
        if not db_path.exists():
            raise CommandError(f"No se encontró la base de datos en {db_path}.")

        destino = carpeta_respaldos(opts["destino"])
        destino.mkdir(parents=True, exist_ok=True)

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = destino / f"{PREFIJO}{sello}.zip"

        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "db.sqlite3"
            _copia_consistente_sqlite(db_path, snap)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                # La base, siempre en la raíz del zip con nombre fijo.
                z.write(snap, "db.sqlite3")
                # Las fotos de productos (si existen).
                media = Path(settings.MEDIA_ROOT)
                n_fotos = 0
                if media.exists():
                    for archivo in media.rglob("*"):
                        if archivo.is_file():
                            z.write(archivo, Path("media") / archivo.relative_to(media))
                            n_fotos += 1
                # Una marca con info del respaldo, útil al restaurar.
                z.writestr(
                    "RESPALDO.txt",
                    f"Respaldo AllPetcr ERP\nFecha: {datetime.now():%d/%m/%Y %H:%M:%S}\n"
                    f"Base: {db_path.name}\nFotos incluidas: {n_fotos}\n",
                )

        tam_mb = zip_path.stat().st_size / (1024 * 1024)
        borrados = self._rotar(destino, opts["conservar"])

        self.stdout.write(self.style.SUCCESS(
            f"Respaldo listo: {zip_path.name} ({tam_mb:.1f} MB) en {destino}"
        ))
        if borrados:
            self.stdout.write(f"Se borraron {borrados} respaldo(s) viejo(s); se conservan los últimos {opts['conservar']}.")

    def _rotar(self, destino: Path, conservar: int) -> int:
        """Deja solo los 'conservar' respaldos más nuevos. Devuelve cuántos borró."""
        if conservar <= 0:
            return 0
        zips = sorted(
            destino.glob(f"{PREFIJO}*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        viejos = zips[conservar:]
        for v in viejos:
            try:
                v.unlink()
            except OSError:
                pass
        return len(viejos)
