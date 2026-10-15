"""Billetes y monedas de colón vigentes, para contar la caja (14/10/2026).

Fuente: Banco Central de Costa Rica, bccr.fi.cr → Billetes y monedas
(revisado el 14/10/2026). Ya NO circulan:
- el billete de ₡50.000 (el BCCR lo sacó de circulación) y
- la moneda de ₡5 (no se acuña desde 2020; las de diseño anterior de ₡5, ₡10
  y ₡25 dejaron de ser medio de pago el 1/7/2026).

Si el BCCR saca o pone una denominación, se cambia SOLO esta lista: la
pantalla de cierre y el cálculo salen de aquí. Un cierre viejo guarda su
propio conteo, así que cambiar la lista no altera cierres pasados.
"""
BILLETES = (20000, 10000, 5000, 2000, 1000)
MONEDAS = (500, 100, 50, 25, 10)
TODAS = BILLETES + MONEDAS


def total(conteo) -> int:
    """{"20000": 3, "500": 4} -> 62000. Solo cuenta denominaciones vigentes."""
    return sum(int(valor) * int(conteo.get(str(valor), 0) or 0) for valor in TODAS)
