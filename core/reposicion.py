"""Reposición basada en velocidad de venta, no en un mínimo fijo.

El problema que resuelve
------------------------
`Producto.stock_minimo` viene con `default=2` para todo el catálogo. Con 184
productos ya era grueso; con el catálogo nuevo de 532 es inservible: un
alimento que rota 30 unidades por semana y una correa que sale una vez al mes
avisan las dos a las 2 unidades. Con el primero te quedás sin producto en tres
días; con la segunda no pasa nada.

Lo que hace en su lugar
-----------------------
Mide cuánto se vendió de cada producto en una ventana reciente, lo convierte a
venta diaria promedio y responde dos preguntas que el mínimo fijo no puede
responder:

- ¿Cuántos días de venta me quedan con el stock que tengo? (cobertura)
- ¿Cuánto tengo que pedir para llegar a la cobertura que quiero?

Límites conocidos, que no hay que tapar
---------------------------------------
El promedio miente en dos casos y conviene saberlo antes de comprar por lo que
diga este cálculo:

- **Producto estacional.** Si vendiste 40 en diciembre y nada en enero, el
  promedio de 90 días te va a sugerir comprar en febrero.
- **Producto que estuvo agotado.** Si no había stock, no se vendió, y el
  promedio sale bajo justo en el producto que más te faltó. El cálculo lo
  marca (`hubo_quiebre`) pero no lo corrige solo: corregirlo requiere saber
  cuántos días estuvo en cero, y eso el kardex lo dice de forma cara.

Por eso la sugerencia se presenta como sugerencia, y la pantalla muestra las
unidades vendidas y la ventana usada al lado del número. Un número de compra
sin su evidencia es una orden a ciegas.
"""
import os
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

# Ventana de análisis. 60 días es el compromiso: suficiente para promediar el
# ruido semanal (quincenas, fines de semana), corto para que un cambio real de
# demanda se note en semanas y no en trimestres. Configurable sin tocar código.
DIAS_VENTANA = int(os.environ.get("REPOSICION_DIAS_VENTANA", "60"))

# Cobertura objetivo: cuántos días de venta querés tener en bodega después de
# reponer. 30 días asume una compra mensual al proveedor.
DIAS_COBERTURA_OBJETIVO = int(os.environ.get("REPOSICION_DIAS_OBJETIVO", "30"))

# Por debajo de esta cobertura el producto se considera urgente. 7 días es el
# tiempo típico entre que se pide y llega la mercadería.
DIAS_COBERTURA_CRITICA = int(os.environ.get("REPOSICION_DIAS_CRITICOS", "7"))


def velocidades(empresa, dias=None):
    """Unidades vendidas por día de cada producto en la ventana.

    Se mide sobre `LineaVenta` de facturas EMITIDAS, no sobre el kardex: el
    kardex mezcla ventas con ajustes, compras y devoluciones, y para saber a
    qué ritmo se vende sólo interesan las ventas. Las regalías se cuentan
    porque también vacían la bodega.

    Devuelve {producto_id: Decimal(unidades por día)}.
    """
    from ventas.models import LineaVenta

    from datetime import timedelta

    dias = dias or DIAS_VENTANA
    desde = timezone.localdate() - timedelta(days=dias)

    vendidas = (
        LineaVenta.objects
        .filter(
            factura__empresa=empresa,
            factura__estado="EMI",
            factura__creado_en__date__gte=desde,
        )
        .values("producto_id")
        .annotate(unidades=Sum("cantidad"))
    )
    return {
        f["producto_id"]: (f["unidades"] or Decimal("0")) / Decimal(dias)
        for f in vendidas
    }


def sugerencias(empresa, dias=None, objetivo=None, solo_urgentes=False):
    """Qué reponer, cuánto y con qué urgencia.

    Cada fila trae el número Y la evidencia con la que se calculó, para poder
    discutirlo: unidades vendidas en la ventana, venta diaria, cobertura
    actual y cantidad sugerida.
    """
    from catalogo.models import Producto
    from ventas.models import LineaVenta

    dias = dias or DIAS_VENTANA
    objetivo = objetivo or DIAS_COBERTURA_OBJETIVO
    from datetime import timedelta
    desde = timezone.localdate() - timedelta(days=dias)

    unidades_por_producto = {
        f["producto_id"]: (f["unidades"] or Decimal("0"))
        for f in LineaVenta.objects.filter(
            factura__empresa=empresa,
            factura__estado="EMI",
            factura__creado_en__date__gte=desde,
        ).values("producto_id").annotate(unidades=Sum("cantidad"))
    }

    productos = (
        Producto.objects
        .filter(empresa=empresa, activo=True)
        .select_related("categoria")
    )

    filas = []
    for p in productos:
        vendidas = unidades_por_producto.get(p.pk, Decimal("0"))
        diaria = vendidas / Decimal(dias) if dias else Decimal("0")

        if diaria > 0:
            cobertura = p.stock_actual / diaria
            sugerido = (diaria * Decimal(objetivo)) - p.stock_actual
        else:
            # Sin ventas en la ventana no hay velocidad que medir. No se
            # inventa una: se cae al criterio viejo del mínimo fijo, que para
            # un producto que no rota es suficiente.
            cobertura = None
            sugerido = (p.stock_minimo - p.stock_actual) if p.stock_actual <= p.stock_minimo else Decimal("0")

        if sugerido < 0:
            sugerido = Decimal("0")

        # Un producto en cero que sí se vendía es la señal más fuerte de que
        # el promedio está subestimando la demanda real.
        hubo_quiebre = p.stock_actual <= 0 and vendidas > 0

        if cobertura is None:
            urgencia = "sin_rotacion" if sugerido == 0 else "bajo_minimo"
        elif p.stock_actual <= 0:
            urgencia = "agotado"
        elif cobertura <= DIAS_COBERTURA_CRITICA:
            urgencia = "critico"
        elif cobertura <= objetivo:
            urgencia = "reponer"
        else:
            urgencia = "ok"

        filas.append({
            "producto": p,
            "vendidas": vendidas,
            "diaria": diaria,
            "cobertura": cobertura,
            "sugerido": sugerido,
            "urgencia": urgencia,
            "hubo_quiebre": hubo_quiebre,
            "bajo_minimo": p.stock_actual <= p.stock_minimo,
        })

    orden = {"agotado": 0, "critico": 1, "reponer": 2, "bajo_minimo": 3, "sin_rotacion": 4, "ok": 5}
    filas.sort(key=lambda f: (orden[f["urgencia"]], f["cobertura"] if f["cobertura"] is not None else 9999))

    if solo_urgentes:
        filas = [f for f in filas if f["urgencia"] in ("agotado", "critico", "reponer", "bajo_minimo")]

    return {
        "filas": filas,
        "dias_ventana": dias,
        "dias_objetivo": objetivo,
        "dias_criticos": DIAS_COBERTURA_CRITICA,
        "desde": desde,
        "num_agotados": sum(1 for f in filas if f["urgencia"] == "agotado"),
        "num_criticos": sum(1 for f in filas if f["urgencia"] == "critico"),
        "num_reponer": sum(1 for f in filas if f["urgencia"] == "reponer"),
        "num_quiebres": sum(1 for f in filas if f["hubo_quiebre"]),
    }
