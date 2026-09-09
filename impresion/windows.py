"""Capa que habla con las impresoras de Windows.

Es el ÚNICO archivo del proyecto que importa pywin32. Todo lo demás trabaja
con bytes o con imágenes y no sabe si detrás hay Windows, un PDF o nada.

El porqué de ese aislamiento: hoy el ERP corre en la misma máquina que las
impresoras (ver CLAUDE.md), así que imprimir desde el servidor funciona. El
día que el ERP se mude a un VPS —está decidido, DigitalOcean— el servidor ya
no verá el USB de la tienda y habrá que poner un agente en la caja. Ese día
se reemplaza este archivo por un cliente del agente y el tiquete, la etiqueta
y las vistas siguen igual.

Dos caminos de impresión, y no son intercambiables:

- `enviar_crudo`: los bytes van tal cual a la impresora, sin pasar por el
  driver. Es lo correcto para la térmica de recibos, que entiende ESC/POS y
  corta el papel sola.
- `imprimir_imagen`: dibuja un mapa de bits a través del driver de Windows.
  Es lo correcto para la Xprinter XP-360B: se comprobó el 05/09/2026 que
  esa impresora IGNORA los comandos crudos (TSPL, ZPL y EPL: no imprimió
  ninguno) y en cambio imprime perfecto por el driver. No volver a intentar
  el camino crudo con ella.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Tamaño de papel definido por el usuario en la API de Windows (DMPAPER_USER).
# Es lo que permite pedirle a la impresora una etiqueta de 44,5 × 31,8 mm, que
# no corresponde a ningún tamaño estándar de la lista de Windows.
_PAPEL_DEFINIDO_POR_USUARIO = 256

# Banderas de DEVMODE que hay que encender para que Windows respete el tamaño
# que le pasamos en vez de usar el de fábrica del driver.
_DM_PAPERSIZE = 0x00000002
_DM_PAPERLENGTH = 0x00000004
_DM_PAPERWIDTH = 0x00000008

# Índices de GetDeviceCaps: ancho y alto imprimibles en píxeles.
_HORZRES = 8
_VERTRES = 10

# Bit de "usar impresora sin conexión" en los atributos de la cola.
_SIN_CONEXION = 0x400


class ErrorDeImpresion(Exception):
    """Falla al imprimir. Lleva un mensaje entendible por el personal de la
    tienda, no una traza técnica: quien lo lee está con un cliente enfrente."""


def _pywin32():
    """Importa pywin32 en el momento de usarlo, no al arrancar Django.

    Si se importara arriba, el ERP no levantaría en una máquina sin pywin32
    (por ejemplo, el servidor de pruebas o un Linux). Prefiero que arranque
    y que solo falle —con un mensaje claro— quien intente imprimir."""
    try:
        import win32gui  # noqa: F401
        import win32print
        import win32ui  # noqa: F401
        return win32print
    except ImportError as e:  # pragma: no cover - depende del sistema
        raise ErrorDeImpresion(
            "Falta el componente de impresión de Windows (pywin32). "
            "Ejecutá INSTALAR_IMPRESION.bat en la carpeta del ERP."
        ) from e


def disponible() -> bool:
    """True si esta máquina puede imprimir (Windows con pywin32)."""
    try:
        _pywin32()
        return True
    except ErrorDeImpresion:
        return False


def listar_impresoras() -> list[str]:
    """Nombres de las impresoras instaladas, tal como los ve Windows."""
    win32print = _pywin32()
    nivel = 2  # PRINTER_ENUM_LOCAL
    conexiones = 4  # PRINTER_ENUM_CONNECTIONS
    return [i[2] for i in win32print.EnumPrinters(nivel | conexiones)]


def existe(nombre: str) -> bool:
    try:
        return nombre in listar_impresoras()
    except ErrorDeImpresion:
        return False


def sin_conexion(nombre: str) -> bool:
    """True si Windows tiene esa cola marcada «usar impresora sin conexión».

    Una cola así acepta los trabajos, los guarda y no los manda nunca: desde
    afuera parece que se imprimió y no sale nada."""
    win32print = _pywin32()
    manejador = win32print.OpenPrinter(nombre)
    try:
        return bool(win32print.GetPrinter(manejador, 2)["Attributes"] & _SIN_CONEXION)
    except Exception:  # pragma: no cover - depende del sistema
        return False
    finally:
        win32print.ClosePrinter(manejador)


def resolver(nombre: str) -> str:
    """Qué cola hay que usar de verdad para la impresora configurada.

    Windows duplica la cola cuando la impresora se reconecta en otro puerto
    USB: la original queda apuntando a un puerto que ya no existe —y marcada
    «sin conexión»— y aparece una copia «Xprinter XP-360B (Copiar 1)» en el
    puerto nuevo. Pasó en la tienda el 08/09/2026 y dejó al ERP mandando
    etiquetas a la cola muerta durante toda una mañana: Windows las aceptaba
    sin protestar y no salía nada.

    Por eso no se exige el nombre exacto: si la cola configurada no está o
    está sin conexión, se usa la copia viva. Es preferible imprimir por la
    copia y dejar el aviso en el registro, a no imprimir y que nadie sepa por
    qué."""
    if not nombre:
        raise ErrorDeImpresion("No hay ninguna impresora configurada para esta tarea.")
    disponibles = listar_impresoras()

    if nombre in disponibles and not sin_conexion(nombre):
        return nombre

    # Las copias de Windows conservan el nombre y le agregan un sufijo.
    familia = sorted(
        d for d in disponibles
        if d != nombre and d.startswith(nombre) and not sin_conexion(d)
    )
    if familia:
        elegida = familia[-1]   # la copia más nueva
        logger.warning(
            "La cola «%s» no está disponible; se imprime por «%s». "
            "Conviene arreglar el puerto de la impresora en Windows.",
            nombre, elegida,
        )
        return elegida

    if nombre in disponibles:
        raise ErrorDeImpresion(
            f"La impresora «{nombre}» está marcada «usar sin conexión» en Windows, "
            "así que acepta los trabajos y no los imprime. Revisá que esté "
            "encendida y conectada, y quitale esa marca."
        )
    raise ErrorDeImpresion(
        f"Windows no encuentra la impresora «{nombre}». "
        f"Instaladas ahora mismo: {', '.join(disponibles) or 'ninguna'}."
    )


def enviar_crudo(impresora: str, datos: bytes, titulo: str = "ALLPETCR") -> None:
    """Manda los bytes a la impresora sin que el driver los interprete."""
    win32print = _pywin32()
    impresora = resolver(impresora)
    manejador = win32print.OpenPrinter(impresora)
    try:
        # El tercer elemento, "RAW", es lo que evita que el driver reinterprete
        # los comandos ESC/POS como si fueran una página que hay que maquetar.
        win32print.StartDocPrinter(manejador, 1, (titulo, None, "RAW"))
        try:
            win32print.StartPagePrinter(manejador)
            win32print.WritePrinter(manejador, datos)
            win32print.EndPagePrinter(manejador)
        finally:
            win32print.EndDocPrinter(manejador)
    except Exception as e:  # pragma: no cover - depende del hardware
        raise ErrorDeImpresion(f"No se pudo imprimir en «{impresora}»: {e}") from e
    finally:
        win32print.ClosePrinter(manejador)


def imprimir_imagen(impresora: str, imagen, ancho_mm: float, alto_mm: float,
                    titulo: str = "ALLPETCR") -> None:
    """Imprime una imagen a través del driver, en una hoja del tamaño pedido.

    `imagen` es un objeto de Pillow. El tamaño se pasa en décimas de milímetro
    porque así lo espera la estructura DEVMODE de Windows."""
    win32print = _pywin32()
    import win32gui
    import win32ui
    from PIL import ImageWin

    impresora = resolver(impresora)
    manejador = win32print.OpenPrinter(impresora)
    dc = None
    try:
        modo = win32print.GetPrinter(manejador, 2)["pDevMode"]
        modo.PaperSize = _PAPEL_DEFINIDO_POR_USUARIO
        modo.PaperWidth = int(round(ancho_mm * 10))
        modo.PaperLength = int(round(alto_mm * 10))
        modo.Fields = modo.Fields | _DM_PAPERSIZE | _DM_PAPERWIDTH | _DM_PAPERLENGTH

        # CreateDC con el DEVMODE modificado: es el único camino para que la
        # etiqueta salga del tamaño del rollo. `CreatePrinterDC` no acepta
        # DEVMODE y usaría el tamaño de fábrica del driver.
        contexto = win32gui.CreateDC("WINSPOOL", impresora, modo)
        dc = win32ui.CreateDCFromHandle(contexto)
        dc.StartDoc(titulo)
        dc.StartPage()
        ancho_px = dc.GetDeviceCaps(_HORZRES)
        alto_px = dc.GetDeviceCaps(_VERTRES)
        ImageWin.Dib(imagen.convert("RGB")).draw(
            dc.GetHandleOutput(), (0, 0, ancho_px, alto_px)
        )
        dc.EndPage()
        dc.EndDoc()
    except Exception as e:  # pragma: no cover - depende del hardware
        raise ErrorDeImpresion(f"No se pudo imprimir en «{impresora}»: {e}") from e
    finally:
        if dc is not None:
            try:
                dc.DeleteDC()
            except Exception:
                logger.warning("No se pudo liberar el contexto de impresión", exc_info=True)
        win32print.ClosePrinter(manejador)
