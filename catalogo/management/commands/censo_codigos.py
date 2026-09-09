"""Censo de los códigos de barras del catálogo. NO modifica nada.

Antes de convertir 532 códigos hay que saber qué hay: cuántos son EAN de
verdad, cuántos parecen EAN pero tienen el dígito verificador malo, y cuántos
salieron del SKU. Convertir a ciegas destruiría los códigos legítimos de
fábrica, que son los que conviene conservar.
"""
import logging
from collections import Counter

import barcode
from django.conf import settings
from django.core.management.base import BaseCommand

from catalogo.models import Producto

logger = logging.getLogger(__name__)

def _modulos_maximos() -> int:
    """A partir de cuántos módulos ya no caben barras de 0,25 mm.

    Se calcula con el ancho del rollo configurado en vez de dejarlo escrito a
    mano: el 08/09/2026 el rollo pasó de 35 a 44,5 mm y un número fijo aquí
    habría seguido acusando códigos que sí se pueden imprimir.

    La cuenta: 2 puntos por barra es el mínimo que la pistola lee, y a los
    lados hay que dejar la zona de silencio (aquí la reducida, que es hasta
    donde afloja `impresion.etiqueta`).
    """
    puntos = int(round(settings.ETIQUETA_ANCHO_MM / 25.4 * 203))
    return (puntos // 2) - 2 * 7


def _es_ean(codigo, nombre, largo):
    if len(codigo) != largo or not codigo.isdigit():
        return False
    try:
        return barcode.get(nombre, codigo[:-1]).get_fullcode() == codigo
    except Exception:
        return False


class Command(BaseCommand):
    help = "Muestra qué tipo de código de barras tiene cada producto. Solo lectura."

    def handle(self, *args, **opciones):
        productos = Producto.objects.filter(activo=True).values_list(
            "sku", "nombre", "codigo_barras"
        )
        total = 0
        grupos = Counter()
        largos = Counter()
        ejemplos = {}
        finos = []
        ilegibles = []

        modulos_maximos = _modulos_maximos()

        for sku, nombre, codigo in productos:
            total += 1
            codigo = (codigo or "").strip()
            if not codigo:
                grupo = "sin codigo"
            elif _es_ean(codigo, "ean13", 13):
                grupo = "EAN-13 valido"
            elif _es_ean(codigo, "ean8", 8):
                grupo = "EAN-8 valido"
            elif codigo.isdigit() and len(codigo) == 13:
                grupo = "13 digitos con verificador MALO"
            elif codigo.isdigit():
                grupo = "solo digitos, otro largo"
                largos[len(codigo)] += 1
            else:
                grupo = "con letras (sale del SKU)"
            grupos[grupo] += 1
            ejemplos.setdefault(grupo, []).append(f"{sku} = {codigo or '(vacio)'}  {nombre[:38]}")

            if codigo:
                try:
                    modulos = len(barcode.get("code128", codigo).build()[0])
                    if modulos > modulos_maximos and not (
                        _es_ean(codigo, "ean13", 13) or _es_ean(codigo, "ean8", 8)
                    ):
                        finos.append(f"{sku} = {codigo} ({modulos} modulos)")
                except Exception as fallo:
                    # Un código que la librería no puede ni dibujar tampoco se
                    # va a poder imprimir: es justo lo que este censo busca.
                    logger.exception("No se pudo medir el código %r del SKU %s", codigo, sku)
                    ilegibles.append(f"{sku} = {codigo} ({fallo.__class__.__name__}: {fallo})")

        self.stdout.write("=== CENSO DE CODIGOS DE BARRAS ===")
        self.stdout.write(f"Productos activos: {total}")
        for grupo, cuantos in grupos.most_common():
            self.stdout.write(f"  {grupo:<34} {cuantos:>5}")
            for linea in ejemplos[grupo][:4]:
                self.stdout.write(f"        ej. {linea}")
        if largos:
            self.stdout.write("  Largos de los codigos solo-digitos: " +
                              ", ".join(f"{k} digitos: {v}" for k, v in sorted(largos.items())))
        self.stdout.write("")
        self.stdout.write(
            f"Codigos que NO admiten barras gruesas en "
            f"{settings.ETIQUETA_ANCHO_MM:g} mm: {len(finos)}"
        )
        for linea in finos[:15]:
            self.stdout.write(f"      {linea}")
        if len(finos) > 15:
            self.stdout.write(f"      ... y {len(finos) - 15} mas")

        if ilegibles:
            self.stdout.write("")
            self.stderr.write(
                f"Codigos que la libreria no pudo ni dibujar (no se van a poder "
                f"imprimir): {len(ilegibles)}"
            )
            for linea in ilegibles[:15]:
                self.stderr.write(f"      {linea}")
            if len(ilegibles) > 15:
                self.stderr.write(f"      ... y {len(ilegibles) - 15} mas")
