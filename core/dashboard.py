"""Indicadores del dashboard, calculados desde los datos reales.

El monitor del RTS es clave: al superar el límite de compras anuales (186
salarios base) la empresa sale del régimen simplificado y entra la
facturación electrónica v4.4 obligatoria. El sistema avisa ANTES.
"""
import os
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q
from django.utils import timezone

# Salario base: cambia cada año (decreto del Poder Judicial). Se puede
# actualizar sin tocar el código con la variable de entorno SALARIO_BASE;
# el valor por defecto es el de 2026. RECORDATORIO: revisar cada enero.
SALARIO_BASE = Decimal(os.environ.get("SALARIO_BASE", "462200"))
LIMITE_RTS_SALARIOS = 186
UMBRAL_ALERTA = Decimal("80")  # porcentaje: avisa al llegar al 80% del límite


def indicadores(empresa):
    from caja.services import monto_esperado
    from caja.models import SesionCaja
    from catalogo.models import Producto
    from compras.models import Compra
    from ventas.models import Cliente, FacturaVenta, LineaVenta

    hoy = timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    inicio_anio = hoy.replace(month=1, day=1)
    hace_7_dias = hoy - timedelta(days=7)

    ventas_emitidas = FacturaVenta.objects.filter(empresa=empresa, estado="EMI")
    ventas_hoy = ventas_emitidas.filter(creado_en__date=hoy).aggregate(t=Sum("total"))["t"] or Decimal("0")
    ventas_mes = ventas_emitidas.filter(creado_en__date__gte=inicio_mes).aggregate(t=Sum("total"))["t"] or Decimal("0")
    ventas_mes_anterior = ventas_emitidas.filter(
        creado_en__date__gte=(inicio_mes - timedelta(days=30)), creado_en__date__lt=inicio_mes
    ).aggregate(t=Sum("total"))["t"] or Decimal("0")

    # Utilidad bruta del mes = ventas - costo de lo vendido (a costo promedio).
    lineas_mes = LineaVenta.objects.filter(
        factura__empresa=empresa, factura__estado="EMI", factura__creado_en__date__gte=inicio_mes
    )
    costo_mes = sum((l.costo_unitario * l.cantidad for l in lineas_mes), Decimal("0"))
    utilidad_mes = ventas_mes - costo_mes
    margen = (utilidad_mes / ventas_mes * 100) if ventas_mes else Decimal("0")

    # Tendencia últimos 7 días
    ventas_ultimos_7 = []
    for i in range(7, -1, -1):
        fecha = hoy - timedelta(days=i)
        v = ventas_emitidas.filter(creado_en__date=fecha).aggregate(t=Sum("total"))["t"] or Decimal("0")
        ventas_ultimos_7.append(float(v))

    # Top 5 productos más vendidos del mes
    top_productos = LineaVenta.objects.filter(
        factura__empresa=empresa, factura__estado="EMI", factura__creado_en__date__gte=inicio_mes
    ).values('producto__nombre').annotate(cant=Sum('cantidad')).order_by('-cant')[:5]

    caja_abierta = SesionCaja.objects.filter(empresa_sucursal(empresa), estado="ABI").first()
    saldo_caja = monto_esperado(caja_abierta) if caja_abierta else Decimal("0")

    cxc_total = Cliente.objects.filter(empresa=empresa).aggregate(t=Sum("saldo"))["t"] or Decimal("0")

    productos = Producto.objects.filter(empresa=empresa, activo=True)
    stock_bajo = [p for p in productos if p.stock_actual <= p.stock_minimo]
    valor_inventario = sum((p.stock_actual * p.costo_promedio for p in productos), Decimal("0"))

    # Monitor RTS
    limite = SALARIO_BASE * LIMITE_RTS_SALARIOS
    compras_anio = Compra.objects.filter(
        empresa=empresa, estado="REC", recibida_en__date__gte=inicio_anio
    ).aggregate(t=Sum("total"))["t"] or Decimal("0")
    pct_rts = (compras_anio / limite * 100) if limite else Decimal("0")

    # Conteo de transacciones de hoy
    num_transacciones_hoy = ventas_emitidas.filter(creado_en__date=hoy).count()

    # Variación de ventas mes vs mes anterior
    variacion_mes = ((ventas_mes - ventas_mes_anterior) / ventas_mes_anterior * 100) if ventas_mes_anterior else Decimal("0")

    return {
        "ventas_hoy": ventas_hoy,
        "ventas_mes": ventas_mes,
        "ventas_ultimos_7": ventas_ultimos_7,
        "top_productos": top_productos,
        "utilidad_mes": utilidad_mes,
        "margen": margen,
        "variacion_mes": variacion_mes,
        "saldo_caja": saldo_caja,
        "caja_abierta": caja_abierta is not None,
        "cxc_total": cxc_total,
        "stock_bajo": stock_bajo,
        "num_stock_bajo": len(stock_bajo),
        "valor_inventario": valor_inventario,
        "compras_anio": compras_anio,
        "limite_rts": limite,
        "pct_rts": pct_rts,
        "alerta_rts": pct_rts >= UMBRAL_ALERTA,
        "es_rts": empresa.regimen == empresa.Regimen.SIMPLIFICADO,
        "num_transacciones_hoy": num_transacciones_hoy,
    }


def empresa_sucursal(empresa):
    """Filtro por sucursales de la empresa, para SesionCaja."""
    from django.db.models import Q
    return Q(sucursal__empresa=empresa)
