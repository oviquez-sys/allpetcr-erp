"""Registra la compra del inventario inicial para el monitor RTS y el D-105.

Contexto: el inventario se cargó con `importar_inventario` como movimientos de
kardex tipo CARGA_INICIAL (INI). Eso subió el stock, pero NO dejó un registro de
Compra, así que el monitor del régimen simplificado y el reporte de IVA
trimestral mostraban ₡0 de compras.

Este comando crea UN registro de Compra (recibida) por el valor a costo del
inventario inicial, con la fecha real en que se compró. Deliberadamente:
  - NO vuelve a mover el inventario (el stock ya está cargado por los INI).
  - NO genera asiento contable (para no duplicar el inventario ya registrado).
Su único fin es que las compras del año aparezcan correctamente en el monitor
RTS y en la declaración D-105 del trimestre correspondiente.

Uso (valores por defecto: junio 2026, monto = suma de la carga inicial):
    python manage.py registrar_compra_inicial
    python manage.py registrar_compra_inicial --fecha 2026-06-30 --monto 1303502

Idempotente: si ya existe la compra de apertura (mismo número), no la duplica.
"""
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from compras.models import Compra, Proveedor
from core.models import Empresa, Sucursal
from inventario.models import MovimientoInventario

NUMERO_APERTURA = "APERTURA-2026"


class Command(BaseCommand):
    help = "Registra la compra del inventario inicial (para el monitor RTS y el D-105)."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", default="2026-06-30",
                            help="Fecha real de la compra (AAAA-MM-DD). Por defecto 2026-06-30.")
        parser.add_argument("--monto", default=None,
                            help="Monto a costo. Por defecto: suma de la carga inicial (INI).")
        parser.add_argument("--numero", default=NUMERO_APERTURA,
                            help=f"Número del documento. Por defecto {NUMERO_APERTURA}.")

    @transaction.atomic
    def handle(self, *args, **opts):
        empresa = Empresa.objects.first()
        if empresa is None:
            raise CommandError("No hay empresa configurada. Corré importar_inventario primero.")
        sucursal = Sucursal.objects.filter(empresa=empresa).first()
        if sucursal is None:
            raise CommandError("La empresa no tiene sucursal.")

        numero = opts["numero"]
        if Compra.objects.filter(numero=numero).exists():
            self.stdout.write(self.style.WARNING(
                f"Ya existe la compra de apertura «{numero}». No se duplica."
            ))
            return

        try:
            fecha = datetime.strptime(opts["fecha"], "%Y-%m-%d").date()
        except ValueError:
            raise CommandError("Fecha inválida. Usá el formato AAAA-MM-DD, por ejemplo 2026-06-30.")

        if opts["monto"] is not None:
            monto = Decimal(str(opts["monto"])).quantize(Decimal("0.01"))
        else:
            # Valor a costo de la carga inicial: suma de cantidad × costo de los INI.
            monto = Decimal("0")
            for m in MovimientoInventario.objects.filter(tipo="INI"):
                monto += (m.cantidad * m.costo_unitario)
            monto = monto.quantize(Decimal("0.01"))

        if monto <= 0:
            raise CommandError("El monto de la carga inicial es 0. Nada que registrar.")

        proveedor, _ = Proveedor.objects.get_or_create(
            empresa=empresa, nombre="Inventario inicial (saldo de apertura)",
            defaults={"notas": "Proveedor técnico para registrar el inventario con que arrancó el sistema."},
        )

        # Fecha con hora, en la zona local, para que caiga en el día correcto.
        recibida = timezone.make_aware(datetime.combine(fecha, datetime.min.time().replace(hour=12)))

        Compra.objects.create(
            empresa=empresa,
            sucursal=sucursal,
            proveedor=proveedor,
            numero=numero,
            factura_proveedor="Saldo de apertura",
            estado=Compra.Estado.RECIBIDA,
            forma_pago=Compra.Pago.CONTADO,
            total=monto,
            recibida_en=recibida,
        )

        self.stdout.write(self.style.SUCCESS(
            f"Compra de apertura registrada: ₡{monto:,.2f} con fecha {fecha:%d/%m/%Y} "
            f"(trimestre {((fecha.month - 1) // 3) + 1}). "
            "No se tocó el inventario ni la contabilidad; solo cuenta para el monitor RTS y el D-105."
        ))
