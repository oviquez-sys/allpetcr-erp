"""Restaurar el sistema desde un respaldo (Sprint G).

Devuelve la base de datos y las fotos al estado guardado en un respaldo. Es una
operación delicada, así que el comando:

  1. Exige que el servidor esté APAGADO (SQLite no se puede reemplazar en uso).
  2. Antes de tocar nada, guarda una copia del estado ACTUAL (por si el respaldo
     elegido no era el que querías: siempre hay marcha atrás).
  3. Pide confirmación explícita con --confirmar; sin eso, solo muestra qué haría.
  4. NO pisa `core_auditlog` de la base viva (FRA-003, auditoría 2026-08-15):
     ver `_capturar_auditlog`/`_restaurar_auditlog` más abajo.

Uso:
    python manage.py restaurar                 # lista los respaldos disponibles
    python manage.py restaurar --archivo respaldo_allpetcr_20260721_200000.zip
    python manage.py restaurar --archivo ...zip --confirmar
"""
import os
import shutil
import sqlite3
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .respaldar import PREFIJO, carpeta_respaldos

_TABLA_AUDITLOG = "core_auditlog"
_TABLA_USUARIOS = "auth_user"


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
        es_postgres = "postgresql" in engine
        es_sqlite = "sqlite3" in engine
        if not (es_postgres or es_sqlite):
            raise CommandError(f"Motor no soportado por la restauración: {engine}")

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
        # Qué motor produjo este respaldo: SQLite guarda "db.sqlite3" y
        # PostgreSQL, "db.dump". Se comprueba que coincida con el motor actual
        # para no intentar meter un volcado de Postgres en un archivo SQLite
        # (o al revés), que dejaría la base inservible.
        with zipfile.ZipFile(zip_path) as z:
            contenido = z.namelist()
            tiene_sqlite = "db.sqlite3" in contenido
            tiene_dump = "db.dump" in contenido
        if not (tiene_sqlite or tiene_dump):
            raise CommandError(
                "El respaldo no contiene la base de datos (ni db.sqlite3 ni db.dump). "
                "¿Es un respaldo de AllPetcr?"
            )
        if es_postgres and not tiene_dump:
            raise CommandError(
                "Este respaldo es de la época de SQLite y la base actual es PostgreSQL.\n"
                "No se puede restaurar automáticamente: hay que volver a migrar los datos.\n"
                "Los respaldos hechos desde el 28/07/2026 sí son compatibles."
            )
        if es_sqlite and not tiene_sqlite:
            raise CommandError(
                "Este respaldo es de PostgreSQL y la base actual es SQLite. "
                "Configurá POSTGRES_HOST antes de restaurar."
            )

        media = Path(settings.MEDIA_ROOT)
        db_path = None if es_postgres else Path(settings.DATABASES["default"]["NAME"])
        descripcion_base = (
            f"la base PostgreSQL '{settings.DATABASES['default']['NAME']}'"
            if es_postgres else f"la base {db_path}"
        )

        if not opts["confirmar"]:
            self.stdout.write(self.style.WARNING(
                f"[SIMULACIÓN] Restauraría desde {zip_path.name}:\n"
                f"  - reemplazaría {descripcion_base}\n"
                f"  - reemplazaría las fotos en {media}\n"
                f"Primero guardaría una copia del estado actual.\n\n"
                "Si estás seguro y el servidor está APAGADO, repetí con --confirmar."
            ))
            return

        # 1) Copia de seguridad del estado actual, por si acaso.
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        previa = carpeta / f"antes_de_restaurar_{sello}"
        previa.mkdir(parents=True, exist_ok=True)
        if db_path is not None and db_path.exists():
            shutil.copy2(db_path, previa / "db.sqlite3")
        if media.exists():
            shutil.copytree(media, previa / "media", dirs_exist_ok=True)

        # FRA-003: capturar la bitácora de la base VIVA antes de tocar nada.
        # Un restaurar no debe poder borrar el rastro de lo que pasó entre el
        # respaldo elegido y este momento —incluido el rastro de un fraude
        # que alguien quisiera tapar restaurando un respaldo viejo—.
        cfg = settings.DATABASES["default"]
        columnas_auditlog, filas_auditlog = self._capturar_auditlog(cfg, es_postgres, db_path)

        # 2) Extraer el respaldo a un temporal y mover a su lugar.
        with zipfile.ZipFile(zip_path) as z:
            tmp = carpeta / f"_restaurando_{sello}"
            z.extractall(tmp)
            # Base
            if es_postgres:
                self._restaurar_postgres(tmp / "db.dump")
            else:
                db_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tmp / "db.sqlite3", db_path)
            # Fotos: reemplazar la carpeta media completa
            origen_media = tmp / "media"
            if origen_media.exists():
                if media.exists():
                    shutil.rmtree(media)
                shutil.copytree(origen_media, media)
            shutil.rmtree(tmp, ignore_errors=True)

        cuantas = self._restaurar_auditlog(cfg, es_postgres, db_path, columnas_auditlog, filas_auditlog)
        if cuantas is not None:
            self.stdout.write(f"Bitácora (AuditLog) de la base viva preservada: {cuantas} registro(s).")

        self.stdout.write(self.style.SUCCESS(
            f"Restaurado desde {zip_path.name}.\n"
            f"El estado anterior quedó guardado en: {previa}\n"
            "Ya podés encender el sistema (python manage.py runserver)."
        ))

    def _restaurar_postgres(self, dump: Path):
        """Restaura el volcado con pg_restore, reemplazando lo que haya.

        `--clean --if-exists` borra los objetos anteriores antes de recrearlos:
        sin eso, restaurar sobre una base con datos deja una mezcla de los dos
        estados, que es peor que cualquiera de los dos por separado.

        pg_restore devuelve código distinto de cero por advertencias que no son
        errores reales (por ejemplo, intentar borrar algo que no existía). Por
        eso se revisa el texto del error en vez de confiar solo en el código.
        """
        cfg = settings.DATABASES["default"]
        entorno = os.environ.copy()
        if cfg.get("PASSWORD"):
            entorno["PGPASSWORD"] = cfg["PASSWORD"]
        comando = [
            os.environ.get("PG_RESTORE_BIN", "pg_restore"),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            f"--host={cfg.get('HOST') or 'localhost'}",
            f"--port={cfg.get('PORT') or '5432'}",
            f"--username={cfg.get('USER') or ''}",
            f"--dbname={cfg['NAME']}",
            str(dump),
        ]
        try:
            proceso = subprocess.run(
                comando, env=entorno, capture_output=True, text=True, timeout=1800
            )
        except FileNotFoundError:
            raise CommandError(
                "No se encontró 'pg_restore'. Viene con PostgreSQL, en la misma\n"
                "carpeta que pg_dump. Agregala al PATH o definí PG_RESTORE_BIN."
            )
        except subprocess.TimeoutExpired:
            raise CommandError("pg_restore tardó más de 30 minutos y se canceló.")
        if proceso.returncode != 0 and "error" in (proceso.stderr or "").lower():
            raise CommandError(f"pg_restore falló:\n{proceso.stderr.strip()}")
        if proceso.stderr and proceso.stderr.strip():
            self.stdout.write(self.style.WARNING(
                "pg_restore reportó avisos (normalmente inofensivos):\n"
                + proceso.stderr.strip()[:1000]
            ))

    # --- FRA-003: la bitácora de la base viva no se pisa con la del respaldo ---
    #
    # `core_auditlog` es la única evidencia de qué pasó ENTRE que se tomó el
    # respaldo elegido y el momento de restaurar — incluido, en el peor caso,
    # el rastro de un fraude que alguien restaura un respaldo viejo para tapar.
    # Antes de esta corrección, restaurar traía la bitácora del zip, que es
    # estrictamente más vieja: como AuditLog es de solo agregar (nunca se
    # edita ni se borra, verificado en el análisis de FRA-001/002), la de la
    # base viva siempre contiene todo lo que tendría la del respaldo y más —
    # por eso "reemplazar con la versión viva" es seguro, no hace falta fusionar.
    #
    # Deliberadamente tolerante a fallas: si la tabla no existe (instalación
    # nueva, o una base de pruebas sin las migraciones de core) o algo sale
    # mal, se avisa por stdout y el restaurar del resto del sistema sigue
    # funcionando exactamente igual que antes de este cambio — no se vuelve
    # un punto único de falla para la funcionalidad principal del comando.

    def _capturar_auditlog(self, cfg, es_postgres, db_path):
        """Lee core_auditlog de la base VIVA, antes de tocar nada. Devuelve
        (columnas, filas) o (None, None) si no hay nada que preservar."""
        try:
            if es_postgres:
                return self._leer_tabla_postgres(cfg, _TABLA_AUDITLOG)
            return self._leer_tabla_sqlite(db_path, _TABLA_AUDITLOG)
        except Exception:
            self.stdout.write(self.style.WARNING(
                f"No se pudo leer {_TABLA_AUDITLOG} de la base actual antes de "
                "restaurar (¿instalación nueva?). La restauración sigue, pero "
                "no hay bitácora previa que preservar."
            ))
            return None, None

    def _restaurar_auditlog(self, cfg, es_postgres, db_path, columnas, filas):
        """Reinserta la bitácora capturada antes de restaurar, reemplazando lo
        que haya traído el respaldo para esa tabla. Devuelve cuántas filas
        preservó, o None si no había nada capturado."""
        if columnas is None:
            return None
        try:
            if es_postgres:
                return self._escribir_tabla_postgres(cfg, _TABLA_AUDITLOG, columnas, filas)
            return self._escribir_tabla_sqlite(db_path, _TABLA_AUDITLOG, columnas, filas)
        except Exception:
            self.stdout.write(self.style.WARNING(
                f"El restaurar terminó, pero no se pudo reescribir {_TABLA_AUDITLOG} "
                "con la bitácora de la base viva — revisar a mano."
            ))
            return None

    def _leer_tabla_sqlite(self, db_path, tabla):
        if db_path is None or not db_path.exists():
            return None, None
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cur = con.execute(f"SELECT * FROM {tabla} ORDER BY id")
            columnas = [d[0] for d in cur.description]
            return columnas, cur.fetchall()
        except sqlite3.OperationalError:
            return None, None
        finally:
            con.close()

    def _escribir_tabla_sqlite(self, db_path, tabla, columnas, filas):
        con = sqlite3.connect(str(db_path))
        try:
            idx_usuario = columnas.index("usuario_id") if "usuario_id" in columnas else None
            ids_validos = set()
            if idx_usuario is not None:
                ids_validos = {r[0] for r in con.execute(f"SELECT id FROM {_TABLA_USUARIOS}")}
            con.execute(f"DELETE FROM {tabla}")
            marcadores = ",".join("?" * len(columnas))
            cols_sql = ",".join(columnas)
            for fila in filas:
                fila = list(fila)
                # usuario_id puede apuntar a alguien que no existe en la base
                # restaurada (creado después del respaldo elegido) — mismo
                # criterio que el propio modelo ya declara para el borrado de
                # usuarios (on_delete=SET_NULL): sin ese usuario, el campo
                # queda nulo, no se rompe la restauración por esto.
                if idx_usuario is not None and fila[idx_usuario] is not None and fila[idx_usuario] not in ids_validos:
                    fila[idx_usuario] = None
                con.execute(f"INSERT INTO {tabla} ({cols_sql}) VALUES ({marcadores})", fila)
            con.commit()
            return len(filas)
        finally:
            con.close()

    def _leer_tabla_postgres(self, cfg, tabla):
        import psycopg2

        con = psycopg2.connect(
            host=cfg.get("HOST") or "localhost", port=cfg.get("PORT") or "5432",
            user=cfg.get("USER") or "", password=cfg.get("PASSWORD") or "", dbname=cfg["NAME"],
        )
        try:
            cur = con.cursor()
            cur.execute(f"SELECT * FROM {tabla} ORDER BY id")
            columnas = [d.name for d in cur.description]
            return columnas, cur.fetchall()
        except psycopg2.Error:
            return None, None
        finally:
            con.close()

    def _escribir_tabla_postgres(self, cfg, tabla, columnas, filas):
        import psycopg2
        from psycopg2.extras import Json

        con = psycopg2.connect(
            host=cfg.get("HOST") or "localhost", port=cfg.get("PORT") or "5432",
            user=cfg.get("USER") or "", password=cfg.get("PASSWORD") or "", dbname=cfg["NAME"],
        )
        try:
            cur = con.cursor()
            idx_usuario = columnas.index("usuario_id") if "usuario_id" in columnas else None
            ids_validos = set()
            if idx_usuario is not None:
                cur.execute(f"SELECT id FROM {_TABLA_USUARIOS}")
                ids_validos = {r[0] for r in cur.fetchall()}
            cur.execute(f"DELETE FROM {tabla}")
            marcadores = ",".join(["%s"] * len(columnas))
            cols_sql = ",".join(columnas)
            for fila in filas:
                fila = list(fila)
                if idx_usuario is not None and fila[idx_usuario] is not None and fila[idx_usuario] not in ids_validos:
                    fila[idx_usuario] = None
                # jsonb (antes/despues) necesita el envoltorio Json: psycopg2
                # no adapta un dict/list de Python automáticamente al insertar
                # con una conexión propia (fuera del ORM de Django).
                fila = [Json(v) if isinstance(v, (dict, list)) else v for v in fila]
                cur.execute(f"INSERT INTO {tabla} ({cols_sql}) VALUES ({marcadores})", fila)
            if filas:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    f"(SELECT COALESCE(MAX(id), 1) FROM {tabla}))",
                    (tabla,),
                )
            con.commit()
            return len(filas)
        finally:
            con.close()
