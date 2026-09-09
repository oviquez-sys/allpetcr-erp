"""Respaldo automatico: lo hace, lo verifica, y AVISA si algo sale mal.

Uso:
    python _respaldo_programado.py diario     # solo la base, todos los dias
    python _respaldo_programado.py semanal    # base + fotos, una vez por semana

Por que existe (01/09/2026)
---------------------------
El respaldo automatico habia dejado de correr en algun momento y nadie se
entero durante 29 dias. Ese es el problema de verdad: no que fallara, sino que
fallara EN SILENCIO. Un respaldo que nadie mira es una carpeta con archivos.

Por eso este script hace tres cosas que el comando `respaldar` solo no hace:

  1. Guarda en OneDrive, fuera de esta computadora. Un respaldo en el mismo
     disco que la base no protege del caso que mas importa: que el disco muera.
  2. VERIFICA lo que acaba de crear: que el zip abra, que traiga la base
     adentro, y que PostgreSQL pueda LEER ese volcado. Que el archivo exista no
     prueba que sirva.
  3. AVISA por correo cuando algo falla, y deja constancia en un archivo de
     estado que el ERP puede leer.

Estrategia de dos ritmos
------------------------
El respaldo completo pesa ~130 MB, casi todo fotos. Guardar eso a diario llena
la nube en semanas. Pero la base --donde viven las ventas, el inventario y la
contabilidad-- pesa menos de 1 MB.

    Diario  : solo la base. Se conservan 30. Ocupa ~15 MB en total.
    Semanal : base + fotos. Se conservan 4. Ocupa ~520 MB.

Asi se pierde como maximo un dia de ventas, y las fotos --que cambian poco--
tienen copia de las ultimas 4 semanas.

Por que cada ritmo va en SU PROPIA subcarpeta (02/09/2026)
-----------------------------------------------------------
`respaldar` rota borrando los mas viejos que coinciden con el prefijo
`respaldo_allpetcr_*.zip` DENTRO de la carpeta destino. Si los dos ritmos
escribieran en la misma carpeta, el respaldo semanal --que conserva 4-- borraria
los 30 diarios el domingo por la noche. Quedarian 4 archivos en total y nadie
se enteraria hasta el dia que hicieran falta.

Separar las carpetas es lo que hace que "conservar 30" y "conservar 4"
signifiquen lo que dicen.
"""
import json
import os
import subprocess
import sys
import tempfile
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.management import call_command  # noqa: E402

ESTADO = Path("respaldos") / "ultimo_respaldo.json"
CARPETA_NUBE = "AllPetCR_Respaldos"


def carpeta_onedrive():
    """La carpeta de OneDrive de este usuario, o None si no hay.

    Windows define estas variables cuando OneDrive esta configurado. Se leen en
    vez de escribir la ruta a mano porque una ruta escrita a mano es
    exactamente lo que rompio el acceso directo del ERP al cambiar de disco.
    """
    for var in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        ruta = os.environ.get(var)
        if ruta and Path(ruta).is_dir():
            return Path(ruta) / CARPETA_NUBE
    return None


def dump_legible_por_postgres(zip_path: Path, nombre_interno: str):
    """Comprueba que el volcado de adentro del zip lo pueda leer PostgreSQL.

    Devuelve (ok, detalle). Si no se encuentra pg_restore devuelve (True, ...)
    con una nota: no poder hacer la comprobacion no es lo mismo que que falle,
    y frenar el respaldo por eso seria peor que el problema.

    Por que esta comprobacion y no solo "el zip abre" (02/09/2026)
    ---------------------------------------------------------------
    Que un zip abra solo prueba que el zip esta bien. Adentro puede haber un
    archivo db.dump que sea basura: pg_dump interrumpido, disco lleno a mitad
    de camino, o el mensaje de error de pg_dump guardado como si fuera datos.
    `pg_restore --list` abre el volcado y lee su indice interno: si eso
    funciona, el archivo es un volcado de PostgreSQL de verdad y trae una lista
    de objetos. No es un ensayo de restauracion completo --para eso esta
    _prueba_restauracion.py-- pero descarta el caso mas comun de archivo inutil.
    """
    binario = os.environ.get("PG_RESTORE_BIN", "pg_restore")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(zip_path) as z:
                extraido = Path(z.extract(nombre_interno, tmp))
        except (KeyError, zipfile.BadZipFile) as e:
            return False, f"No se pudo sacar {nombre_interno} del zip: {e}"

        try:
            proceso = subprocess.run(
                [binario, "--list", str(extraido)],
                capture_output=True, text=True, timeout=180,
            )
        except FileNotFoundError:
            return True, ("no se pudo comprobar con pg_restore (no esta en el PATH); "
                          "defini PG_RESTORE_BIN si queres esta revision")
        except subprocess.TimeoutExpired:
            return False, "pg_restore --list tardo mas de 3 minutos leyendo el volcado"

        if proceso.returncode != 0:
            return False, f"PostgreSQL no puede leer el volcado: {proceso.stderr.strip()[:400]}"

        # El indice lista un objeto por linea; las que empiezan con ';' son
        # comentarios de cabecera. Un volcado de una base con datos trae
        # decenas de objetos. Cero objetos = volcado de una base vacia.
        objetos = [l for l in proceso.stdout.splitlines() if l.strip() and not l.startswith(";")]
        if not objetos:
            return False, "el volcado se lee pero esta vacio: no contiene ni una tabla"
        return True, f"pg_restore lee el volcado: {len(objetos)} objetos"


