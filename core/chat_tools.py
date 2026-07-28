"""Herramientas (function calling) que el chat de ayuda puede usar para
consultar datos REALES del negocio, en vez de solo explicar cómo se usa el
sistema. Todo acá es de SOLO LECTURA — ninguna herramienta escribe en la base
de datos. Si algún día se agrega una que sí escribe, tiene que pedir
confirmación explícita en el frontend antes de ejecutarse.
"""
from decimal import Decimal

from . import reportes as rep
from .dashboard import indicadores
from .models import Empresa

# Definición de herramientas en formato Anthropic tool-use. La descripción es
# lo que Claude lee para decidir CUÁNDO usar cada una — hay que ser preciso.
TOOLS_SCHEMA = [
    {
        "name": "indicadores_del_negocio",
        "description": (
            "Devuelve los indicadores clave de hoy y del mes: ventas de hoy, "
            "ventas del mes, margen de utilidad del mes, si la caja está "
            "abierta y su saldo esperado, total por cobrar a clientes (CxC), "
            "y cuántos productos tienen stock bajo el mínimo. Usar esta "
            "herramienta para cualquier pregunta sobre '¿cuánto vendí?', "
            "'¿cómo va el mes?', '¿cuánto tengo en caja?', '¿cuánto me deben?'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "productos_mas_vendidos",
        "description": (
            "Devuelve el ranking de productos más vendidos en el mes en curso "
            "(unidades e ingreso). Usar para preguntas de '¿qué se vende más?' "
            "o '¿cuál es mi producto estrella?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limite": {
                    "type": "integer",
                    "description": "Cuántos productos devolver, máximo 20. Por defecto 5.",
                }
            },
        },
    },
    {
        "name": "productos_stock_bajo",
        "description": (
            "Devuelve la lista de productos cuyo stock actual está en o por "
            "debajo del mínimo definido (necesitan reposición ya). Usar para "
            "'¿qué me está faltando?' o '¿qué tengo que pedirle al proveedor?'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "productos_menor_margen",
        "description": (
            "Devuelve los productos con el margen de ganancia % más bajo "
            "(precio de venta vs costo promedio). Usar para '¿qué producto "
            "me deja menos ganancia?' o '¿a qué precios debería revisar?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limite": {
                    "type": "integer",
                    "description": "Cuántos productos devolver, máximo 20. Por defecto 5.",
                }
            },
        },
    },
    {
        "name": "valor_inventario",
        "description": (
            "Devuelve el capital total inmovilizado en inventario (a costo "
            "promedio), agrupado por categoría. Usar para '¿cuánto tengo "
            "invertido en inventario?' o '¿cuánto vale mi bodega?'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _empresa_actual():
    # Sistema de una sola empresa por instalación (mismo patrón que las
    # demás vistas del ERP: core/views.py usa Empresa.objects.first()).
    return Empresa.objects.first()


def _num(valor):
    """Decimal/None -> algo serializable en JSON."""
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def ejecutar_herramienta(nombre, entrada):
    """Corre la herramienta pedida y devuelve un dict JSON-serializable.
    Si algo falla o no hay empresa configurada, devuelve un error legible
    en vez de reventar — Claude lo puede explicar al usuario."""
    empresa = _empresa_actual()
    if empresa is None:
        return {"error": "Todavía no hay una empresa configurada en el sistema."}

    try:
        if nombre == "indicadores_del_negocio":
            d = indicadores(empresa)
            return {
                "ventas_hoy": _num(d["ventas_hoy"]),
                "ventas_mes": _num(d["ventas_mes"]),
                "margen_utilidad_mes_pct": _num(round(d["margen"], 1)) if d["margen"] is not None else None,
                "variacion_vs_mes_anterior_pct": _num(round(d["variacion_mes"], 1)),
                "caja_abierta": d["caja_abierta"],
                "saldo_caja_esperado": _num(d["saldo_caja"]),
                "total_por_cobrar_clientes": _num(d["cxc_total"]),
                "productos_con_stock_bajo": d["num_stock_bajo"],
                "moneda": empresa.moneda,
            }

        if nombre == "productos_mas_vendidos":
            limite = min(int(entrada.get("limite", 5) or 5), 20)
            r = rep.mas_vendidos(empresa, limite=limite)
            return {
                "periodo": f"{r['desde'].isoformat()} a {r['hasta'].isoformat()}",
                "productos": [
                    {
                        "nombre": f["producto__nombre"],
                        "sku": f["producto__sku"],
                        "unidades_vendidas": _num(f["unidades"]),
                        "ingreso": _num(f["ingreso"]),
                    }
                    for f in r["filas"]
                ],
            }

        if nombre == "productos_stock_bajo":
            r = rep.niveles_stock(empresa, solo_bajo=True)
            return {
                "cantidad": r["num_bajo"],
                "productos": [
                    {
                        "nombre": p.nombre,
                        "sku": p.sku,
                        "stock_actual": _num(p.stock_actual),
                        "stock_minimo": _num(p.stock_minimo),
                    }
                    for p in r["productos"][:30]
                ],
            }

        if nombre == "productos_menor_margen":
            from catalogo.models import Producto

            limite = min(int(entrada.get("limite", 5) or 5), 20)
            productos = Producto.objects.filter(empresa=empresa, activo=True)
            con_margen = [(p, p.margen_pct) for p in productos if p.margen_pct is not None]
            con_margen.sort(key=lambda t: t[1])
            return {
                "productos": [
                    {
                        "nombre": p.nombre,
                        "sku": p.sku,
                        "margen_pct": _num(m),
                        "precio_venta": _num(p.precio_venta),
                        "costo_promedio": _num(p.costo_promedio),
                    }
                    for p, m in con_margen[:limite]
                ],
            }

        if nombre == "valor_inventario":
            r = rep.valor_inventario(empresa)
            return {
                "valor_total": _num(r["total_valor"]),
                "unidades_totales": _num(r["total_unidades"]),
                "num_productos": r["num_productos"],
                "por_categoria": [
                    {
                        "categoria": g["categoria"],
                        "valor": _num(g["valor"]),
                        "unidades": _num(g["unidades"]),
                        "items": g["items"],
                    }
                    for g in r["filas"]
                ],
            }

        return {"error": f"Herramienta desconocida: {nombre}"}
    except Exception as e:  # nunca reventar el chat por un dato raro
        return {"error": f"No se pudo consultar '{nombre}': {e}"}
