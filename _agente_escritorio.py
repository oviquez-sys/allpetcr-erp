"""El agente de impresión como programa de Windows: se instala una vez y se olvida.

QUÉ PROBLEMA RESUELVE (27/09/2026)
    Con AGENTE_IMPRESION.bat había que acordarse de abrirlo cada mañana, dejar
    una ventana negra abierta todo el día y tener la carpeta entera del ERP
    con Python instalada en cada computadora. Si alguien cerraba la ventana,
    dejaba de salir papel y nadie se enteraba hasta que un cliente reclamaba.

QUÉ HACE
    Es un solo archivo, AllPetCR-Impresion.exe, que lleva adentro Python, el
    motor del agente (_agente_impresion.py) y la llave del ERP.

    - Doble clic desde cualquier lado  → se instala en esta computadora
      (%LOCALAPPDATA%\\AllPetCR\\Impresion), queda anotado para arrancar con
      Windows y empieza a trabajar. No pide permisos de administrador.
    - Corriendo desde donde se instaló → trabaja sin ventana. Solo se ve un
      iconito junto al reloj: al pasarle el mouse dice si está conectado, y
      si un tiquete no sale avisa con una notificación de Windows.
    - Si ya estaba instalado, instalar de nuevo lo actualiza: cierra el viejo,
      pone el nuevo y lo arranca.

POR QUÉ VA EN CADA COMPUTADORA CON IMPRESORA
    El servidor no ve el USB de nadie. Cada máquina le dice al ERP qué
    impresoras tiene y el ERP solo le da lo suyo (cola.tomar_pendientes), así
    que instalarlo en una computadora sin impresoras no roba trabajos.

POR QUÉ DOS MANERAS DE ARRANCAR
    La entrada «Run» de Windows lo arranca al iniciar sesión, al instante. La
    tarea programada lo vuelve a lanzar cada 10 minutos por si algo lo cerró:
    si ya está corriendo, la copia nueva lo nota (mutex) y se va sola.

NO SE SUBE A GITHUB EL .EXE: lleva la llave del ERP adentro. Se construye con
CONSTRUIR_AGENTE_IMPRESION.bat y queda en la carpeta INSTALADORES, fuera del
repositorio.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import _agente_impresion as motor

NOMBRE = "AllPetCR-Impresion"
TITULO = "AllPetCR · Impresión"
CARPETA_INSTALACION = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AllPetCR" / "Impresion"
EJECUTABLE_INSTALADO = CARPETA_INSTALACION / f"{NOMBRE}.exe"
CLAVE_ARRANQUE = r"Software\Microsoft\Windows\CurrentVersion\Run"
TAREA = "AllPetCR - Agente de impresion"
MINUTOS_ENTRE_REVISIONES = 10
# «Local\» = uno por sesión de Windows. Si dos personas usan la misma
# computadora con usuarios distintos, cada una tiene el suyo, como la cola.
MUTEX = "Local\\AllPetCR-AgenteImpresion"
EVENTO_SALIR = "Local\\AllPetCR-AgenteImpresion-Salir"
LOGO = Path(getattr(sys, "_MEIPASS", motor.BASE)) / "impresion" / "marca" / "logo_marca.png"

_SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW: que schtasks no parpadee una consola
_YA_EXISTE = 183           # ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------- avisos ---

def mensaje(texto: str, error: bool = False, pregunta: bool = False) -> bool:
    """Cuadro de Windows. Encima de todo: sin él, el cuadro puede quedar
    detrás de otra ventana y parecer que el programa no hizo nada."""
    icono = 0x10 if error else (0x20 if pregunta else 0x40)
    botones = 0x4 if pregunta else 0x0  # Sí/No o Aceptar
    r = ctypes.windll.user32.MessageBoxW(0, texto, TITULO, icono | botones | 0x40000)
    return r == 6  # IDYES


def _es_la_copia_instalada() -> bool:
    return os.path.normcase(Path(sys.executable).resolve()) == os.path.normcase(EJECUTABLE_INSTALADO.resolve())


# -------------------------------------------------- una sola copia a la vez ---

def tomar_turno():
    """Devuelve el mutex si esta es la única copia corriendo, o None si ya hay otra."""
    import win32api
    import win32event

    mutex = win32event.CreateMutex(None, True, MUTEX)
    if win32api.GetLastError() == _YA_EXISTE:
        return None
    return mutex


def cerrar_copia_corriendo(segundos: int = 20) -> None:
    """Le pide a la copia que esté corriendo que se cierre y espera a que lo haga.

    Hace falta para actualizar: Windows no deja reemplazar un .exe abierto."""
    import win32event

    evento = win32event.CreateEvent(None, True, False, EVENTO_SALIR)
    win32event.SetEvent(evento)
    mutex = win32event.CreateMutex(None, False, MUTEX)
    if win32event.WaitForSingleObject(mutex, segundos * 1000) in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
        win32event.ReleaseMutex(mutex)
    # Si no se apaga el evento, la copia nueva lo encontraría encendido y se
    # cerraría apenas arranca.
    win32event.ResetEvent(evento)


# ------------------------------------------------------- arranque automático ---

def xml_tarea(ejecutable: Path) -> str:
    """La tarea que relanza el agente si algo lo cerró.

    Se arma en XML y no con `schtasks /SC MINUTE` porque por defecto Windows
    le pone tres condiciones que acá son dañinas: no arrancar con batería (la
    laptop del mostrador), matar la tarea a las 72 horas (el agente vive días)
    y encolar otra copia si la anterior sigue viva."""
    inicio = datetime.now().replace(second=0, microsecond=0).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Relanza el agente de impresión de AllPetCR si se cerró.</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{inicio}</StartBoundary>
      <Repetition><Interval>PT{MINUTOS_ENTRE_REVISIONES}M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="Autor"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Autor"><Exec><Command>"{ejecutable}"</Command></Exec></Actions>
</Task>"""


