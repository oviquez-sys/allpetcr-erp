"""Diferencias de cierre de caja, agregadas por cajero.

Por qué
-------
`cerrar_caja` ya calcula y guarda `diferencia` (contado − esperado) en cada
sesión. Nadie la mira nunca en conjunto, y ahí está el punto ciego: un
faltante de ₡500 en un cierre parece ruido — el vuelto de alguien, un billete
mal contado. El mismo faltante todos los días, siempre con el mismo usuario,
no es ruido.

Lo que hace este módulo es sumar, no acusar. La señal que importa no es el
total: es el **sesgo**. Diferencias que caen a los dos lados (a veces sobra, a
veces falta) son error de conteo, y son normales. Diferencias que caen siempre
del mismo lado son otra cosa, y merecen una conversación.

Por eso se devuelven por separado los cierres con faltante y los que tienen
sobrante, en vez de un promedio que los cancela entre sí — que es exactamente
la forma de no ver nada.
"""
import os
from decimal import Decimal

from django.db.models import Avg, Count, Max, Q, Sum
from django.utils import timezone

# Ventana de análisis por defecto.
DIAS_VENTANA = int(os.environ.get("ARQUEO_DIAS_VENTANA", "30"))

# Diferencia por debajo de la cual un cierre se considera cuadrado. No es cero
# a propósito: exigir el céntimo exacto genera ruido constante por redondeos
# de vuelto y entrena a ignorar la alerta.
TOLERANCIA = Decimal(os.environ.get("ARQUEO_TOLERANCIA", "100"))


def por_cajero(empresa, dias=None):
    """Resumen de las diferencias de arqueo por usuario en la ventana."""
    from caja.models import SesionCaja
    from datetime import timedelta

    dias = dias or DIAS_VENTANA
    desde = timezone.now() - timedelta(days=dias)

    sesiones = SesionCaja.objects.filter(
        sucursal__empresa=empresa,
        estado=SesionCaja.Estado.CERRADA,
        cerrada_en__gte=desde,
        diferencia__isnull=False,
    ).select_related("usuario")

    filas = (
        sesiones
        .values("usuario_id", "usuario__username")
        .annotate(
            cierres=Count("id"),
            total=Sum("diferencia"),
            promedio=Avg("diferencia"),
            ultimo=Max("cerrada_en"),
            # Faltantes y sobrantes por separado: un promedio los cancela
            # entre sí y esconde justo lo que se está buscando.
            faltantes=Count("id", filter=Q(diferencia__lt=-TOLERANCIA)),
            sobrantes=Count("id", filter=Q(diferencia__gt=TOLERANCIA)),
            monto_faltante=Sum("diferencia", filter=Q(diferencia__lt=-TOLERANCIA)),
            monto_sobrante=Sum("diferencia", filter=Q(diferencia__gt=TOLERANCIA)),
        )
        .order_by("total")
    )

    resultado = []
    for f in filas:
        cierres = f["cierres"] or 0
        faltantes = f["faltantes"] or 0
        sobrantes = f["sobrantes"] or 0
        descuadres = faltantes + sobrantes
        # Sesgo: qué proporción de los descuadres cae del lado del faltante.
        # Con pocos cierres no significa nada, por eso se informa junto al
        # número de cierres y no se convierte en una alerta automática.
        sesgo = (Decimal(faltantes) / Decimal(descuadres) * 100) if descuadres else None
        resultado.append({
            "usuario_id": f["usuario_id"],
            "usuario": f["usuario__username"],
            "cierres": cierres,
            "cuadrados": cierres - descuadres,
            "faltantes": faltantes,
            "sobrantes": sobrantes,
            "monto_faltante": f["monto_faltante"] or Decimal("0"),
            "monto_sobrante": f["monto_sobrante"] or Decimal("0"),
            "total": f["total"] or Decimal("0"),
            "promedio": f["promedio"] or Decimal("0"),
            "ultimo": f["ultimo"],
            "sesgo_faltante": sesgo,
            # Se marca para revisar cuando hay evidencia suficiente (al menos
            # 5 cierres) y los descuadres se van claramente para un lado.
            "revisar": cierres >= 5 and sesgo is not None and sesgo >= 75 and faltantes >= 3,
        })

    totales = sesiones.aggregate(
        cierres=Count("id"),
        total=Sum("diferencia"),
        faltantes=Count("id", filter=Q(diferencia__lt=-TOLERANCIA)),
        sobrantes=Count("id", filter=Q(diferencia__gt=TOLERANCIA)),
    )

    return {
        "filas": resultado,
        "dias": dias,
        "desde": desde,
        "tolerancia": TOLERANCIA,
        "cierres": totales["cierres"] or 0,
        "total": totales["total"] or Decimal("0"),
        "num_faltantes": totales["faltantes"] or 0,
        "num_sobrantes": totales["sobrantes"] or 0,
        "hay_revisar": any(f["revisar"] for f in resultado),
    }


def sesiones_descuadradas(empresa, dias=None, usuario_id=None):
    """Los cierres concretos que no cuadraron: la evidencia detrás del
    resumen. Sin esto el resumen es una acusación sin expediente."""
    from caja.models import SesionCaja
    from datetime import timedelta

    dias = dias or DIAS_VENTANA
    desde = timezone.now() - timedelta(days=dias)

    qs = SesionCaja.objects.filter(
        sucursal__empresa=empresa,
        estado=SesionCaja.Estado.CERRADA,
        cerrada_en__gte=desde,
        diferencia__isnull=False,
    ).exclude(
        diferencia__gte=-TOLERANCIA, diferencia__lte=TOLERANCIA
    ).select_related("usuario", "sucursal").order_by("-cerrada_en")

    if usuario_id:
        qs = qs.filter(usuario_id=usuario_id)
    return qs
