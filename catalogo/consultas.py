"""Punto único donde se decide qué productos ve el personal.

LA REGLA (Oscar, 02/08/2026)
---------------------------
El ERP muestra solo lo que hay en existencia. De los 532 productos del
catálogo, 348 están en cero: listarlos en cada pantalla obliga a filtrar a
ojo cientos de artículos que no se pueden ni vender ni etiquetar.

LAS DOS EXCEPCIONES, Y POR QUÉ NO SON NEGOCIABLES
-------------------------------------------------
Hay dos pantallas donde ocultar el stock en cero no es una molestia: es un
punto muerto del que el sistema no puede salir solo.

1. **Compras / recibir mercadería** (`compras.views.nueva`) es LA pantalla
   que hace que un producto agotado deje de estarlo. Si no aparece ahí, no
   se puede recibir; si no se puede recibir, el stock nunca sube; si el
   stock nunca sube, no vuelve a aparecer en ninguna parte. Un producto que
   se agota quedaría enterrado para siempre.

2. **Ajuste de inventario** (`inventario.forms.AjusteForm`) existe justo
   para corregir el conteo cuando la base dice cero y en la bodega hay tres
   —o al revés—. Filtrar por stock ahí es filtrar por el dato que se está
   corrigiendo.

Estas dos usan `Producto.objects` directamente y lo dicen en un comentario.
No es un olvido de aplicar la regla; es la regla teniendo un límite.

`core/test_arquitectura.py` verifica que ninguna otra pantalla se salte esto:
una regla que no se verifica sola se rompe en tres meses.
"""
from .models import Producto


def productos_visibles(empresa, *, incluir_agotados=False):
    """Productos que el personal debe ver: activos, de la empresa, con stock.

    `incluir_agotados=True` es la vía explícita para las pantallas que
    ofrecen un botón "ver también los agotados". Es un parámetro y no una
    variante silenciosa para que cada excepción quede escrita en el código
    que la necesita.
    """
    qs = Producto.objects.filter(activo=True, empresa=empresa)
    if not incluir_agotados:
        qs = qs.filter(stock_actual__gt=0)
    return qs


def pidio_agotados(request):
    """True si la pantalla debe mostrar también lo que no hay.

    Se lee de la querystring (`?agotados=1`) y no de una preferencia guardada
    a propósito: así el estado se ve en la URL, se puede compartir un enlace,
    y nadie queda con un filtro activo de la semana pasada sin saberlo.
    """
    return request.GET.get("agotados") == "1"
