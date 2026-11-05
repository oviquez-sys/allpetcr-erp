"""Qué productos NO llevan el cupón de bienvenida de la manada.

Pedido de Oscar (05/11/2026): el alimento tiene un margen tan chico que el
10 % de bienvenida los dejaba casi sin ganancia. Desde esa fecha el cupón se
aplica a todo MENOS al alimento.

- "Alimento" = la categoría raíz Alimento, o cualquier producto cuya ficha
  técnica sea de alimento seco o húmedo (por si quedó mal categorizado). Los
  snacks y premios SÍ llevan el cupón: tienen otro margen y no los pidió
  excluir.
- La exclusión viaja en el cupón (`Cupon.excluye_alimentos`), copiada de la
  regalía al emitirse, igual que el porcentaje. Los cupones que ya se habían
  entregado prometían "10 % en tu primera compra" sin esa condición: se
  respetan como se ofrecieron.
- Una sola regla para la caja (ventas.services.registrar_venta), el POS
  (ventas.views._filas_pos → `alimento` en cada producto) y los textos.
"""
from __future__ import annotations

RAICES_SIN_CUPON = {"Alimento"}
TIPOS_FICHA_SIN_CUPON = {"seco", "humedo"}
LEYENDA = "no aplica a alimentos"


def es_alimento(raiz: str | None, tipo_ficha: str | None = None) -> bool:
    return (raiz or "") in RAICES_SIN_CUPON or (tipo_ficha or "") in TIPOS_FICHA_SIN_CUPON


def producto_es_alimento(producto) -> bool:
    cat = producto.categoria
    raiz = (cat.padre.nombre if cat.padre_id else cat.nombre) if cat is not None else ""
    ficha = producto.ficha_alimento if producto.ficha_alimento_id else None
    return es_alimento(raiz, ficha.tipo if ficha else None)


def cupon_aplica(cupon, producto) -> bool:
    """¿Este cupón rebaja este producto?"""
    return not (cupon.excluye_alimentos and producto_es_alimento(producto))


def texto_con_condicion(texto: str, excluye: bool) -> str:
    """"10 % de descuento en tu primera compra" → "... (no aplica a alimentos)".
    Si el gerente ya lo escribió en el texto, no se repite."""
    texto = (texto or "").strip()
    if not excluye or "aliment" in texto.lower():
        return texto
    return f"{texto} ({LEYENDA})"
