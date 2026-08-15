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
  * Si están definidas las variables B2_BUCKET/B2_KEY_ID/B2_APPLICATION_KEY/
    B2_ENDPOINT, el zip también se sube a Backblaze B2 (FRA-005, auditoría
    2026-08-15) — un tercero que ni siquiera un administrador del servidor
    puede alterar: la Application Key configurada es "Write Only" (sin
    listar ni borrar) y el bucket tiene Object Lock en modo Compliance, que
    ninguna cuenta puede saltarse antes de que venza la retención. Ver
    PRODUCCION.txt para cómo crear el bucket y la llave. Sin esas variables,
    esta parte simplemente no corre — el respaldo local sigue igual que
    siempre.

Uso:
    python manage.py respaldar
    python manage.py respaldar --conservar 60
    python manage.py respaldar --destino "D:\\RespaldosAllpet"
"""
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

PREFIJO = "respaldo_allpetcr_"

_VARIABLES_B2 = ("B2_BUCKET", "B2_KEY_ID", "B2_APPLICATION_KEY", "B2_ENDPOINT")


def carpeta_respaldos(destino=None) -> Path:
    if destino:
        return Path(destino)
    env = os.environ.get("ALLPETCR_RESPALDOS")
    if env:
        return Path(env)
    return Path(settings.BASE_DIR) / "respaldos"


def _b2_configurado() -> bool:
    """Ausencia de configuración apaga el envío a B2, no lo rompe — mismo
    criterio que EMAIL_HOST_PASSWORD en config/settings.py."""
    return all(os.environ.get(v) for v in _VARIABLES_B2)


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
        es_postgres = "postgresql" in engine
        es_sqlite = "sqlite3" in engine
        if not (es_postgres or es_sqlite):
            raise CommandError(f"Motor de base de datos no soportado por el respaldo: {engine}")

        destino = carpeta_respaldos(opts["destino"])
        destino.mkdir(parents=True, exist_ok=True)
        self._advertir_si_esta_sincronizada(destino)

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = destino / f"{PREFIJO}{sello}.zip"

        with tempfile.TemporaryDirectory() as tmp:
            if es_postgres:
                # El sistema pasó a PostgreSQL el 28/07/2026 y este comando
                # solo sabía respaldar SQLite: desde ese momento `respaldar`
                # abortaba con error y el negocio quedó sin copias nuevas.
                # Migrar de motor sin migrar el respaldo es un riesgo tan
                # grande como el que la migración vino a resolver.
                nombre_interno, ruta_dump = self._volcar_postgres(Path(tmp))
                descripcion_base = settings.DATABASES["default"]["NAME"]
            else:
                db_path = Path(settings.DATABASES["default"]["NAME"])
                if not db_path.exists():
                    raise CommandError(f"No se encontró la base de datos en {db_path}.")
                ruta_dump = Path(tmp) / "db.sqlite3"
                _copia_consistente_sqlite(db_path, ruta_dump)
                nombre_interno = "db.sqlite3"
                descripcion_base = db_path.name

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                # La base, siempre en la raíz del zip con nombre fijo según el
                # motor: así `restaurar` sabe qué está leyendo.
                z.write(ruta_dump, nombre_interno)
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
                    f"Motor: {'PostgreSQL' if es_postgres else 'SQLite'}\n"
                    f"Base: {descripcion_base}\nFotos incluidas: {n_fotos}\n",
                )

        tam_mb = zip_path.stat().st_size / (1024 * 1024)
        borrados = self._rotar(destino, opts["conservar"])

        self.stdout.write(self.style.SUCCESS(
            f"Respaldo listo: {zip_path.name} ({tam_mb:.1f} MB) en {destino}"
        ))
        if borrados:
            self.stdout.write(f"Se borraron {borrados} respaldo(s) viejo(s); se conservan los últimos {opts['conservar']}.")

        if _b2_configurado():
            try:
                self._subir_a_b2(zip_path)
            except (BotoCoreError, ClientError) as e:
                # El respaldo local YA está hecho y rotado — un fallo acá no
                # lo pierde. Pero tiene que quedar visible: código de salida
                # distinto de cero para que el cron lo note.
                raise CommandError(
                    f"El respaldo local quedó bien ({zip_path.name}), pero no se "
                    f"pudo subir a Backblaze B2: {e}"
                )
            self.stdout.write(self.style.SUCCESS(f"Copia enviada a Backblaze B2: {zip_path.name}"))

    # --- respaldo a Backblaze B2 (FRA-005) ---
    def _subir_a_b2(self, zip_path: Path):
        """Sube el zip a B2 vía su API S3-compatible.

        Sin list_objects ni delete_object en ningún lado de este método, a
        propósito: la Application Key configurada (ver PRODUCCION.txt) es
        "Write Only" — no tiene esos permisos de todos modos. El bucket con
        Object Lock en modo Compliance hace el resto: nadie, ni con esta
        llave ni con la cuenta completa, puede borrar la versión subida
        antes de que venza la retención (30 días por defecto)."""
        cliente = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['B2_ENDPOINT']}",
            aws_access_key_id=os.environ["B2_KEY_ID"],
            aws_secret_access_key=os.environ["B2_APPLICATION_KEY"],
        )
        cliente.upload_file(str(zip_path), os.environ["B2_BUCKET"], zip_path.name)

    # --- respaldo de PostgreSQL ---
    def _volcar_postgres(self, tmp: Path):
        """Vuelca la base con pg_dump en formato comprimido propio (-Fc).

        Se usa formato custom y no SQL plano porque permite restaurar tablas
        sueltas y tolera mejor diferencias de versión del servidor.

        La contraseña va por PGPASSWORD en el entorno del subproceso, no en la
        línea de comandos: los argumentos de un proceso son visibles para
        cualquier usuario de la máquina.
        """
        cfg = settings.DATABASES["default"]
        salida = tmp / "db.dump"
        entorno = os.environ.copy()
        if cfg.get("PASSWORD"):
            entorno["PGPASSWORD"] = cfg["PASSWORD"]
        comando = [
            os.environ.get("PG_DUMP_BIN", "pg_dump"),
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            f"--host={cfg.get('HOST') or 'localhost'}",
            f"--port={cfg.get('PORT') or '5432'}",
            f"--username={cfg.get('USER') or ''}",
            f"--file={salida}",
            cfg["NAME"],
        ]
        try:
            proceso = subprocess.run(
                comando, env=entorno, capture_output=True, text=True, timeout=600
            )
        except FileNotFoundError:
            raise CommandError(
                "No se encontró 'pg_dump'. Viene con PostgreSQL; suele estar en\n"
                "  C:\\Program Files\\PostgreSQL\\<version>\\bin\\pg_dump.exe\n"
                "Agregá esa carpeta al PATH, o definí la variable PG_DUMP_BIN con\n"
                "la ruta completa al ejecutable. SIN ESTO NO HAY RESPALDOS."
            )
        except subprocess.TimeoutExpired:
            raise CommandError("pg_dump tardó más de 10 minutos y se canceló.")
        if proceso.returncode != 0:
            raise CommandError(f"pg_dump falló:\n{proceso.stderr.strip()}")
        if not salida.exists() or salida.stat().st_size == 0:
            raise CommandError("pg_dump terminó bien pero no generó archivo. Revisá permisos.")
        return "db.dump", salida

    def _advertir_si_esta_sincronizada(self, destino: Path):
        """Avisa si los respaldos caen en una carpeta de OneDrive/Dropbox.

        Auditoría 2026-07-28, hallazgo ARQ-04: guardar la copia en la misma
        carpeta sincronizada que el original no protege contra el fallo más
        probable de este montaje —que la sincronización propague un borrado o
        una corrupción— ni contra ransomware, que cifra la carpeta completa
        incluidos los respaldos.

        Es una advertencia, no un bloqueo: mejor un respaldo en mal lugar que
        ningún respaldo. Pero que no pase inadvertido.
        """
        ruta = str(destino).lower()
        for nube in ("onedrive", "dropbox", "google drive", "icloud"):
            if nube in ruta:
                self.stdout.write(self.style.WARNING(
                    f"  AVISO: los respaldos se guardan dentro de una carpeta de "
                    f"{nube.title()}.\n"
                    f"  Una copia junto al original no protege si la sincronización "
                    f"propaga un borrado, ni contra ransomware.\n"
                    f"  Definí ALLPETCR_RESPALDOS con una ruta fuera de la nube "
                    f"(por ejemplo un disco externo) o usá --destino."
                ))
                return

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
        borrados = 0
        for v in viejos:
            try:
                v.unlink()
                borrados += 1
            except OSError:
                # No poder borrar un respaldo viejo no debe frenar el respaldo
                # nuevo, pero tiene que quedar constancia (auditoría
                # 2026-07-28, BE-03): si el disco se llena porque los viejos
                # no se están borrando, este log es la única pista.
                logger.warning("No se pudo borrar el respaldo viejo %s", v, exc_info=True)
        return borrados
