"""Tiquete con el resumen del cierre de caja, para la térmica de 80 mm
(02/11/2026, pedido de Oscar: "que imprima un tiquete en la impresora térmica
con un cierre de las ventas diarias").

Mismo camino que el tiquete de venta: ESC/POS armado en el servidor y
entregado por el agente de la tienda, así que no hay que reinstalar nada en
la computadora de la caja.

Recibe el diccionario de `caja.resumen.resumen_cierre` ya armado: este
módulo solo acomoda renglones, no calcula. Así el papel no puede decir algo
distinto que el correo o la pantalla.
"""
from __future__ import annotations

from decimal import Decimal

from .tiquete import (CENTRO, CODIGOS_CP850, CORTAR, DOBLE, IZQUIERDA, INICIALIZAR, NEGRITA_OFF, NEGRITA_ON,
                      NORMAL, SALTO, _dos_columnas, _envolver, _hora_local, _monto, _texto)


def _con_signo(valor) -> str:
    """¢1.000 / -¢1.000 / ¢0: el signo va antes del colón, como se lee."""
    valor = Decimal(valor or 0)
    return f"-{_monto(-valor)}" if valor < 0 else _monto(valor)


def _fecha(momento) -> str:
    return f"{_hora_local(momento):%d/%m/%Y %I:%M %p}" if momento else "—"


def _usuario(u) -> str:
    if not u:
        return "—"
    return u.get_full_name() or u.get_username()


