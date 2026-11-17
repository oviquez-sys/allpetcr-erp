"""Demostración de una campaña con datos ficticios.

Para ver las pantallas llenas ANTES de activar la campaña de verdad: quién
participa, la lista, el sorteo (se puede pulsar), el acta y la medición.

Qué toca y qué no
-----------------
- Crea una campaña marcada `es_demo`, que nunca es «la vigente»: no da
  números en ventas reales, no frena cupones y no aparece en la API.
- Crea clientes ficticios INACTIVOS (nombre «DEMO · …», teléfonos 0000-00xx):
  no salen en la caja, ni en Manada, ni en los reportes.
- NO crea ventas, ni mueve inventario, ni caja, ni contabilidad. Las compras
  de la demostración son solo filas de números con un documento «DEMO-…».
- «Borrar demostración» quita todo lo anterior.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from pedidos.models import PedidoPorConfirmar
from ventas.models import Cliente

from . import plantillas
from .models import (Adjudicacion, Campana, EntregaPremio, MovimientoNumeros, NumerosVenta, Participante,
                     Sorteo)

SLUG = "demo-navidad"
PREFIJO = "DEMO · "

# (nombre, canal de inscripción, origen de la visita, cliente nuevo, compras [(monto, canal, envío)])
_PERSONAS = [
    ("María Pérez", "WEB", "qr-tarjeta", True, [(8000, "TIE", 0), (25000, "TIE", 0), (30000, "WEB", 2500)]),
    ("Juan Mora", "TIE", "", False, [(20000, "TIE", 0)]),
    ("Ana Solís", "WEB", "instagram / navidad", True, [(42500, "WEB", 2500)]),
    ("Carlos Vargas", "TIE", "", True, []),
    ("Laura Jiménez", "WEB", "qr-tarjeta", True, [(12900, "TIE", 0), (21500, "TIE", 0)]),
    ("Pedro Rojas", "WEB", "", False, [(5900, "TIE", 0)]),
    ("Sofía Castro", "TIE", "", True, [(64900, "TIE", 0)]),
    ("Diego Araya", "WEB", "qr-tarjeta", True, []),
    ("Valeria Méndez", "WEB", "instagram / navidad", False, [(23900, "WEB", 0)]),
    ("Andrés Quesada", "TIE", "", False, [(3500, "TIE", 0), (4200, "TIE", 0), (20001, "TIE", 0)]),
    ("Gabriela Núñez", "WEB", "whatsapp", True, []),
    ("Luis Chaves", "TIE", "", True, [(31000, "TIE", 0)]),
    ("Paola Ureña", "WEB", "qr-tarjeta", True, [(19990, "WEB", 0)]),
    ("Esteban Salas", "WEB", "", True, []),
]


@transaction.atomic
def borrar(empresa):
    campanas = Campana.objects.filter(empresa=empresa, es_demo=True)
    clientes = list(Participante.objects.filter(campana__in=campanas).values_list("cliente_id", flat=True))
    EntregaPremio.objects.filter(sorteo__campana__in=campanas).delete()
    Adjudicacion.objects.filter(sorteo__campana__in=campanas).delete()
    Sorteo.objects.filter(campana__in=campanas).delete()
    MovimientoNumeros.objects.filter(campana__in=campanas).delete()
    NumerosVenta.objects.filter(campana__in=campanas).delete()
    Participante.objects.filter(campana__in=campanas).delete()
    PedidoPorConfirmar.objects.filter(empresa=empresa, clave__startswith="demo-").delete()
    campanas.delete()
    # Solo los clientes que la demostración creó (inactivos y con su marca).
    Cliente.objects.filter(pk__in=clientes, activo=False, nombre__startswith=PREFIJO).delete()


@transaction.atomic
def crear(empresa):
    """Vuelve a armar la demostración desde cero. Queda con las inscripciones
    cerradas hace un rato y la hora del sorteo ya cumplida, para poder pulsar
    «Congelar» y «Sortear» y ver el acta."""
    from . import reglas

    borrar(empresa)
    ahora = timezone.now()
    inicio = ahora - timedelta(days=35)
    base = plantillas.navidad_2026(empresa)
    campana = Campana.objects.create(
        empresa=empresa, es_demo=True, estado=Campana.Estado.ACTIVA, slug=SLUG,
        nombre="DEMOSTRACIÓN — Navidad AllPet", premio=base["premio"],
        inicio=inicio, cierre=ahora - timedelta(hours=1), sorteo_en=ahora - timedelta(minutes=30),
        envio_gratis_hasta=ahora, suplentes=2, plazo_reclamo_dias=5,
        bases=base["bases"], costo_impresion=Decimal("45000"), costo_reparto=Decimal("20000"),
    )
    azar = random.Random(2026)   # siempre la misma demostración
    for i, (nombre, canal, origen, nuevo, compras) in enumerate(_PERSONAS, 1):
        cliente = Cliente.objects.create(
            empresa=empresa, nombre=f"{PREFIJO}{nombre}", telefono=f"0000-00{i:02d}", activo=False,
            notas="Cliente ficticio de la demostración de campañas. Se borra con la demostración.",
        )
        momento = inicio + timedelta(days=azar.randint(0, 20), hours=azar.randint(9, 18))
        participante, _ = reglas.inscribir(
            campana=campana, cliente=cliente, canal=canal, origen_visita=origen, cliente_nuevo=nuevo,
            miembro_nuevo=nuevo, momento=momento,
        )
        Participante.objects.filter(pk=participante.pk).update(creado_en=momento)
        for j, (monto, canal_compra, envio) in enumerate(compras, 1):
            fecha = momento + timedelta(days=j * azar.randint(2, 6))
            monto = Decimal(monto)
            documento = f"DEMO-{i:02d}{j}"
            venta = reglas._crear_numeros(campana, participante, documento=documento, canal=canal_compra,
                                               monto=monto, fecha=fecha,
                                               margen=(monto / Decimal("1.13") * Decimal("0.24")).quantize(Decimal("1")))
            if canal_compra == "WEB" and venta is not None:
                PedidoPorConfirmar.objects.create(
                    empresa=empresa, numero=f"DEMO-WEB-{i:02d}{j}", clave=f"demo-{campana.pk}-{i}-{j}",
                    estado=PedidoPorConfirmar.Estado.CONCRETADO, cliente_nombre=cliente.nombre,
                    cliente_telefono=cliente.telefono, cliente=cliente,
                    entrega="ENV" if envio else "RET", canton="Heredia" if envio else "",
                    subtotal_productos=monto, envio_gratis=bool(envio), envio_costo=Decimal(envio),
                    concretado_en=fecha, origen_visita=origen,
                )
    return campana
