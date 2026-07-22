"""Formato de números al estilo de Costa Rica: miles con punto, decimales con
coma (₡1.234.567,89). Determinístico, sin depender de la localización del
sistema. Se registra como filtro global (ver settings TEMPLATES 'builtins'),
así funciona en todas las plantillas sin {% load %}.

Uso:  {{ valor|crc }}      -> 1.234.568   (0 decimales, redondeado)
      {{ valor|crc:2 }}    -> 1.234.567,89
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name="crc")
def crc(value, decimales=0):
    """Formatea un número con punto de miles y coma decimal."""
    if value is None or value == "":
        return ""
    try:
        d = int(decimales)
    except (TypeError, ValueError):
        d = 0
    try:
        num = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    # Formato "en-US" (coma miles, punto decimal) y luego se intercambian los
    # separadores para dejarlo al estilo CR.
    base = f"{num:,.{d}f}"
    return base.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
