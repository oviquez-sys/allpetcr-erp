"""ENSAYO DE RESTAURACION: prueba que el negocio se puede recuperar de verdad.

Que hace
--------
1. Toma el respaldo mas reciente (busca tambien en OneDrive).
2. Crea una base de datos NUEVA y desechable: allpetcr_ensayo_<fecha y hora>.
3. Restaura el volcado ahi adentro con pg_restore, con las MISMAS opciones que
   usa `python manage.py restaurar`.
4. Cuenta lo que quedo: productos, ventas, movimientos de inventario.
5. Lo compara con lo que hay hoy en la base real.
6. Borra la base de prueba.

LA BASE REAL NO SE TOCA. El script se niega a arrancar si el nombre de la base
de prueba coincidiera con el de la real.

Por que hace falta, si ya hay pruebas automaticas (02/09/2026)
---------------------------------------------------------------
`core/test_respaldos.py` ya prueba el ciclo respaldar -> restaurar, pero lo
hace con bases de mentira creadas para la prueba. Eso comprueba que el CODIGO
funciona.

Esto es otra cosa: agarra EL ARCHIVO QUE ESTA HOY EN ONEDRIVE --el que hizo la
tarea programada anoche, con los datos reales del negocio-- y lo restaura en un
PostgreSQL de verdad. Comprueba que ESE archivo sirve.

La pregunta que importa no es "¿el codigo de respaldo esta bien probado?" sino
"¿puedo abrir la tienda manana si esta computadora no prende?". Solo se
contesta restaurando el archivo real.

Conviene correrlo una vez por mes, y siempre despues de cambiar algo del
sistema de respaldos.
"""
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings  # noqa: E402

import psycopg2  # noqa: E402
from psycopg2 import sql  # noqa: E402
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT  # noqa: E402

CFG = settings.DATABASES["default"]
SELLO = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_ENSAYO = f"allpetcr_ensayo_{SELLO}"
PREFIJO = "respaldo_allpetcr_"

# Lo que se cuenta para comparar. Son las tablas donde vive el negocio: si
# estas vuelven completas, volvio todo lo que importa.
TABLAS = [
    ("Productos", "catalogo_producto"),
    ("Facturas de venta", "ventas_facturaventa"),
    ("Movimientos de inventario", "inventario_movimientoinventario"),
]


def respaldos_disponibles():
    """Todos los respaldos que se encuentren, del mas nuevo al mas viejo.

    Busca en la carpeta local y en OneDrive, entrando en subcarpetas: desde el
    02/09/2026 los respaldos diarios y semanales viven separados en
    AllPetCR_Respaldos\\diario y AllPetCR_Respaldos\\semanal.
    """
    carpetas = []
    env = os.environ.get("ALLPETCR_RESPALDOS")
    if env:
        carpetas.append(Path(env))
    carpetas.append(Path(settings.BASE_DIR) / "respaldos")
    for var in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        ruta = os.environ.get(var)
        if ruta and Path(ruta).is_dir():
            carpetas.append(Path(ruta) / "AllPetCR_Respaldos")

    encontrados = {}
    for carpeta in carpetas:
        if not carpeta.is_dir():
            continue
        for z in carpeta.rglob(f"{PREFIJO}*.zip"):
            encontrados[z.resolve()] = z
    return sorted(encontrados.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def conectar(nombre_base):
    return psycopg2.connect(
        dbname=nombre_base,
        user=CFG.get("USER") or "",
        password=CFG.get("PASSWORD") or "",
        host=CFG.get("HOST") or "localhost",
        port=CFG.get("PORT") or "5432",
    )


def contar(nombre_base):
    """Cuenta las filas de las tablas del negocio. None = la tabla no esta."""
    conn = conectar(nombre_base)
    try:
        resultados = {}
        with conn.cursor() as cur:
            for etiqueta, tabla in TABLAS:
                try:
                    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(tabla)))
                    resultados[etiqueta] = cur.fetchone()[0]
                except psycopg2.Error:
                    conn.rollback()
                    resultados[etiqueta] = None
        return resultados
    finally:
        conn.close()


