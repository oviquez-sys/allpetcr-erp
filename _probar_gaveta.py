"""Prueba de la gaveta de dinero (19/10/2026).

La gaveta Dynapos no se conecta a la computadora: su cable RJ11 ("de
teléfono") va al puerto de la impresora de recibos marcado DK / CASH DRAWER.
La gaveta no tiene electrónica propia: es un electroimán. La impresora le da
un pulso cuando recibe el comando ESC/POS `ESC p` (1B 70 m t1 t2), y por eso
Windows no la "ve" ni la puede detectar: lo único que se puede probar es
mandarle el pulso y ver si abre.

Hay dos patillas posibles en el conector (2 y 5) según la marca de la gaveta.
Esta prueba manda primero la patilla 2 y pregunta; si no abrió, la 5. La
respuesta queda en resultado_gaveta.txt para configurar el ERP con la que sirve.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from impresion import windows  # noqa: E402

IMPRESORA = os.environ.get("IMPRESORA_RECIBOS", "Caysn 80mm")
PULSOS = {
    "2": b"\x1b\x70\x00\x19\xfa",   # ESC p 0 25 250: patilla 2, 50 ms encendido
    "5": b"\x1b\x70\x01\x19\xfa",   # ESC p 1 25 250: patilla 5
}


def main():
    print("Impresoras conectadas:", ", ".join(windows.impresoras_conectadas()) or "ninguna")
    try:
        nombre = windows.resolver(IMPRESORA)
    except Exception as e:  # noqa: BLE001 - se informa tal cual al usuario
        print("NO SE ENCONTRÓ LA IMPRESORA DE RECIBOS:", e)
        return
    print("Impresora de recibos:", nombre)
    for patilla, datos in PULSOS.items():
        print(f"\nMandando el pulso por la patilla {patilla}...")
        try:
            windows.enviar_crudo(nombre, datos, titulo="Prueba gaveta")
        except Exception as e:  # noqa: BLE001
            print("ERROR al mandar el pulso:", e)
            return
        time.sleep(1.5)
        r = input("¿Se abrió la gaveta? Escriba S o N y Enter: ").strip().upper()
        print("Respuesta:", r)
        if r.startswith("S"):
            print(f"\nRESULTADO: la gaveta abre con la patilla {patilla}.")
            return
        input("Cierre la gaveta si hace falta y dé Enter para probar la otra patilla...")
    print("\nRESULTADO: la gaveta NO abrió con ninguna patilla. Revise el cable (va en la impresora, puerto DK).")


class _Doble:
    """Escribe en pantalla y en el archivo a la vez."""
    def __init__(self, *salidas):
        self.salidas = salidas

    def write(self, texto):
        for s in self.salidas:
            s.write(texto)
            s.flush()

    def flush(self):
        for s in self.salidas:
            s.flush()


if __name__ == "__main__":
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultado_gaveta.txt"),
              "w", encoding="utf-8") as log:
        sys.stdout = _Doble(sys.__stdout__, log)
        main()
