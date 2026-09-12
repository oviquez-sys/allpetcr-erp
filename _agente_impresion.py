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
    Doble clic en AGENTE_IMPRESION.bat. Se deja abierto todo el día.
    La ventana va contando lo que imprime; si se cierra, deja de imprimirse
    (las ventas y el inventario siguen funcionando igual).
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# La configuración vive aparte, en un archivo que NO se sube a GitHub: el
# repositorio es público y esa llave abre la cola de impresión.
try:
    from _llaves_agente import ERP_URL, TOKEN
except ImportError:
    ERP_URL = TOKEN = ""

SEGUNDOS_ENTRE_CONSULTAS = 3
SEGUNDOS_SI_FALLA_LA_RED = 15
REGISTRO = BASE / "logs" / "agente_impresion.txt"


def anotar(mensaje: str, en_pantalla: bool = True) -> None:
    linea = f"{datetime.now():%d/%m/%Y %H:%M:%S}  {mensaje}"
    if en_pantalla:
        print(linea)
    try:
        REGISTRO.parent.mkdir(exist_ok=True)
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except Exception:
        pass  # el registro es una comodidad, no una razón para dejar de imprimir


def _pedir(ruta: str, datos: dict | None = None, metodo: str = "GET"):
    """Una llamada al ERP. Devuelve el JSON, o None si no se pudo."""
    url = ERP_URL.rstrip("/") + ruta
    cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
    pedido = urllib.request.Request(url, data=cuerpo, method=metodo)
    pedido.add_header("X-Agente-Token", TOKEN)
    if cuerpo:
        pedido.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(pedido, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def imprimir(trabajo: dict) -> tuple[bool, str]:
    """Manda un trabajo a la impresora. Devuelve (salió bien, detalle)."""
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
        return True, ""
    except windows.ErrorDeImpresion as e:
        return False, str(e)
    except Exception as e:  # pragma: no cover - depende del hardware
        return False, f"{type(e).__name__}: {e}"


def impresoras_de_esta_maquina() -> list:
    """Las colas que esta computadora tiene instaladas ahora mismo.

    Se le mandan al ERP en cada consulta para que solo le dé los trabajos que
    esta máquina puede imprimir de verdad. Sin esto, el agente abierto en la
    casa de Oscar se llevaría el tiquete de una venta hecha en la tienda y el
    cliente se quedaría sin comprobante (ver cola.tomar_pendientes)."""
    from impresion import windows

    try:
        return windows.listar_impresoras()
    except Exception:
        return []


def una_vuelta() -> int:
    """Pide trabajos, los imprime y reporta. Devuelve cuántos imprimió."""
    lista = ",".join(impresoras_de_esta_maquina())
    respuesta = _pedir(
        "/impresion/agente/pendientes/?cuantos=5&impresoras="
        + urllib.parse.quote(lista)
    )
    trabajos = respuesta.get("trabajos", []) if respuesta else []
    for t in trabajos:
        ok, detalle = imprimir(t)
        etiqueta = t.get("titulo") or t.get("tipo")
        anotar(f"{'✅' if ok else '⛔'} {etiqueta}" + (f" — {detalle}" if detalle else ""))
        try:
            _pedir("/impresion/agente/resultado/",
                   {"id": t["id"], "ok": ok, "detalle": detalle}, metodo="POST")
        except Exception as e:
            # Si no se pudo avisar, el trabajo queda «tomado» y vence solo.
            # Peor sería reintentar e imprimirlo dos veces.
            anotar(f"   (no se pudo avisarle al ERP: {e})")
    return len(trabajos)


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

    # Comprobación de arranque: es mejor enterarse acá de que la llave está
    # mal que descubrirlo con un cliente esperando el tiquete.
    vistas = impresoras_de_esta_maquina()
    if vistas:
        anotar("Impresoras que veo en esta computadora: " + ", ".join(vistas))
    else:
        anotar("⚠ Esta computadora no tiene ninguna impresora instalada. "
               "El agente igual se conecta, pero no va a recibir trabajos.")

    try:
        _pedir("/impresion/agente/pendientes/?cuantos=1&impresoras=")
        anotar("Conectado al ERP. Esperando trabajos…")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            anotar("⛔ El ERP rechazó la llave. Avisale a Claude.")
            input("  Presioná Enter para cerrar.")
            return
        anotar(f"⛔ El ERP respondió {e.code}. Se sigue intentando…")
    except Exception as e:
        anotar(f"Sin conexión con el ERP ({e}). Se sigue intentando…")

    sin_red = False
    while True:
        try:
            una_vuelta()
            if sin_red:
                anotar("Conexión recuperada.")
                sin_red = False
            time.sleep(SEGUNDOS_ENTRE_CONSULTAS)
        except KeyboardInterrupt:
            anotar("Agente detenido a mano.")
            return
        except Exception as e:
            # Cualquier problema de red o del ERP: se anota UNA vez y se sigue
            # esperando. Este programa no se puede caer: si se cae, la tienda
            # deja de imprimir y nadie se entera hasta que un cliente reclama.
            if not sin_red:
                anotar(f"Sin conexión con el ERP ({e}). Reintentando…")
                sin_red = True
            time.sleep(SEGUNDOS_SI_FALLA_LA_RED)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
