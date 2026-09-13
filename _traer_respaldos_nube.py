"""Baja a esta computadora los respaldos que el servidor hace solo.

QUÉ PROBLEMA RESUELVE
    Desde que el ERP corre en DigitalOcean, las ventas del día ya no pasan por
    esta computadora. El respaldo diario de acá seguía sacando copia de la base
    LOCAL —la vieja— y nadie lo notaba: la tarea aparecía en verde todos los
    días respaldando datos que ya no son los del negocio.

    Ahora el servidor se respalda solo y deja el archivo en el bucket. Este
    programa lo trae a OneDrive. Con eso la copia queda en OTRA empresa y en
    OTRA cuenta: si mañana se pierde el acceso a DigitalOcean —una tarjeta
    rechazada, una cuenta suspendida, un borrado por error— el negocio se puede
    reconstruir igual.

POR QUÉ BAJAR Y NO CONFIAR EN LA NUBE
    DigitalOcean guarda respaldos automáticos de la base, pero solo 7 días, en
    la misma cuenta. Un error que se descubre tarde (alguien borró productos el
    mes pasado) y una cuenta que se pierde son justo los dos casos que esos
    respaldos NO cubren.

CÓMO SE USA
    Doble clic en TRAER_RESPALDOS_NUBE.bat, o dejarlo a la tarea programada
    "AllPetCR - Traer respaldos del servidor", que corre todos los días.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# Los mismos datos que usa la subida de fotos: el bucket es el mismo, lo único
# distinto es la carpeta de adentro.
BUCKET = "allpetcr-fotos"
REGION = "nyc3"
ENDPOINT = f"https://{REGION}.digitaloceanspaces.com"
CARPETA_EN_EL_BUCKET = "respaldos/"

# Cuántas copias conservar en esta computadora. Cada una pesa menos de 1 MB
# (es solo la base, sin fotos), así que 60 días de historia ocupan poco y
# cubren de sobra el caso "esto se rompió hace un mes y nadie lo vio".
CONSERVAR = 60

CARPETA_NUBE = "AllPetCR_Respaldos"
SUBCARPETA = "servidor"

try:
    from _llaves_spaces import ACCESS_KEY_ID, SECRET_ACCESS_KEY
except ImportError:  # pragma: no cover - solo si falta el archivo de llaves
    ACCESS_KEY_ID = SECRET_ACCESS_KEY = ""


def avisar(asunto: str, cuerpo: str):
    """Le manda el aviso a Oscar por correo.

    Una tarea programada que falla en silencio no sirve de nada: nadie abre el
    Programador de tareas a ver cómo le fue. El mismo mecanismo que ya usa
    _respaldo_programado.py, y con la misma regla: si el correo tampoco
    funciona, se anota y se sigue — nunca tapa el problema original.
    """
    try:
        import os

        import django

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        django.setup()
        from django.core.mail import EmailMessage

        destino = os.environ.get("RESPALDO_AVISO_A") or os.environ.get("EMAIL_HOST_USER")
        if not destino:
            print("  (no hay a quién avisar: falta RESPALDO_AVISO_A o EMAIL_HOST_USER)")
            return
        EmailMessage(subject=asunto, body=cuerpo, to=[destino]).send(fail_silently=False)
        print(f"  Aviso enviado a {destino}")
    except Exception as e:  # noqa: BLE001
        print(f"  No se pudo mandar el aviso por correo: {e}")


def fallar(mensaje: str):
    print()
    print("  " + mensaje)
    print()
    sys.exit(1)


def carpeta_destino() -> Path:
    """OneDrive si está; si no, una carpeta local avisando que no basta.

    Se leen las variables que Windows define, nunca una ruta escrita a mano:
    una ruta a mano es lo que rompió el acceso directo al cambiar el disco.
    """
    import os

    for var in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        ruta = os.environ.get(var)
        if ruta and Path(ruta).is_dir():
            return Path(ruta) / CARPETA_NUBE / SUBCARPETA
    print()
    print("  ATENCIÓN: no encontré OneDrive. Las copias quedan solo en esta")
    print("  computadora, que es justo lo que hay que evitar.")
    return BASE / "respaldos" / SUBCARPETA


def main():
    print()
    print("=" * 66)
    print("  TRAER LOS RESPALDOS DEL SERVIDOR")
    print("=" * 66)
    print(f"  {datetime.now():%d/%m/%Y %H:%M:%S}")

    if not (ACCESS_KEY_ID and SECRET_ACCESS_KEY):
        fallar("Falta el archivo _llaves_spaces.py con las llaves del bucket.\n"
               "  Avisale a Claude y te lo vuelve a dejar.")
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        fallar("Falta el paquete 'boto3'. Corré INSTALAR_RESPALDO_NUBE.bat.")

    destino = carpeta_destino()
    destino.mkdir(parents=True, exist_ok=True)
    print(f"\n  Destino: {destino}")

    cliente = boto3.client(
        "s3", endpoint_url=ENDPOINT, region_name=REGION,
        aws_access_key_id=ACCESS_KEY_ID, aws_secret_access_key=SECRET_ACCESS_KEY,
    )

    try:
        pagina = cliente.list_objects_v2(Bucket=BUCKET, Prefix=CARPETA_EN_EL_BUCKET)
    except (BotoCoreError, ClientError) as e:
        fallar(f"No pude leer el bucket: {e}")

    remotos = sorted(
        (o for o in pagina.get("Contents", []) if o["Key"].endswith(".zip")),
        key=lambda o: o["LastModified"], reverse=True,
    )
    if not remotos:
        # No es un error del programa, pero SÍ es una señal: el servidor
        # debería estar dejando una copia por día.
        print("\n  ⚠ No hay ningún respaldo en el servidor.")
        print("  Si esto se repite mañana, el trabajo programado del ERP no está")
        print("  corriendo. Avisale a Claude.")
        avisar("AllPetCR: el servidor no está dejando respaldos",
               "No hay ningún respaldo en el bucket del servidor.\n\n"
               "El trabajo programado del ERP en DigitalOcean no está corriendo, "
               "o está fallando. Mientras tanto, lo único que protege las ventas "
               "es el respaldo automático de DigitalOcean, que dura 7 días.")
        return 1

    bajados = 0
    for objeto in remotos[:CONSERVAR]:
        nombre = objeto["Key"].split("/")[-1]
        archivo = destino / nombre
        # Ya está y con el mismo tamaño: no se vuelve a bajar. Así la tarea
        # puede correr todos los días sin gastar datos ni tiempo de más.
        if archivo.is_file() and archivo.stat().st_size == objeto["Size"]:
            continue
        try:
            cliente.download_file(BUCKET, objeto["Key"], str(archivo))
        except (BotoCoreError, ClientError) as e:
            print(f"  ⛔ No pude bajar {nombre}: {e}")
            continue
        bajados += 1
        print(f"  ✅ {nombre}  ({objeto['Size'] / 1024:.0f} KB)")

    locales = sorted(destino.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)
    borrados = 0
    for viejo in locales[CONSERVAR:]:
        try:
            viejo.unlink()
            borrados += 1
        except OSError:
            pass  # que no se pueda borrar uno viejo no arruina la copia nueva

    ultimo = remotos[0]
    edad_horas = (datetime.now(ultimo["LastModified"].tzinfo)
                  - ultimo["LastModified"]).total_seconds() / 3600

    print()
    print(f"  Copias nuevas bajadas: {bajados}")
    if borrados:
        print(f"  Copias viejas borradas de esta computadora: {borrados}")
    print(f"  Respaldo más reciente del servidor: {ultimo['LastModified']:%d/%m/%Y %H:%M} "
          f"({edad_horas:.0f} h)")

    # 36 horas es un día y medio: da margen para que el servidor se salte una
    # corrida por un despliegue, pero no para que el respaldo lleve días caído
    # sin que nadie lo note.
    if edad_horas > 36:
        print()
        print("  ⚠ El último respaldo del servidor tiene más de un día y medio.")
        print("  El trabajo programado del ERP puede estar fallando.")
        avisar("AllPetCR: el respaldo del servidor se atrasó",
               f"El respaldo más reciente del servidor es del "
               f"{ultimo['LastModified']:%d/%m/%Y %H:%M} ({edad_horas:.0f} horas).\n\n"
               "Debería haber uno por día. Revisá el trabajo programado del ERP "
               "en DigitalOcean.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