def bytes_cierre(datos: dict, ancho: int = 48, logo: bytes = b"", impreso_en=None) -> bytes:
    s = datos["sesion"]
    p: list[bytes] = [INICIALIZAR, CODIGOS_CP850, CENTRO]
    linea = lambda t="": p.extend([_texto(t), SALTO])  # noqa: E731
    fila = lambda a, b: linea(_dos_columnas(a, b, ancho))  # noqa: E731
    raya = lambda: linea("-" * ancho)  # noqa: E731
    titulo = lambda t: p.extend([NEGRITA_ON, _texto(t), NEGRITA_OFF, SALTO])  # noqa: E731

    if logo:
        p += [logo, SALTO]
    p += [NEGRITA_ON, DOBLE, _texto("CIERRE DE CAJA"), NORMAL, NEGRITA_OFF, SALTO]
    linea(s.sucursal.empresa.nombre)
    linea(s.sucursal.nombre)
    p += [NEGRITA_ON, _texto(f"Caja #{s.pk}"), NEGRITA_OFF, SALTO]
    p += [IZQUIERDA]
    linea(f"Abrió: {_usuario(s.usuario)}  {_fecha(s.abierta_en)}")
    linea(f"Cerró: {_usuario(s.cerrada_por)}  {_fecha(s.cerrada_en)}")
    raya()

    titulo("VENTAS")
    fila(f"Ventas ({datos['ventas_n']})", _monto(datos["ventas_total"]))
    for nombre, n, total in datos["ventas_por_medio"]:
        fila(f"  {nombre} ({n})", _monto(total))
    if datos["descuentos"] > 0:
        fila("Descuentos dados", f"-{_monto(datos['descuentos'])}")
    if datos["redondeo"] > 0:
        fila("Redondeos", f"-{_monto(datos['redondeo'])}")
    if datos["impuesto"] > 0:
        fila("IVA incluido en las ventas", _monto(datos["impuesto"]))
    if datos["regalias"]:
        fila("Regalías entregadas", f"{datos['regalias']:g} unid.")
    if datos["anuladas_n"]:
        fila(f"Anuladas ({datos['anuladas_n']})", _monto(datos["anuladas_total"]))
    raya()

    titulo("EFECTIVO EN LA GAVETA")
    for concepto, monto in datos["efectivo"]:
        if monto or concepto == "Apertura":
            fila(concepto, _con_signo(monto))
    for r in datos.get("retiros", []):
        estado = "depositado" if r.estado == "DEP" else "por depositar"
        linea(f"  {r.referencia} {_hora_local(r.creado_en):%I:%M %p} {_usuario(r.usuario)} ({estado})"[:ancho])
    p += [NEGRITA_ON]
    fila("= Se esperaba", _monto(s.monto_esperado or 0))
    p += [NEGRITA_OFF]
    fila("Se contó", _monto(s.monto_contado or 0))
    raya()

    if datos.get("cambios_medio"):
        titulo("VENTAS COBRADAS CON OTRO MEDIO")
        for c in datos["cambios_medio"]:
            fila(f"{c.factura.numero} {c.get_anterior_display()} > {c.get_nuevo_display()}", _monto(c.monto))
            for renglon in _envolver(f"«{c.motivo}» ({_usuario(c.usuario)})", ancho - 2):
                linea(f"  {renglon}")
        raya()

    titulo("ARQUEO POR MEDIO")
    col = (ancho - 12) // 3
    linea(f"{'':12}{'Esperado':>{col}}{'Contado':>{col}}{'Diferencia':>{col}}"[:ancho])
    for a in datos["arqueo"]:
        if a["contado"] is None:
            linea(f"{a['nombre'][:12]:12}{_monto(a['esperado']):>{col}}{'no revisado':>{col * 2}}"[:ancho])
            continue
        linea(f"{a['nombre'][:12]:12}{_monto(a['esperado']):>{col}}{_monto(a['contado']):>{col}}"
              f"{_con_signo(a['diferencia']):>{col}}"[:ancho])
    raya()

    p += [CENTRO, NEGRITA_ON, DOBLE]
    linea("CUADRA" if datos["cuadra"] else "NO CALZÓ")
    p += [NORMAL, NEGRITA_OFF, IZQUIERDA]
    for d in datos["diferencias"]:
        quien = "Faltan" if d.diferencia < 0 else "Sobran"
        p += [NEGRITA_ON]
        fila(f"{d.get_medio_display()}: {quien.lower()}", _monto(abs(d.diferencia)))
        p += [NEGRITA_OFF]
        for renglon in _envolver(d.get_motivo_display() or "Sin explicar", ancho - 2):
            linea(f"  {renglon}")
        if d.explicacion:
            for renglon in _envolver(f"«{d.explicacion}»", ancho - 2):
                linea(f"  {renglon}")
    if len(datos["diferencias"]) > 1:
        fila("Sumando los medios", _con_signo(datos["neto"]))
    previos = s.conteos_previos or []
    if previos:
        linea(f"Se volvió a contar: {len(previos)} vez/veces antes.")
        for c in previos:
            linea(f"  Primero: efectivo {_monto(c.get('efectivo') or 0)}")
    if s.aviso_diferencia:
        for renglon in _envolver(s.aviso_diferencia, ancho):
            linea(renglon)
    raya()

    if datos["apertura_vs_anterior"]:
        for renglon in _envolver(
                f"Ojo: abrió con {_monto(s.monto_apertura)}; el cierre anterior contó "
                f"{_monto(datos['anterior'].monto_contado)}. Puede ser un depósito.", ancho):
            linea(renglon)
        raya()

    if datos["desglose"]:
        titulo("BILLETES Y MONEDAS")
        for valor, cantidad, subtotal in datos["desglose"]:
            fila(f"  {cantidad} x {_monto(valor)}", _monto(subtotal))
        raya()

    linea()
    linea("Firma de quien cierra:")
    linea()
    linea("_" * (ancho * 2 // 3))
    linea()
    linea("Revisado por:")
    linea()
    linea("_" * (ancho * 2 // 3))
    linea()
    if impreso_en:
        p += [CENTRO]
        linea(f"Impreso {_fecha(impreso_en)}")
    p += [SALTO, SALTO, CORTAR]
    return b"".join(p)


def bytes_retiro(retiro, ancho: int = 48, logo: bytes = b"", abrir_gaveta: bool = True) -> bytes:
    """Comprobante del efectivo que se sacó de la gaveta (02/11/2026). Va
    dentro del sobre con la plata hasta que se deposita, firmado por quien la
    sacó. El pulso de la gaveta va primero: para sacar la plata hay que
    abrirla, y así no hace falta llave ni una venta falsa."""
    from .tiquete import ABRIR_GAVETA

    p: list[bytes] = [ABRIR_GAVETA] if abrir_gaveta else []
    p += [INICIALIZAR, CODIGOS_CP850, CENTRO]
    linea = lambda t="": p.extend([_texto(t), SALTO])  # noqa: E731
    fila = lambda a, b: linea(_dos_columnas(a, b, ancho))  # noqa: E731
    if logo:
        p += [logo, SALTO]
    p += [NEGRITA_ON, DOBLE, _texto("RETIRO DE CAJA"), NORMAL, NEGRITA_OFF, SALTO]
    linea("Efectivo para depositar")
    linea(retiro.sesion.sucursal.empresa.nombre)
    p += [IZQUIERDA]
    linea(f"{retiro.referencia} · Caja #{retiro.sesion_id}")
    linea(f"Fecha: {_fecha(retiro.creado_en)}")
    linea(f"Sacó: {_usuario(retiro.usuario)}")
    if retiro.nota:
        for renglon in _envolver(f"Nota: {retiro.nota}", ancho):
            linea(renglon)
    linea("-" * ancho)
    for valor, cantidad, subtotal in retiro.desglose():
        fila(f"  {cantidad} x {_monto(valor)}", _monto(subtotal))
    p += [NEGRITA_ON, DOBLE]
    linea(_dos_columnas("TOTAL", _monto(retiro.monto), ancho // 2))
    p += [NORMAL, NEGRITA_OFF]
    linea("-" * ancho)
    linea()
    linea("Firma de quien saca:")
    linea()
    linea("_" * (ancho * 2 // 3))
    linea()
    linea("Depositado el ____/____/______")
    linea("Comprobante N.° ________________")
    p += [SALTO, SALTO, CORTAR]
    return b"".join(p)
