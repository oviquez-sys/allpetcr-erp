"""Medición de una campaña: qué trajo y cuánto costó.

Definiciones (lo que cada número quiere decir, y su límite)
-----------------------------------------------------------
- **Participantes únicos**: personas inscritas (una fila por cliente).
- **Canal de inscripción**: dónde se inscribió (web o tienda).
- **Origen de la visita**: de dónde llegó, si se supo (el QR de la tarjeta,
  Instagram…). Lo que no se supo se cuenta como «origen desconocido»; nunca
  se reparte ni se adivina.
- **Canal de compra**: tienda, o web cuando la venta cobró un pedido WEB-n
  (o vino de la pasarela).
- **Nuevos miembros**: quienes se unieron a La manada AL inscribirse.
- **Primera compra**: participante que nunca había comprado antes del inicio
  de la campaña y compró durante ella, ya inscrito.
- **Recompra a 30 / 60 días**: de esos, cuántos volvieron a comprar dentro de
  los 30 / 60 días siguientes a su primera compra. Solo se puede afirmar de
  quienes ya cumplieron ese plazo: el resto sale como «aún en plazo».
- **Ventas, margen**: de las compras de participantes que dieron números. NO
  es «lo que la campaña vendió de más»: parte de esa gente habría comprado
  igual. Es un techo, no una medición del efecto.
- **Costo de envíos**: lo que la tienda pagó por los envíos gratis.
- **Costo de la canasta**: el real si ya se entregó; si no, el estimado de la
  versión más cara con el costo promedio de hoy.
- **Costo por cliente nuevo**: costo total / primeras compras.
- **Margen de campaña**: margen de esas ventas − costo total.
"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Min, Sum
from django.utils import timezone

from .models import CanastaProducto, MovimientoNumeros, NumerosVenta, Participante
from .sorteo import costo_canasta

CERO = Decimal("0")


def _compras_de(cliente_ids):
    """{cliente_id: [fechas de compra]} con todas las compras reales (caja y
    pasarela) de esos clientes."""
    from pedidos.models import Pedido
    from ventas.models import FacturaVenta

    fechas = {c: [] for c in cliente_ids}
    for cliente, fecha in (FacturaVenta.objects.filter(cliente_id__in=cliente_ids, estado="EMI", total__gt=0)
                           .values_list("cliente_id", "creado_en")):
        fechas[cliente].append(fecha)
    for cliente, fecha in (Pedido.objects.filter(cliente_id__in=cliente_ids).exclude(estado="CAN")
                           .values_list("cliente_id", "creado_en")):
        fechas[cliente].append(fecha)
    return fechas


def _recompra(primeras, compras, dias, ahora):
    """De quienes hicieron su primera compra: cuántos ya cumplieron `dias`,
    cuántos de esos volvieron, y cuántos siguen en plazo."""
    evaluables = volvieron = en_plazo = 0
    for cliente, primera in primeras.items():
        limite = primera + timedelta(days=dias)
        volvio = any(primera < f <= limite for f in compras.get(cliente, []))
        if volvio:
            evaluables += 1
            volvieron += 1
        elif ahora >= limite:
            evaluables += 1
        else:
            en_plazo += 1
    pct = round(volvieron * 100 / evaluables) if evaluables else None
    return {"dias": dias, "evaluables": evaluables, "volvieron": volvieron, "en_plazo": en_plazo, "pct": pct}


def resumen(campana, ahora=None) -> dict:
    ahora = ahora or timezone.now()
    participantes = Participante.objects.filter(campana=campana)
    total = participantes.count()
    por_canal = dict(participantes.values_list("canal").annotate(n=Count("id")))
    origenes = Counter(p or "origen desconocido" for p in participantes.values_list("origen_visita", flat=True))

    ventas = NumerosVenta.objects.filter(campana=campana)
    por_compra = {}
    for canal, etiqueta in NumerosVenta.Canal.choices:
        filas = list(ventas.filter(canal=canal, monto_vigente__gt=0))
        por_compra[canal] = {
            "nombre": etiqueta, "cantidad": len(filas),
            "monto": sum((v.monto_vigente for v in filas), CERO),
            "margen": sum((v.margen_vigente for v in filas), CERO),
        }
    monto_ventas = sum((c["monto"] for c in por_compra.values()), CERO)
    margen_ventas = sum((c["margen"] for c in por_compra.values()), CERO)

    mov = dict(MovimientoNumeros.objects.filter(campana=campana).values_list("tipo").annotate(t=Sum("cantidad")))
    numeros = {
        "inscripcion": mov.get("INS", 0), "habituales": mov.get("COM", 0), "bono": mov.get("BON", 0),
        "revertidos": -mov.get("REV", 0), "ajustes": mov.get("AJU", 0),
    }
    numeros["vigentes"] = sum(mov.values())

    # Primeras compras y recompra.
    ids = list(participantes.values_list("cliente_id", flat=True))
    compras = _compras_de(ids)
    # En la demostración no hay facturas: sus compras son las filas de números.
    for cliente, fecha in ventas.filter(factura__isnull=True, pedido__isnull=True).values_list(
            "participante__cliente_id", "fecha"):
        compras.setdefault(cliente, []).append(fecha)
    primera_en_campana = dict(ventas.values_list("participante__cliente_id").annotate(f=Min("fecha")))
    primeras = {c: f for c, f in primera_en_campana.items()
                if not any(x < campana.inicio for x in compras.get(c, []))}

    # Costos.
    from pedidos.models import PedidoPorConfirmar
    con_envio = PedidoPorConfirmar.objects.filter(
        empresa=campana.empresa, estado="CON", envio_gratis=True,
        concretado_en__gte=campana.inicio, concretado_en__lte=campana.envio_hasta,
    )
    # Los pedidos de la demostración llevan su marca en la clave: solo los ve
    # la demostración, y una campaña real nunca los cuenta.
    marca = f"demo-{campana.pk}-"
    con_envio = (con_envio.filter(clave__startswith=marca) if campana.es_demo
                 else con_envio.exclude(clave__startswith="demo-"))
    envios = con_envio.aggregate(n=Count("id"), t=Sum("envio_costo"))
    costo_envios = envios["t"] or CERO
    entrega = getattr(getattr(campana, "sorteo", None), "entrega", None) if hasattr(campana, "sorteo") else None
    if entrega is not None:
        canasta, canasta_real = entrega.costo, True
    else:
        canasta = max((costo_canasta(campana, v) for v in CanastaProducto.Version.values), default=CERO)
        canasta_real = False
    costo_total = campana.costos_fijos + costo_envios + canasta

    def por(cantidad):
        return (costo_total / cantidad).quantize(Decimal("1")) if cantidad else None

    return {
        "participantes": total,
        "por_canal_inscripcion": [
            {"nombre": etiqueta, "cantidad": por_canal.get(canal, 0)} for canal, etiqueta in Participante.Canal.choices
        ],
        "origenes": [{"nombre": nombre, "cantidad": n} for nombre, n in origenes.most_common()],
        "nuevos_miembros": participantes.filter(miembro_nuevo=True).count(),
        "clientes_nuevos": participantes.filter(cliente_nuevo=True).count(),
        "con_compra": ventas.filter(monto_vigente__gt=0).values("participante").distinct().count(),
        "primeras_compras": len(primeras),
        "recompra": [_recompra(primeras, compras, 30, ahora), _recompra(primeras, compras, 60, ahora)],
        "por_canal_compra": list(por_compra.values()),
        "ventas_monto": monto_ventas,
        "ventas_margen": margen_ventas,
        "numeros": numeros,
        "envios_gratis": envios["n"] or 0,
        "costo_envios": costo_envios,
        "costo_canasta": canasta,
        "costo_canasta_real": canasta_real,
        "costo_impresion": campana.costo_impresion,
        "costo_reparto": campana.costo_reparto,
        "otros_costos": campana.otros_costos,
        "costo_total": costo_total,
        "costo_por_participante": por(total),
        "costo_por_cliente_nuevo": por(len(primeras)),
        "margen_campana": margen_ventas - costo_total,
    }
