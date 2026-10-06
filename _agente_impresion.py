"""Agente de impresión: el puente entre el ERP en la nube y las impresoras.

QUÉ PROBLEMA RESUELVE
    El ERP dejó de correr en la computadora de la tienda: ahora vive en un
    servidor en Nueva York. Ese servidor nunca va a ver el USB del mostrador
    de Heredia, así que no puede imprimir ni el tiquete ni las etiquetas.

    Este programa corre EN la computadora de la tienda, le pregunta al ERP
    cada pocos segundos «¿hay algo para imprimir?» y lo manda a la impresora
    que tiene al lado. Es la pieza que faltaba, y la única que hay que dejar
    encendida en la tienda.

POR QUÉ PREGUNTA EL AGENTE EN VEZ DE QUE EL SERVIDOR LE AVISE
    Porque la computadora de la tienda está detrás del router de un ISP: no
    tiene dirección fija ni puerto abierto, y no debería tenerlos. Que sea
    ella la que llama hacia afuera evita abrirle un agujero a internet.

POR QUÉ ES TONTO A PROPÓSITO
    No sabe qué es un tiquete ni cómo se dibuja una etiqueta: recibe bytes y
    los entrega. Todo el diseño se arma en el servidor. Así, un cambio en la
    etiqueta se sube al ERP y ya: nadie tiene que venir a actualizar este
    programa en la tienda.

CÓMO SE USA
    Lo normal (desde el 27/09/2026): el programa AllPetCR-Impresion.exe, que
    se instala una sola vez por computadora y corre invisible desde que
    arranca Windows (ver _agente_escritorio.py). Este archivo es el motor que
    ese programa lleva adentro.

    Para diagnosticar a mano sigue sirviendo AGENTE_IMPRESION.bat: corre lo
    mismo en una ventana que va contando lo que imprime.
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Callable

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# Empaquetado como .exe, BASE es una carpeta temporal que se borra al cerrar:
# el registro tiene que vivir donde quede instalado, no ahí.
EMPAQUETADO = getattr(sys, "frozen", False)
CARPETA_DATOS = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AllPetCR" / "Impresion"
                 if EMPAQUETADO else BASE)

# La configuración vive aparte, en un archivo que NO se sube a GitHub: el
# repositorio es público y esa llave abre la cola de impresión.
try:
    from _llaves_agente import ERP_URL, TOKEN
except ImportError:
    ERP_URL = TOKEN = ""

SEGUNDOS_ENTRE_CONSULTAS = 3
SEGUNDOS_SI_FALLA_LA_RED = 15
REGISTRO = CARPETA_DATOS / "logs" / "agente_impresion.txt"
# Corriendo meses sin que nadie lo mire, el registro no puede crecer sin fin.
TOPE_REGISTRO_BYTES = 1_000_000


def anotar(mensaje: str, en_pantalla: bool = True) -> None:
    linea = f"{datetime.now():%d/%m/%Y %H:%M:%S}  {mensaje}"
    if en_pantalla:
        print(linea)  # sin consola (el .exe) print no hace nada, y está bien
    try:
        REGISTRO.parent.mkdir(parents=True, exist_ok=True)
        if REGISTRO.exists() and REGISTRO.stat().st_size > TOPE_REGISTRO_BYTES:
            REGISTRO.replace(REGISTRO.with_suffix(".anterior.txt"))
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except Exception:
        pass  # el registro es una comodidad, no una razón para dejar de imprimir


def _contexto_tls() -> ssl.SSLContext:
    """Verificación TLS completa, menos una exigencia nueva de Python 3.13.

    Avast (el antivirus de la tienda) revisa las conexiones seguras poniendo
    su propio certificado raíz en Windows, y ese certificado no marca como
    «crítica» una extensión. Python 3.13 empezó a exigirlo (VERIFY_X509_STRICT)
    y rechaza la conexión: el agente quedaba «sin conexión» para siempre sin
    que el ERP tuviera nada de malo (27/09/2026). Se apaga SOLO esa exigencia;
    la cadena de confianza y el nombre del servidor se siguen verificando."""
    contexto = ssl.create_default_context()
    contexto.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return contexto


_TLS = _contexto_tls()


def _pedir(ruta: str, datos: dict | None = None, metodo: str = "GET"):
    """Una llamada al ERP. Devuelve el JSON, o None si no se pudo."""
    url = ERP_URL.rstrip("/") + ruta
    cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
    pedido = urllib.request.Request(url, data=cuerpo, method=metodo)
    pedido.add_header("X-Agente-Token", TOKEN)
    if cuerpo:
        pedido.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(pedido, timeout=30, context=_TLS) as r:
        return json.loads(r.read().decode("utf-8"))


def imprimir(trabajo: dict) -> tuple[bool, str, bool]:
    """Manda un trabajo a la impresora.

    Devuelve (salió bien, detalle, devolver). `devolver` es True cuando la
    impresora no está conectada a ESTA computadora: el trabajo no falló, le
    tocó a la máquina equivocada, y vuelve a la cola para la otra."""
    from impresion import windows

    contenido = base64.b64decode(trabajo["contenido_b64"])
    titulo = trabajo.get("titulo") or "ALLPETCR"
    try:
        if trabajo["formato"] == "crudo":
            windows.enviar_crudo(trabajo["impresora"], contenido, titulo=titulo)
        else:
            from PIL import Image
            imagen = Image.open(BytesIO(contenido))
            windows.imprimir_imagen(
                trabajo["impresora"], imagen,
                float(trabajo["ancho_mm"]), float(trabajo["alto_mm"]),
                titulo=titulo,
            )
        return True, "", False
    except windows.ImpresoraNoDisponible as e:
        return False, str(e), True
    except windows.ErrorDeImpresion as e:
        return False, str(e), False
    except Exception as e:  # pragma: no cover - depende del hardware
        return False, f"{type(e).__name__}: {e}", False


def impresoras_de_esta_maquina() -> list:
    """Las impresoras CONECTADAS a esta computadora ahora mismo.

    Se le mandan al ERP en cada consulta para que solo le dé los trabajos que
    esta máquina puede imprimir de verdad. Sin esto, el agente abierto en la
    casa de Oscar se llevaría el tiquete de una venta hecha en la tienda y el
    cliente se quedaría sin comprobante (ver cola.tomar_pendientes).

    Conectadas, no instaladas (06/10/2026): en la tienda las dos computadoras
    tienen las colas instaladas y el cable va a una u otra según el horario.
    Con la lista de instaladas, la que no tenía el cable se llevaba el trabajo
    y fallaba (ver windows.impresoras_conectadas)."""
    from impresion import windows

    try:
        return windows.impresoras_conectadas()
    except Exception:
        return []


@dataclass
class Estado:
    """Lo que el agente sabe de sí mismo, para mostrarlo sin ventana (el
    iconito junto al reloj). La consola no lo necesita: ya lo va imprimiendo."""
    conectado: bool = False
    impresoras: list = field(default_factory=list)
    impresos_hoy: int = 0
    dia: date = field(default_factory=date.today)
    ultimo_error: str = ""

    def contar(self, ok: bool) -> None:
        if self.dia != date.today():
            self.dia, self.impresos_hoy = date.today(), 0
        if ok:
            self.impresos_hoy += 1

    def resumen(self) -> str:
        if not self.conectado:
            return "Sin conexión con el ERP (reintentando)"
        if not self.impresoras:
            return "Conectado, pero esta computadora no tiene impresoras"
        return f"Conectado · {self.impresos_hoy} impresos hoy"


# Quién se entera de cada trabajo: (salió bien, título, detalle del error).
AlImprimir = Callable[[bool, str, str], None]


def una_vuelta(estado: Estado | None = None, al_imprimir: AlImprimir | None = None) -> int:
    """Pide trabajos, los imprime y reporta. Devuelve cuántos imprimió."""
    impresoras = impresoras_de_esta_maquina()
    if estado is not None:
        estado.impresoras = impresoras
    respuesta = _pedir(
        "/impresion/agente/pendientes/?cuantos=5&impresoras="
        + urllib.parse.quote(",".join(impresoras))
    )
    trabajos = respuesta.get("trabajos", []) if respuesta else []
    for t in trabajos:
        ok, detalle, devolver = imprimir(t)
        etiqueta = t.get("titulo") or t.get("tipo")
        if devolver:
            # La impresora se desenchufó entre la consulta y la impresión (o
            # Windows tardó en marcarla). No es un error para esta máquina:
            # sin aviso en pantalla y de vuelta a la cola para la otra.
            anotar(f"↩ {etiqueta} — devuelto a la cola: {detalle}")
        else:
            anotar(f"{'✅' if ok else '⛔'} {etiqueta}" + (f" — {detalle}" if detalle else ""))
            if estado is not None:
                estado.contar(ok)
            if al_imprimir:
                al_imprimir(ok, etiqueta, detalle)
        try:
            _pedir("/impresion/agente/resultado/",
                   {"id": t["id"], "ok": ok, "detalle": detalle, "devolver": devolver},
                   metodo="POST")
        except Exception as e:
            # Si no se pudo avisar, el trabajo queda «tomado» y vence solo.
            # Peor sería reintentar e imprimirlo dos veces.
            anotar(f"   (no se pudo avisarle al ERP: {e})")
    return len(trabajos)


class LlaveRechazada(Exception):
    """El ERP dice que la llave no sirve. Reintentar no lo arregla."""


def comprobar_arranque() -> list:
    """Anota qué impresoras ve y si el ERP acepta la llave.

    Es mejor enterarse al arrancar de que la llave está mal que descubrirlo
    con un cliente esperando el tiquete. Devuelve las impresoras vistas."""
    vistas = impresoras_de_esta_maquina()
    if vistas:
        anotar("Impresoras conectadas a esta computadora: " + ", ".join(vistas))
    else:
        anotar("⚠ Esta computadora no tiene ninguna impresora conectada ahora. "
               "El agente igual se conecta y empieza a recibir trabajos apenas "
               "se enchufe una.")
    try:
        _pedir("/impresion/agente/pendientes/?cuantos=1&impresoras=")
        anotar("Conectado al ERP. Esperando trabajos…")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            anotar("⛔ El ERP rechazó la llave. Avisale a Claude.")
            raise LlaveRechazada from e
        anotar(f"⛔ El ERP respondió {e.code}. Se sigue intentando…")
    except Exception as e:
        anotar(f"Sin conexión con el ERP ({e}). Se sigue intentando…")
    return vistas


def _dormir(segundos: float) -> bool:
    time.sleep(segundos)
    return False


def atender(esperar: Callable[[float], bool] = _dormir, estado: Estado | None = None,
            al_imprimir: AlImprimir | None = None,
            al_cambiar: Callable[[], None] | None = None) -> None:
    """El ciclo de siempre: preguntar, imprimir, esperar. Hasta que `esperar`
    devuelva True (el programa de escritorio lo usa para cerrarse limpio al
    actualizarse; la consola nunca lo pide y se corta con Ctrl+C)."""
    estado = estado or Estado()
    antes = None
    while True:
        try:
            una_vuelta(estado, al_imprimir)
            if not estado.conectado and antes is not None:
                anotar("Conexión recuperada.")
            estado.conectado, estado.ultimo_error = True, ""
            pausa = SEGUNDOS_ENTRE_CONSULTAS
        except Exception as e:
            # Cualquier problema de red o del ERP: se anota UNA vez y se sigue
            # esperando. Este programa no se puede caer: si se cae, la tienda
            # deja de imprimir y nadie se entera hasta que un cliente reclama.
            if estado.conectado or antes is None:
                anotar(f"Sin conexión con el ERP ({e}). Reintentando…")
            estado.conectado, estado.ultimo_error = False, str(e)
            pausa = SEGUNDOS_SI_FALLA_LA_RED
        if al_cambiar and estado.resumen() != antes:
            al_cambiar()
        antes = estado.resumen()
        if esperar(pausa):
            anotar("Agente detenido.")
            return


def main():
    print()
    print("=" * 66)
    print("  AGENTE DE IMPRESIÓN — ALLPETCR")
    print("=" * 66)
    print()

    if not ERP_URL or not TOKEN:
        print("  Falta el archivo _llaves_agente.py con la dirección del ERP")
        print("  y la llave. Avisale a Claude.")
        print()
        input("  Presioná Enter para cerrar.")
        return

    print(f"  ERP: {ERP_URL}")
    print()
    print("  Dejá esta ventana abierta mientras la tienda esté abierta.")
    print("  Acá se va anotando cada tiquete y cada etiqueta que sale.")
    print("  Para detenerlo: cerrá la ventana.")
    print()
    print("-" * 66)

    try:
        comprobar_arranque()
    except LlaveRechazada:
        input("  Presioná Enter para cerrar.")
        return
    try:
        atender()
    except KeyboardInterrupt:
        anotar("Agente detenido a mano.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
