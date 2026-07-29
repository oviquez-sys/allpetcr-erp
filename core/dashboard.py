"""Indicadores del dashboard, calculados desde los datos reales.

El monitor del RTS es clave: al superar el límite de compras anuales (186
salarios base) la empresa sale del régimen simplificado y entra la
facturación electrónica v4.4 obligatoria. El sistema avisa ANTES.
"""
import os
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q, F, DecimalField
from django.db.models.functions import TruncDate
from django.utils import timezone

# Salario base: cambia cada año (decreto del Poder Judicial). Se puede
# actualizar sin tocar el código con la variable de entorno SALARIO_BASE;
# el valor por defecto es el de 2026. RECORDATORIO: revisar cada enero.
SALARIO_BASE = Decimal(os.environ.get("SALARIO_BASE", "462200"))
LIMITE_RTS_SALARIOS = 186
UMBRAL_ALERTA = Decimal("80")  # porcentaje: avisa al llegar al 80% del límite


# Segundos que se cachean los indicadores (auditoría 2026-07-28, PERF-03).
# Dos minutos: suficiente para que abrir el dashboard varias veces seguidas no
# recalcule ocho agregados, y poco para que las ventas del día se sientan al
# instante. Si se quiere ver el efecto de una venta ya, se recarga a los dos
# minutos — es el compromiso correcto para un tablero, no para el POS.
CACHE_INDICADORES_SEG = int(os.environ.get("DASHBOARD_CACHE_SEG", "120"))


def indicadores(empresa, usar_cache=True):
    """Indicadores del tablero, con caché corta.

    La caché es TOLERANTE a fallos a propósito: si la tabla de caché no existe
    todavía (falta `manage.py createcachetable`) o el backend falla, se calcula
    igual y el dashboard funciona. Un tablero que no abre porque la caché no
    está configurada sería un problema peor que el que la caché resuelve.
    """
    from django.core.cache import cache

    clave = f"dashboard:indicadores:{empresa.pk}"
    if usar_cache:
        try:
            en_cache = cache.get(clave)
        except Exception:  # noqa: BLE001 — la caché nunca debe tumbar el tablero
            en_cache = None
        if en_cache is not None:
            # El estado de integridad NO se cachea: es una alerta y tiene que
            # verse apenas cambia.
            return {**en_cache, **_estado_integridad()}

    datos = _calcular_indicadores(empresa)
    if usar_cache:
        try:
            cache.set(clave, datos, CACHE_INDICADORES_SEG)
        except Exception:  # noqa: BLE001
            pass  # sin caché el tablero sigue funcionando, solo más lento
    return {**datos, **_estado_integridad()}


def _calcular_indicadores(empresa):
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
    # El costo se suma EN LA BASE (no trayendo cada línea a memoria): a miles
    # de líneas de venta al mes, iterar en Python vuelve lenta la página.
    costo_mes = lineas_mes.aggregate(
        t=Sum(
            F("costo_unitario") * F("cantidad"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )["t"] or Decimal("0")
    utilidad_mes = ventas_mes - costo_mes
    margen = (utilidad_mes / ventas_mes * 100) if ventas_mes else Decimal("0")

    # Tendencia últimos 7 días: UNA consulta agrupada por día, no ocho
    # consultas en un bucle (una por fecha).
    totales_por_dia = dict(
        ventas_emitidas.filter(creado_en__date__gte=hace_7_dias)
        .annotate(dia=TruncDate("creado_en"))
        .values("dia")
        .annotate(t=Sum("total"))
        .values_list("dia", "t")
    )
    ventas_ultimos_7 = [
        float(totales_por_dia.get(hoy - timedelta(days=i)) or 0) for i in range(7, -1, -1)
    ]

    caja_abierta = SesionCaja.objects.filter(empresa_sucursal(empresa), estado="ABI").first()
    saldo_caja = monto_esperado(caja_abierta) if caja_abierta else Decimal("0")

    cxc_total = Cliente.objects.filter(empresa=empresa).aggregate(t=Sum("saldo"))["t"] or Decimal("0")

    # Stock bajo contado EN LA BASE: antes se cargaban todos los productos a
    # memoria para compararlos uno por uno.
    num_stock_bajo = (
        Producto.objects.filter(empresa=empresa, activo=True)
        .filter(stock_actual__lte=F("stock_minimo"))
        .count()
    )

    # Monitor RTS
    limite = SALARIO_BASE * LIMITE_RTS_SALARIOS
    compras_anio = Compra.objects.filter(
        empresa=empresa, estado="REC", recibida_en__date__gte=inicio_anio
    ).aggregate(t=Sum("total"))["t"] or Decimal("0")
    pct_rts = (compras_anio / limite * 100) if limite else Decimal("0")

    # Variación de ventas mes vs mes anterior
    variacion_mes = ((ventas_mes - ventas_mes_anterior) / ventas_mes_anterior * 100) if ventas_mes_anterior else Decimal("0")

    return {
        "ventas_hoy": ventas_hoy,
        "ventas_mes": ventas_mes,
        "ventas_ultimos_7": ventas_ultimos_7,
        "utilidad_mes": utilidad_mes,
        "margen": margen,
        "variacion_mes": variacion_mes,
        "saldo_caja": saldo_caja,
        "caja_abierta": caja_abierta is not None,
        "cxc_total": cxc_total,
        "num_stock_bajo": num_stock_bajo,
        "compras_anio": compras_anio,
        "limite_rts": limite,
        "pct_rts": pct_rts,
        "alerta_rts": pct_rts >= UMBRAL_ALERTA,
        "es_rts": empresa.regimen == empresa.Regimen.SIMPLIFICADO,
    }


# Días tras los cuales un chequeo de integridad deja de ser informativo.
# Una semana: si el stock se descuadró el lunes, no queremos enterarnos el mes
# siguiente, cuando ya se vendió con datos malos.
DIAS_CHEQUEO_VIGENTE = 7


def _estado_integridad():
    """Resumen del último `manage.py reconciliar`, para avisar en el dashboard.

    Devuelve dos alertas distintas a propósito:

    - `integridad_descuadres`: se encontraron diferencias entre el stock/saldo
      guardado y lo que dicen los libros. Es lo que hace que el POS bloquee
      ventas de producto que sí hay, o que el control de crédito autorice de
      más.
    - `integridad_vencida`: hace más de una semana que nadie corre el chequeo
      (o no se corrió nunca). No significa que algo esté mal: significa que no
      sabemos si algo está mal, que es una situación distinta y también hay
      que mostrarla.
    """
    from django.utils import timezone

    from .models import ChequeoIntegridad

    ultimo = ChequeoIntegridad.ultimo()
    if ultimo is None:
        return {
            "integridad_ultimo": None,
            "integridad_descuadres": 0,
            "integridad_vencida": True,
            "integridad_detalle": "",
        }
    dias = (timezone.now() - ultimo.fecha).days
    return {
        "integridad_ultimo": ultimo.fecha,
        "integridad_descuadres": ultimo.descuadres,
        "integridad_vencida": dias > DIAS_CHEQUEO_VIGENTE,
        "integridad_detalle": ultimo.detalle,
    }


def empresa_sucursal(empresa):
    """Filtro por sucursales de la empresa, para SesionCaja."""
    from django.db.models import Q
    return Q(sucursal__empresa=empresa)