def verificar(zip_path: Path, espera_fotos: bool):
    """Comprueba que el respaldo recien hecho sirva. Devuelve (ok, detalle)."""
    if not zip_path.exists():
        return False, "El archivo no se creo."
    if zip_path.stat().st_size < 10_000:
        return False, f"El archivo pesa solo {zip_path.stat().st_size} bytes: esta vacio."
    try:
        with zipfile.ZipFile(zip_path) as z:
            danado = z.testzip()
            if danado:
                return False, f"El zip esta danado (falla en {danado})."
            nombres = z.namelist()
    except zipfile.BadZipFile:
        return False, "No es un zip valido."

    bases = [n for n in nombres if n.lower().endswith((".dump", ".sql", ".sqlite3"))]
    if not bases:
        return False, "El zip no trae la base de datos adentro."

    fotos = [n for n in nombres if n.lower().startswith("media/")]
    if espera_fotos and not fotos:
        return False, "Se pidio respaldo con fotos y el zip no trae ninguna."

    resumen = f"{len(nombres)} archivos, base: {bases[0]}, fotos: {len(fotos)}"

    if bases[0].endswith(".dump"):
        ok_dump, detalle_dump = dump_legible_por_postgres(zip_path, bases[0])
        if not ok_dump:
            return False, f"{resumen} — PERO {detalle_dump}"
        resumen += f" — {detalle_dump}"

    return True, resumen


def avisar_por_correo(asunto, cuerpo):
    """Manda el aviso. Si el correo tampoco funciona, no tapa el error original."""
    try:
        from django.core.mail import EmailMessage

        destino = os.environ.get("RESPALDO_AVISO_A") or os.environ.get("EMAIL_HOST_USER")
        if not destino:
            print("  (no hay a quien avisar: falta RESPALDO_AVISO_A o EMAIL_HOST_USER)")
            return
        EmailMessage(subject=asunto, body=cuerpo, to=[destino]).send(fail_silently=False)
        print(f"  Aviso enviado a {destino}")
    except Exception as e:  # noqa: BLE001
        print(f"  No se pudo mandar el aviso por correo: {e}")


def guardar_estado(datos):
    try:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print(f"  No se pudo escribir el estado: {e}")


def main():
    modo = (sys.argv[1] if len(sys.argv) > 1 else "diario").lower()
    if modo not in ("diario", "semanal"):
        print("Uso: python _respaldo_programado.py [diario|semanal]")
        return 2

    con_fotos = modo == "semanal"
    conservar = 4 if con_fotos else 30
    inicio = datetime.now()

    print("=" * 70)
    print(f"RESPALDO {modo.upper()} - {inicio:%d/%m/%Y %H:%M:%S}")
    print("=" * 70)

    nube = carpeta_onedrive()
    if nube is None:
        print("\nATENCION: no se encontro la carpeta de OneDrive. El respaldo se")
        print("guarda solo en esta computadora, que es justo lo que hay que evitar.")
        destino = Path("respaldos") / modo
        en_la_nube = False
    else:
        destino = nube / modo
        en_la_nube = True

    destino.mkdir(parents=True, exist_ok=True)
    print(f"\nDestino: {destino}")

    try:
        call_command("respaldar", destino=str(destino), conservar=conservar,
                     sin_fotos=not con_fotos)
    except Exception:
        detalle = traceback.format_exc()
        print("\nFALLO EL RESPALDO:\n")
        print(detalle)
        guardar_estado({"modo": modo, "fecha": inicio.isoformat(), "ok": False,
                        "error": detalle[-2000:]})
        avisar_por_correo(
            f"[AllPetCR] FALLO el respaldo {modo}",
            "El respaldo automatico del ERP fallo.\n\n"
            f"Fecha: {inicio:%d/%m/%Y %H:%M}\nModo: {modo}\n\n"
            f"Detalle tecnico:\n{detalle}\n\n"
            "Mientras esto no se arregle, el negocio esta sin copia nueva.",
        )
        return 1

    # El comando no devuelve la ruta, asi que se busca el zip mas nuevo.
    zips = sorted(destino.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not zips:
        print("\nEl comando termino bien pero no aparecio ningun zip. Raro.")
        guardar_estado({"modo": modo, "fecha": inicio.isoformat(), "ok": False,
                        "error": "No se encontro el zip generado."})
        avisar_por_correo(f"[AllPetCR] Respaldo {modo} sin archivo",
                          "El respaldo dijo que termino bien pero no dejo ningun archivo.")
        return 1

    reciente = zips[0]
    ok, detalle = verificar(reciente, espera_fotos=con_fotos)
    peso = reciente.stat().st_size

    print(f"\nArchivo   : {reciente.name}")
    print(f"Peso      : {peso:,} bytes")
    print(f"Verificado: {'SI' if ok else 'NO'} - {detalle}")
    print(f"En la nube: {'SI' if en_la_nube else 'NO'}")

    guardar_estado({
        "modo": modo, "fecha": inicio.isoformat(), "ok": ok,
        "archivo": str(reciente), "peso": peso, "detalle": detalle,
        "en_la_nube": en_la_nube,
    })

    if not ok:
        avisar_por_correo(
            f"[AllPetCR] El respaldo {modo} NO paso la verificacion",
            f"Se creo el archivo {reciente.name} pero no pasa la revision.\n\n"
            f"Problema: {detalle}\n\n"
            "O sea que hay un archivo, pero no sirve para recuperar el negocio.",
        )
        return 1

    if not en_la_nube:
        avisar_por_correo(
            "[AllPetCR] El respaldo quedo solo en la computadora",
            "El respaldo se hizo y esta bien, pero no se encontro OneDrive, asi que "
            "quedo en el mismo disco que la base de datos.\n\n"
            "Si ese disco falla, se pierden los dos juntos.",
        )

    print("\nLISTO. Respaldo hecho, verificado y guardado fuera de la computadora.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