def restaurar_en(base_destino, volcado):
    """pg_restore con las MISMAS opciones que usa `manage.py restaurar`.

    Se repiten aca en vez de llamar al comando porque el comando restaura
    siempre sobre la base configurada --la real--, que es justo lo que este
    ensayo NO debe tocar. Si esas opciones cambian alla, hay que cambiarlas
    aca: lo cubre test_ensayo_usa_las_mismas_opciones_que_restaurar.
    """
    entorno = os.environ.copy()
    if CFG.get("PASSWORD"):
        entorno["PGPASSWORD"] = CFG["PASSWORD"]
    comando = [
        os.environ.get("PG_RESTORE_BIN", "pg_restore"),
        "--clean", "--if-exists", "--no-owner", "--no-privileges",
        f"--host={CFG.get('HOST') or 'localhost'}",
        f"--port={CFG.get('PORT') or '5432'}",
        f"--username={CFG.get('USER') or ''}",
        f"--dbname={base_destino}",
        str(volcado),
    ]
    return subprocess.run(comando, env=entorno, capture_output=True, text=True, timeout=1800)


def main():
    print("=" * 72)
    print("ENSAYO DE RESTAURACION")
    print("=" * 72)

    if "postgresql" not in CFG["ENGINE"]:
        print("\nEste ensayo esta escrito para PostgreSQL y la base actual no lo es.")
        return 2

    # Guarda de seguridad. Es practicamente imposible que coincidan, pero el
    # precio de equivocarse aca es borrar la base del negocio.
    if BASE_ENSAYO == CFG["NAME"]:
        print("\nABORTADO: la base de prueba tendria el mismo nombre que la real.")
        return 2

    print(f"\nBase real     : {CFG['NAME']}   (NO se toca en ningun momento)")
    print(f"Base de prueba: {BASE_ENSAYO}   (se crea y se borra)")

    # --- 1. el respaldo a probar ---
    print("\n[1/6] Buscando el respaldo mas reciente...")
    zips = respaldos_disponibles()
    if not zips:
        print("      NO SE ENCONTRO NI UN RESPALDO.")
        print("      Corre RESPALDO_AHORA.bat antes de este ensayo.")
        return 1
    respaldo = zips[0]
    cuando = datetime.fromtimestamp(respaldo.stat().st_mtime)
    edad_h = (datetime.now() - cuando).total_seconds() / 3600
    print(f"      {respaldo}")
    print(f"      Fecha: {cuando:%d/%m/%Y %H:%M}  ({edad_h:.0f} horas de antiguedad)")
    print(f"      Peso : {respaldo.stat().st_size:,} bytes")
    if edad_h > 48:
        print("      *** ATENCION: el respaldo mas nuevo tiene mas de 2 dias. ***")

    with zipfile.ZipFile(respaldo) as z:
        if "db.dump" not in z.namelist():
            print("\n      El respaldo NO trae db.dump adentro. No sirve para restaurar.")
            return 1

    # --- 2. lo que hay hoy ---
    print("\n[2/6] Contando lo que hay hoy en la base real...")
    try:
        vivos = contar(CFG["NAME"])
    except psycopg2.Error as e:
        print(f"      No se pudo leer la base real: {e}")
        return 1
    for etiqueta, _ in TABLAS:
        print(f"      {etiqueta:30} {vivos[etiqueta]}")

    # --- 3. base desechable ---
    print(f"\n[3/6] Creando la base de prueba {BASE_ENSAYO}...")
    try:
        # No se puede crear una base estando conectado a ella: se entra por la
        # base de mantenimiento que PostgreSQL trae siempre.
        admin = conectar("postgres")
        admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    except psycopg2.Error as e:
        print(f"      No se pudo conectar a PostgreSQL: {e}")
        return 1
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(BASE_ENSAYO)))
        print("      Creada.")
    except psycopg2.Error as e:
        print(f"      No se pudo crear la base de prueba: {e}")
        print(f"      El usuario '{CFG.get('USER')}' necesita permiso CREATEDB.")
        admin.close()
        return 1

    codigo = 1
    try:
        # --- 4. restaurar ---
        print("\n[4/6] Restaurando el respaldo dentro de la base de prueba...")
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(respaldo) as z:
                volcado = Path(z.extract("db.dump", tmp))
            print(f"      Volcado: {volcado.stat().st_size:,} bytes")
            try:
                proceso = restaurar_en(BASE_ENSAYO, volcado)
            except FileNotFoundError:
                print("      No se encontro 'pg_restore'. Viene con PostgreSQL.")
                print("      Agrega su carpeta al PATH o define PG_RESTORE_BIN.")
                return 1
            except subprocess.TimeoutExpired:
                print("      pg_restore tardo mas de 30 minutos y se canceló.")
                return 1

        aviso = (proceso.stderr or "").strip()
        if proceso.returncode != 0 and "error" in aviso.lower():
            # Mismo criterio que `manage.py restaurar`: pg_restore devuelve
            # codigo distinto de cero por avisos que no son errores (borrar
            # algo que no existia en una base recien creada, por ejemplo).
            print("\n      FALLO LA RESTAURACION:")
            print("      " + aviso[:2000].replace("\n", "\n      "))
            print("\n      Esto significa que HOY el negocio NO se puede recuperar")
            print("      desde este respaldo. Es lo mas urgente que hay que arreglar.")
            return 1
        if aviso:
            print(f"      pg_restore dejo avisos (normal en una base vacia): {len(aviso.splitlines())} lineas")
        print("      Restaurado.")

        # --- 5. comparar ---
        print("\n[5/6] Contando lo que quedo en la base restaurada...")
        restaurados = contar(BASE_ENSAYO)

        print()
        print(f"      {'':30} {'HOY':>10} {'RESTAURADO':>12}")
        print("      " + "-" * 56)
        todo_bien = True
        for etiqueta, _ in TABLAS:
            hoy = vivos[etiqueta]
            rec = restaurados[etiqueta]
            if rec is None:
                marca = "   <-- LA TABLA NO ESTA"
                todo_bien = False
            elif rec == 0 and (hoy or 0) > 0:
                marca = "   <-- VINO VACIA"
                todo_bien = False
            elif hoy is not None and rec < hoy:
                marca = f"   <-- faltan {hoy - rec}"
            else:
                marca = "   ok"
            print(f"      {etiqueta:30} {str(hoy):>10} {str(rec):>12}{marca}")

        print()
        print("=" * 72)
        if todo_bien:
            print("RESULTADO: EL RESPALDO SIRVE.")
            print()
            print("Se restauro en una base limpia y las tablas del negocio volvieron")
            print("con datos. Si manana esta computadora no prende, el negocio se")
            print("recupera desde este archivo.")
            codigo = 0
        else:
            print("RESULTADO: EL RESPALDO NO VUELVE COMPLETO.")
            print()
            print("Mostrale esta salida a Claude antes de confiar en estos respaldos.")
            codigo = 1
        print("=" * 72)
        print()
        print("Nota: si el respaldo se hizo antes de las ultimas ventas, es normal que")
        print("los numeros restaurados sean un poco menores que los de hoy. Lo que no")
        print("puede pasar es que falte una tabla o que venga vacia.")

    finally:
        # --- 6. limpiar ---
        print(f"\n[6/6] Borrando la base de prueba {BASE_ENSAYO}...")
        try:
            with admin.cursor() as cur:
                # PostgreSQL no deja borrar una base con alguien conectado, y
                # pg_restore pudo dejar una sesion abierta.
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (BASE_ENSAYO,),
                )
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(BASE_ENSAYO)))
            print("      Borrada. La base real quedo intacta.")
        except psycopg2.Error as e:
            print(f"      NO se pudo borrar: {e}")
            print(f"      Borrala a mano con:  DROP DATABASE {BASE_ENSAYO};")
        finally:
            admin.close()

    return codigo


if __name__ == "__main__":
    sys.exit(main())
