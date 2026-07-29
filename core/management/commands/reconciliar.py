"""Reconciliación: verifica que los campos denormalizados (cachés de lectura
rápida) sigan cuadrando con su fuente de verdad en los libros.

Es una RED DE SEGURIDAD de solo lectura: NO corrige nada, solo reporta las
diferencias. Si todo cuadra, sale en verde. Si algo no cuadra, muestra qué
registro, cuánto tiene guardado y cuánto deberían decir los libros.

Campos que revisa:
  - Producto.stock_actual   vs  suma del kardex (MovimientoInventario)
  - DocumentoCxC.saldo      vs  monto_original menos abonos
  - Cliente.saldo           vs  suma de los saldos de sus CxC pendientes
  - Proveedor.saldo         vs  compras a crédito recibidas menos anuladas

Uso:
    python manage.py reconciliar
    python manage.py reconciliar --verbose     (lista también lo que SÍ cuadra)

Recomendación: correrlo periódicamente (p. ej. semanal, o antes de cada
cierre de mes). Si aparece una diferencia, NO la corrijas a mano: avisá para
investigar de dónde salió antes de tocar nada.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import ChequeoIntegridad


class Command(BaseCommand):
    help = "Verifica (solo lectura) que los saldos/stock denormalizados cuadren con los libros."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose", action="store_true",
            help="Muestra también los registros que cuadran, no solo los descuadrados.",
        )
        parser.add_argument(
            "--sin-guardar", action="store_true", dest="sin_guardar",
            help="No registra el resultado (para pruebas o corridas exploratorias).",
        )

    def handle(self, *args, **opciones):
        verbose = opciones["verbose"]
        self._descuadres = 0
        self._revisados = 0
        self._diferencias = []  # se guardan para que el dashboard las muestre

        self.stdout.write(self.style.MIGRATE_HEADING("Reconciliación de denormalizados vs. libros"))
        self.stdout.write("")

        self._revisar_stock(verbose)
        self._revisar_cxc(verbose)
        self._revisar_clientes(verbose)
        self._revisar_proveedores(verbose)

        self.stdout.write("")
        if self._descuadres == 0:
            self.stdout.write(self.style.SUCCESS(
                f"Todo cuadra. {self._revisados} registros revisados, 0 diferencias."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"{self._descuadres} diferencia(s) encontrada(s) de {self._revisados} "
                f"registros revisados. Revisá cada caso antes de corregir nada a mano."
            ))

        # Guardar el resultado (auditoría 2026-07-28, BE-04). Antes esto moría
        # en la consola: si nadie leía la salida, un descuadre de stock pasaba
        # inadvertido hasta que el POS bloqueara una venta de producto que sí
        # había. Ahora el gerente lo ve en el dashboard sin tener que saber
        # que este comando existe.
        if not opciones.get("sin_guardar"):
            ChequeoIntegridad.objects.create(
                revisados=self._revisados,
                descuadres=self._descuadres,
                detalle="\n".join(self._diferencias[:100]),  # tope: el dashboard no es un log
            )

    # --- utilidades ---
    def _ok(self, texto, verbose):
        if verbose:
            self.stdout.write(self.style.SUCCESS(f"  ok   {texto}"))

    def _mal(self, texto):
        self._descuadres += 1
        self._diferencias.append(texto)
        self.stdout.write(self.style.ERROR(f"  DIF  {texto}"))

    # --- 1. Stock de productos vs kardex ---
    def _revisar_stock(self, verbose):
        from catalogo.models import Producto
        from inventario.models import MovimientoInventario

        self.stdout.write("Producto.stock_actual vs kardex:")
        # Suma de cantidades del kardex por producto (una sola consulta).
        sumas = dict(
            MovimientoInventario.objects
            .values_list("producto_id")
            .annotate(t=Sum("cantidad"))
            .values_list("producto_id", "t")
        )
        for prod in Producto.objects.all().iterator():
            self._revisados += 1
            esperado = sumas.get(prod.id, Decimal("0")) or Decimal("0")
            if prod.stock_actual != esperado:
                self._mal(
                    f"[{prod.sku}] {prod.nombre}: guardado {prod.stock_actual}, "
                    f"kardex dice {esperado} (dif {prod.stock_actual - esperado})"
                )
            else:
                self._ok(f"[{prod.sku}] stock {prod.stock_actual}", verbose)

    # --- 2. Saldo de cada CxC vs monto_original - abonos ---
    def _revisar_cxc(self, verbose):
        from ventas.models import DocumentoCxC

        self.stdout.write("DocumentoCxC.saldo vs (monto_original - abonos):")
        for doc in DocumentoCxC.objects.all().iterator():
            self._revisados += 1
            abonado = doc.abonos.aggregate(t=Sum("monto"))["t"] or Decimal("0")
            esperado = doc.monto_original - abonado
            # Un documento ANULADO se deja en saldo 0 a propósito (la deuda se
            # canceló), así que no se compara contra monto_original - abonos.
            if doc.estado == DocumentoCxC.Estado.ANULADO:
                if doc.saldo != Decimal("0"):
                    self._mal(f"CxC {doc.factura.numero} ANULADO con saldo {doc.saldo} (debería ser 0)")
                else:
                    self._ok(f"CxC {doc.factura.numero} anulado, saldo 0", verbose)
                continue
            if doc.saldo != esperado:
                self._mal(
                    f"CxC {doc.factura.numero}: guardado {doc.saldo}, "
                    f"libros dicen {esperado} (dif {doc.saldo - esperado})"
                )
            else:
                self._ok(f"CxC {doc.factura.numero} saldo {doc.saldo}", verbose)

    # --- 3. Saldo del cliente vs suma de sus CxC pendientes ---
    def _revisar_clientes(self, verbose):
        from ventas.models import Cliente, DocumentoCxC

        self.stdout.write("Cliente.saldo vs suma de CxC pendientes:")
        for cli in Cliente.objects.all().iterator():
            self._revisados += 1
            esperado = (
                cli.cxc.filter(estado=DocumentoCxC.Estado.PENDIENTE)
                .aggregate(t=Sum("saldo"))["t"] or Decimal("0")
            )
            if cli.saldo != esperado:
                self._mal(
                    f"Cliente {cli.nombre}: guardado {cli.saldo}, "
                    f"CxC pendientes suman {esperado} (dif {cli.saldo - esperado})"
                )
            else:
                self._ok(f"Cliente {cli.nombre} saldo {cli.saldo}", verbose)

    # --- 4. Saldo del proveedor vs compras a crédito recibidas ---
    def _revisar_proveedores(self, verbose):
        from compras.models import Compra, Proveedor

        self.stdout.write("Proveedor.saldo vs compras a crédito recibidas:")
        for prov in Proveedor.objects.all().iterator():
            self._revisados += 1
            # El saldo del proveedor sube al recibir una compra a crédito y baja
            # al anularla. No hay (aún) flujo de pago a proveedor, así que el
            # esperado es el total de compras a crédito en estado RECIBIDA.
            esperado = (
                prov.compras.filter(
                    forma_pago=Compra.Pago.CREDITO, estado=Compra.Estado.RECIBIDA,
                ).aggregate(t=Sum("total"))["t"] or Decimal("0")
            )
            if prov.saldo != esperado:
                self._mal(
                    f"Proveedor {prov.nombre}: guardado {prov.saldo}, "
                    f"compras a crédito recibidas suman {esperado} (dif {prov.saldo - esperado})"
                )
            else:
                self._ok(f"Proveedor {prov.nombre} saldo {prov.saldo}", verbose)
