"""Arma AllPetCR-Impresion.exe, el instalador del agente de impresión (27/09/2026).

Lo deja en la carpeta AllPet\\INSTALADORES, FUERA del repositorio: el .exe
lleva adentro la llave del ERP (_llaves_agente.py) y el repositorio es público.

Hace falta volver a armarlo solo si cambia la llave, la dirección del ERP o el
código del agente. El diseño del tiquete y de la etiqueta vive en el servidor:
cambiarlo NO obliga a reinstalar nada en las computadoras.

Se ejecuta con CONSTRUIR_AGENTE_IMPRESION.bat (doble clic).
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
TRABAJO = BASE / "build" / "agente"
DESTINO = BASE.parents[1] / "INSTALADORES"


def fallar(texto: str) -> None:
    print(f"\n  ⛔ {texto}\n")
    sys.exit(1)


def main() -> None:
    sys.path.insert(0, str(BASE))
    try:
        from _llaves_agente import ERP_URL, TOKEN
    except ImportError:
        fallar("Falta _llaves_agente.py: sin la llave, el programa no podría hablar con el ERP.")
    if not ERP_URL or not TOKEN:
        fallar("_llaves_agente.py está incompleto (ERP_URL y TOKEN).")

    TRABAJO.mkdir(parents=True, exist_ok=True)
    from _agente_escritorio import dibujar_icono
    icono = TRABAJO / "agente.ico"
    dibujar_icono(True).save(icono, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])

    orden = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
        "--name", "AllPetCR-Impresion", "--icon", str(icono),
        "--distpath", str(DESTINO), "--workpath", str(TRABAJO), "--specpath", str(TRABAJO),
        "--add-data", f"{BASE / 'impresion' / 'marca' / 'logo_marca.png'};impresion/marca",
        # pywin32 y la bandeja se importan adentro de funciones o se eligen al
        # correr: PyInstaller no siempre los ve solo.
        "--hidden-import", "win32print", "--hidden-import", "win32ui", "--hidden-import", "win32gui",
        "--hidden-import", "pystray._win32", "--hidden-import", "_llaves_agente",
        # El agente no usa Django: sin esto el .exe cargaría con el ERP entero.
        "--exclude-module", "django", "--exclude-module", "rest_framework",
        str(BASE / "_agente_escritorio.py"),
    ]
    print("  Armando el programa (tarda un par de minutos)...")
    if subprocess.run(orden, cwd=BASE).returncode != 0:
        fallar("PyInstaller falló. El mensaje de arriba dice por qué.")
    print(f"\n  ✅ Listo: {DESTINO / 'AllPetCR-Impresion.exe'}\n")


if __name__ == "__main__":
    main()
