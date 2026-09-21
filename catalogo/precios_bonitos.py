"""Precio "bonito" para trasladarle el IVA al cliente (20/09/2026).

Por qué existe
--------------
AllPetCR resultó ser régimen tradicional desde el primer día, y los precios
se habían puesto sin pensar en el IVA. Oscar decidió trasladárselo al
cliente: cada precio sube 13 %. Pero ₡5.989 (₡5.300 × 1,13) se ve raro y
caro; su pedido textual fue que el cliente vea el precio y piense "está
bonito y no tan caro, no me importa pagarlo".

La regla
--------
1. Se calcula el precio exacto con IVA (precio × 1,13).
2. Se busca el precio "bonito" más cercano:
      menos de ₡2.000       termina en 50 o 90       (₡690, ₡1.250, ₡1.990)
      ₡2.000 a ₡19.999      termina en 90            (₡2.390, ₡5.990)
      ₡20.000 o más         termina en 900           (₡25.900, ₡53.900)
3. Si bajar un poquito evita saltar al siguiente millar, se baja: ₡5.990 se
   lee "cinco mil y resto", ₡6.090 se lee "seis mil". Es el efecto del
   primer dígito, el más documentado en precios minoristas.
4. Nunca se baja más de 3 % del precio exacto: el IVA se traslada, no se
   regala.

Medido sobre los 295 precios reales del sitio (20/09/2026): en promedio el
precio bonito queda 0,26 % por debajo del exacto — prácticamente neutro.
"""
from decimal import ROUND_HALF_UP, Decimal

TOPE_REBAJA = Decimal("0.97")  # nunca más de 3 % por debajo del exacto


def es_bonito(valor: int) -> bool:
    if valor < 2000:
        return valor % 100 in (50, 90)
    if valor < 20000:
        return valor % 100 == 90
    return valor % 1000 == 900


def precio_bonito(exacto: Decimal) -> Decimal:
    """El precio bonito para un precio exacto (ya con IVA)."""
    if exacto <= 0:
        return Decimal("0")
    t = int(exacto.to_integral_value(ROUND_HALF_UP))
    arriba = t
    while not es_bonito(arriba):
        arriba += 1
    abajo = t - 1
    while abajo > 0 and not es_bonito(abajo):
        abajo -= 1

    if abajo <= 0 or abajo < exacto * TOPE_REBAJA:
        return Decimal(arriba)
    # Bajar evita cambiar el primer dígito (del millar, o de la centena en
    # precios chicos): se prefiere ₡5.990 a ₡6.090.
    grupo = 100 if arriba < 1000 else 1000
    if abajo // grupo != arriba // grupo:
        return Decimal(abajo)
    return Decimal(abajo if (exacto - abajo) < (arriba - exacto) else arriba)
