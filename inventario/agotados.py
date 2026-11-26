"""Agotados: el código del proveedor, la alarma del Inicio y la última compra.

Pedido de Oscar (02/10/2026): la lista de agotados tiene que traer el código
del proveedor, porque con ella se arma el pedido o se decide no comprar más.
Desde el 26/11/2026 la lista vive en la pantalla «Reponer» (pestaña
Agotados, inventario/reponer.py). Aquí queda lo que usan otras partes.
"""
import re

from .models import Agotamiento

# Prefijos que el ERP le agrega al código del proveedor al crear el SKU
# (comandos cargar_compra_belina / gosbi / zeedog y la compra de Special
# Care). Quitándolos queda el código tal como lo conoce el proveedor.
_PREFIJOS_INTERNOS = re.compile(r"^(BEL|GOS|ZDG|SPC)-", re.IGNORECASE)


def codigo_proveedor(sku):
    """Código con el que se le pide el producto al proveedor.

    - "BEL-1234" → "1234" (y lo mismo con GOS-, ZDG-, SPC-).
    - Los de Buen Amigo y los del inventario inicial usan el REF del
      proveedor como SKU, así que van tal cual.
    - Los "NP…" los inventa el ERP cuando el producto entra sin código: el
      proveedor no los conoce, así que no se muestran (queda el código de
      barras, que sí sirve para pedir).
    """
    sku = (sku or "").strip()
    if not sku or sku.upper().startswith("NP"):
        return ""
    return _PREFIJOS_INTERNOS.sub("", sku)


def por_decidir(empresa):
    """Cuántos avisos esperan una decisión. Es lo que enciende la alarma del
    Inicio y no se cachea: un aviso que aparece dos minutos tarde no avisa."""
    return Agotamiento.objects.filter(
        producto__empresa=empresa, repuesto_en__isnull=True,
        decision=Agotamiento.Decision.PENDIENTE,
    ).count()


def _ultima_compra(producto_ids):
    """{producto_id: LineaCompra} con la compra recibida más reciente."""
    from compras.models import Compra, LineaCompra

    lineas = (
        LineaCompra.objects
        .filter(producto_id__in=producto_ids, compra__estado=Compra.Estado.RECIBIDA)
        .select_related("compra__proveedor")
        .order_by("producto_id", "-compra_id", "-id")
    )
    ultima = {}
    for linea in lineas:
        ultima.setdefault(linea.producto_id, linea)
    return ultima