def registrar_arranque(ejecutable: Path) -> bool:
    """Deja el agente arrancando solo. Devuelve False si la tarea de respaldo
    no se pudo crear (el arranque con Windows igual queda)."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_ARRANQUE, 0, winreg.KEY_SET_VALUE) as clave:
        winreg.SetValueEx(clave, NOMBRE, 0, winreg.REG_SZ, f'"{ejecutable}"')

    ruta_xml = Path(tempfile.gettempdir()) / f"{NOMBRE}-tarea.xml"
    ruta_xml.write_text(xml_tarea(ejecutable), encoding="utf-16")
    try:
        r = subprocess.run(["schtasks", "/Create", "/TN", TAREA, "/XML", str(ruta_xml), "/F"],
                           capture_output=True, text=True, creationflags=_SIN_VENTANA)
    finally:
        ruta_xml.unlink(missing_ok=True)
    if r.returncode != 0:
        motor.anotar(f"No se pudo crear la tarea de respaldo: {(r.stderr or r.stdout).strip()}", en_pantalla=False)
    return r.returncode == 0


def quitar_arranque() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_ARRANQUE, 0, winreg.KEY_SET_VALUE) as clave:
            winreg.DeleteValue(clave, NOMBRE)
    except FileNotFoundError:
        pass
    subprocess.run(["schtasks", "/Delete", "/TN", TAREA, "/F"], capture_output=True, creationflags=_SIN_VENTANA)


def lanzar(ejecutable: Path) -> None:
    # Sin esta variable, el .exe nuevo heredaría la carpeta temporal de este y
    # se rompería cuando este se cierre y la borre.
    entorno = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen([str(ejecutable)], env=entorno, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | _SIN_VENTANA)


# ------------------------------------------------------ instalar / quitar ---

def _con_paciencia(accion, segundos: int = 15) -> bool:
    """Reintenta una operación sobre el .exe instalado hasta que Windows lo suelte.

    El agente se cierra al instante, pero el envoltorio de PyInstaller que lo
    lanzó tarda unos segundos más en irse y mientras tanto el archivo sigue
    bloqueado (pasó al probar la desinstalación el 27/09/2026)."""
    for _ in range(segundos * 2):
        try:
            accion()
            return True
        except PermissionError:
            time.sleep(0.5)
    return False


def instalar(silencioso: bool = False) -> int:
    if not motor.EMPAQUETADO:
        # Sin empaquetar, sys.executable es python.exe: instalaría Python pelado.
        print("Instalar solo tiene sentido desde el .exe (CONSTRUIR_AGENTE_IMPRESION.bat).")
        return 1
    if not motor.ERP_URL or not motor.TOKEN:
        mensaje("Este instalador se armó sin la llave del ERP. Avisale a Claude.", error=True)
        return 1
    cerrar_copia_corriendo()
    CARPETA_INSTALACION.mkdir(parents=True, exist_ok=True)
    if not _con_paciencia(lambda: shutil.copy2(sys.executable, EJECUTABLE_INSTALADO)):
        mensaje("No pude reemplazar la versión anterior (sigue abierta).\n"
                "Reiniciá la computadora y volvé a abrir este archivo.", error=True)
        return 1
    tarea_ok = registrar_arranque(EJECUTABLE_INSTALADO)
    lanzar(EJECUTABLE_INSTALADO)
    motor.anotar(f"Instalado en {EJECUTABLE_INSTALADO}", en_pantalla=False)

    if not silencioso:
        impresoras = motor.impresoras_de_esta_maquina()
        lista = ("\n".join(f"   • {i}" for i in impresoras)
                 or "   (ninguna conectada ahora: va a imprimir apenas se le enchufe una)")
        mensaje("Listo. La impresión quedó instalada en esta computadora.\n\n"
                "Arranca sola cada vez que se enciende Windows: no hay que abrir nada.\n"
                "Vas a ver el logo de AllPet junto al reloj; al pasarle el mouse\n"
                "te dice si está conectado.\n\n"
                f"Impresoras conectadas ahora:\n{lista}"
                + ("" if tarea_ok else "\n\n(Nota: no se pudo crear el reinicio automático cada "
                   f"{MINUTOS_ENTRE_REVISIONES} min; el arranque con Windows sí quedó.)"))
    return 0


def desinstalar(silencioso: bool = False) -> bool:
    """Devuelve True si se quitó (False si el usuario se arrepintió)."""
    if not silencioso and not mensaje("¿Quitar la impresión de AllPetCR de esta computadora?\n\n"
                                      "Desde esta computadora dejarán de salir tiquetes y etiquetas.",
                                      pregunta=True):
        return False
    quitar_arranque()
    if _es_la_copia_instalada():
        # Un programa no puede borrarse a sí mismo mientras corre: lo borra
        # una consola invisible unos segundos después de que este se cierre.
        subprocess.Popen(f'cmd /c ping -n 6 127.0.0.1 >nul & del /q "{EJECUTABLE_INSTALADO}"',
                         creationflags=_SIN_VENTANA | subprocess.DETACHED_PROCESS)
    else:
        cerrar_copia_corriendo()
        _con_paciencia(lambda: EJECUTABLE_INSTALADO.unlink(missing_ok=True))
    motor.anotar("Desinstalado de esta computadora.", en_pantalla=False)
    if not silencioso:
        mensaje("Listo. La impresión de AllPetCR se quitó de esta computadora.")
    return True


# --------------------------------------------------------- trabajar en fondo ---

def dibujar_icono(conectado: bool):
    """El logo de AllPet en blanco sobre el azul de la marca, con un punto
    verde (todo bien) o naranja (sin conexión). Se dibuja al vuelo para no
    cargar con dos archivos de icono."""
    from PIL import Image, ImageDraw, ImageOps

    lado = 64
    icono = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(icono)
    d.rounded_rectangle((0, 0, lado - 1, lado - 1), radius=14, fill=(9, 46, 94, 255))
    try:
        forma = Image.open(LOGO).convert("L")
        forma = ImageOps.invert(forma).point(lambda v: 255 if v > 128 else 0)
        forma.thumbnail((44, 44), Image.LANCZOS)
        blanco = Image.new("RGBA", forma.size, (255, 255, 255, 255))
        icono.paste(blanco, ((lado - forma.width) // 2, (lado - forma.height) // 2), forma)
    except OSError:
        pass  # sin logo queda el cuadro azul con el punto: sigue sirviendo
    color = (46, 204, 113, 255) if conectado else (243, 156, 18, 255)
    d.ellipse((40, 40, 62, 62), fill=color, outline=(255, 255, 255, 255), width=3)
    return icono


def trabajar() -> int:
    turno = tomar_turno()
    if turno is None:
        return 0  # ya hay una copia trabajando (típico: la revisión cada 10 min)
    if not motor.ERP_URL or not motor.TOKEN:
        mensaje("A este programa le falta la llave del ERP. Avisale a Claude.", error=True)
        return 1
    try:
        motor.comprobar_arranque()
    except motor.LlaveRechazada:
        mensaje("El ERP rechazó la llave de impresión.\nDesde esta computadora no va a salir papel. "
                "Avisale a Claude.", error=True)
        return 1

    import win32event

    evento = win32event.CreateEvent(None, True, False, EVENTO_SALIR)

    def esperar(segundos: float) -> bool:
        return win32event.WaitForSingleObject(evento, int(segundos * 1000)) == win32event.WAIT_OBJECT_0

    estado = motor.Estado()
    try:
        import pystray
    except ImportError:  # sin bandeja igual imprime: eso es lo que importa
        motor.atender(esperar, estado)
        return 0

    icono = pystray.Icon(NOMBRE, dibujar_icono(False), TITULO)

    def refrescar():
        icono.icon = dibujar_icono(estado.conectado)
        icono.title = f"{TITULO}\n{estado.resumen()}"[:127]  # Windows corta a 127
        icono.update_menu()

    def al_imprimir(ok: bool, titulo: str, detalle: str):
        refrescar()
        if not ok:
            icono.notify(detalle or "Revisá la impresora.", f"No salió: {titulo}"[:63])

    def impresoras_texto(_):
        return "Impresoras: " + (", ".join(estado.impresoras) or "ninguna")

    def quitar():
        if desinstalar():
            win32event.SetEvent(evento)  # el ciclo termina y el icono se va

    icono.menu = pystray.Menu(
        pystray.MenuItem(lambda _: estado.resumen(), None, enabled=False),
        pystray.MenuItem(impresoras_texto, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Ver registro de impresiones", lambda: os.startfile(motor.REGISTRO)),
        pystray.MenuItem("Quitar de esta computadora…", quitar),
    )

    def ciclo():
        motor.atender(esperar, estado, al_imprimir, refrescar)
        icono.stop()

    def al_arrancar(i):
        i.visible = True
        threading.Thread(target=ciclo, daemon=True).start()

    icono.run(setup=al_arrancar)
    return 0


def main() -> int:
    argumentos = {a.lower() for a in sys.argv[1:]}
    silencioso = "--silencioso" in argumentos
    if "--desinstalar" in argumentos:
        desinstalar(silencioso)
        return 0
    if "--instalar" in argumentos or (motor.EMPAQUETADO and not _es_la_copia_instalada()):
        return instalar(silencioso)
    return trabajar()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # sin consola, un error sin atrapar desaparecería en silencio
        motor.anotar(f"⛔ Error inesperado: {type(e).__name__}: {e}", en_pantalla=False)
        mensaje(f"El agente de impresión tuvo un error:\n{e}\n\nAvisale a Claude.", error=True)
        sys.exit(1)
