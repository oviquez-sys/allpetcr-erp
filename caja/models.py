from django.conf import settings
from django.db import models

from core.models import Sucursal


class SesionCaja(models.Model):
    """Turno de caja: abre con un monto contado, acumula movimientos y
    cierra con arqueo (contado vs. esperado). Inmutable tras el cierre."""

    class Estado(models.TextChoices):
        ABIERTA = "ABI", "Abierta"
        CERRADA = "CER", "Cerrada"

    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="sesiones_caja")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sesiones_caja")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.ABIERTA)
    monto_apertura = models.DecimalField(max_digits=12, decimal_places=2)
    abierta_en = models.DateTimeField(auto_now_add=True)
    monto_esperado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_contado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    cerrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="cajas_cerradas")
    # Arqueo de lo que NO es efectivo (auditoría 26/09/2026, CAJ-02). Lo
    # esperado sale de las ventas de la sesión; lo "según comprobante" lo anota
    # quien cierra: el total del cierre del datáfono y lo que de verdad entró
    # por SINPE. Vacío = no se revisó (no se inventa un cero).
    tarjeta_esperado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tarjeta_contado = models.DecimalField("tarjeta según datáfono", max_digits=12, decimal_places=2,
                                          null=True, blank=True)
    sinpe_esperado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sinpe_contado = models.DecimalField("SINPE recibido", max_digits=12, decimal_places=2, null=True, blank=True)
    # Cuántos billetes y monedas de cada uno se contaron al cerrar (14/10/2026),
    # p. ej. {"20000": 2, "1000": 7, "100": 12}. monto_contado es su suma.
    # Vacío en los cierres anteriores a este cambio.
    conteo_efectivo = models.JSONField("billetes y monedas contados", null=True, blank=True)
    # Cierre que no calza (02/11/2026, pedido de Oscar). Si quien cierra vio
    # la diferencia y prefirió volver a contar, el primer conteo NO se pierde:
    # queda aquí, en orden ([{"efectivo": .., "tarjeta": .., "sinpe": .., "en": iso}]).
    # Recontar es legítimo (un billete pegado, una suma mal hecha); lo que no
    # puede pasar es que el conteo se "acomode" al esperado sin dejar rastro.
    conteos_previos = models.JSONField("conteos anteriores al definitivo", null=True, blank=True)
    # A quién se le avisó la diferencia y si el correo salió. Vacío = el
    # cierre calzó y no hubo nada que avisar.
    aviso_diferencia = models.CharField("aviso de diferencia", max_length=300, blank=True)

    class Meta:
        verbose_name = "sesión de caja"
        verbose_name_plural = "sesiones de caja"
        ordering = ["-abierta_en"]

    def __str__(self):
        return f"Caja #{self.pk} — {self.usuario.username} ({self.get_estado_display()})"

    def desglose(self):
        """[(valor, cantidad, subtotal)] de lo contado, de mayor a menor."""
        conteo = self.conteo_efectivo or {}
        filas = [(int(v), int(n)) for v, n in conteo.items() if int(n)]
        return [(v, n, v * n) for v, n in sorted(filas, reverse=True)]


class MovimientoCaja(models.Model):
    """Movimiento de efectivo dentro de una sesión. Monto con signo:
    positivo entra, negativo sale. Inmutable."""

    class Tipo(models.TextChoices):
        APERTURA = "APE", "Apertura"
        VENTA = "VEN", "Venta en efectivo"
        INGRESO = "ING", "Ingreso manual"
        EGRESO = "EGR", "Egreso manual"
        ANULACION = "ANU", "Devolución por anulación"
        # 02/11/2026, pedido de Oscar: la gaveta se mantiene bajo ₡50-60 mil;
        # lo que pasa de ahí se saca para depositar (ver RetiroCaja).
        RETIRO = "RET", "Retiro para depositar"
        # Una venta registrada con un medio que se cobró con otro (iba con
        # efectivo y pagó con tarjeta, o al revés): ver ventas/medio_pago.py.
        CORRECCION = "COR", "Corrección de medio de pago"

    sesion = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    descripcion = models.CharField(max_length=200, blank=True)
    referencia = models.CharField(max_length=40, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de caja"
        verbose_name_plural = "movimientos de caja"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(monto=0), name="monto_caja_distinto_de_cero"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.monto} ({self.referencia})"


class RetiroCaja(models.Model):
    """Efectivo que se saca de la gaveta para depositarlo después
    (02/11/2026, pedido de Oscar: "a la caja le vamos a estar sacando para
    mantener menos de unos 50-60 mil; hoy le saqué 50.000 en billetes de 20 y
    10 que se depositarán a la cuenta del BN otro día").

    Al sacarlo se crea un MovimientoCaja negativo (tipo RET), así lo esperado
    del cierre ya lo descuenta y la caja calza. La plata sigue siendo de la
    empresa —en un sobre— hasta que se deposita: por eso el retiro queda
    "por depositar" y se marca "depositado" con el número de comprobante, que
    es cuando se hace el asiento Bancos contra Caja.

    No tiene llave foránea a MovimientoCaja A PROPÓSITO: esa tabla es de solo
    agregar (endurecer_documentos le quita UPDATE en PostgreSQL) y una FK
    hacia ella exige UPDATE para el bloqueo de cada INSERT. Se enlazan por la
    referencia "RET-<id>"."""

    class Estado(models.TextChoices):
        POR_DEPOSITAR = "PEN", "Por depositar"
        DEPOSITADO = "DEP", "Depositado"

    sesion = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name="retiros")
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    conteo = models.JSONField("billetes y monedas", null=True, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                related_name="retiros_caja")
    creado_en = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.POR_DEPOSITAR)
    depositado_en = models.DateField(null=True, blank=True)
    comprobante = models.CharField("número de comprobante del depósito", max_length=60, blank=True)
    depositado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="depositos_caja")

    class Meta:
        verbose_name = "retiro de caja"
        verbose_name_plural = "retiros de caja"
        ordering = ["-creado_en"]
        constraints = [models.CheckConstraint(condition=models.Q(monto__gt=0), name="retiro_positivo")]

    def __str__(self):
        return f"{self.referencia} ₡{self.monto} ({self.get_estado_display()})"

    @property
    def referencia(self):
        return f"RET-{self.pk}"

    def desglose(self):
        conteo = self.conteo or {}
        filas = [(int(v), int(n)) for v, n in conteo.items() if int(n)]
        return [(v, n, v * n) for v, n in sorted(filas, reverse=True)]


class DiferenciaCaja(models.Model):
    """Lo que no calzó en un cierre, por medio de pago, y por qué
    (02/11/2026, pedido de Oscar).

    Una fila por medio con diferencia (efectivo, tarjeta o SINPE). Quien
    cierra tiene que explicarla para poder cerrar: "la clienta iba a pagar
    con tarjeta y al final hizo un SINPE" son cosas que pasan, y quedan
    escritas en vez de quedar como un faltante sin dueño. Inmutable, igual
    que la sesión."""

    class Medio(models.TextChoices):
        EFECTIVO = "EFE", "Efectivo"
        TARJETA = "TAR", "Tarjeta"
        SINPE = "SIN", "SINPE Móvil"

    class Motivo(models.TextChoices):
        CRUCE = "CRU", "Se cobró por otro medio (p. ej. iba con tarjeta y pagó por SINPE)"
        VUELTO = "VUE", "Error al dar el vuelto"
        SIN_REGISTRAR = "SRG", "Se cobró algo que no se registró en el sistema"
        GASTO = "GAS", "Se sacó efectivo sin registrarlo (gasto, compra, cambio)"
        BANCO = "BAN", "El datáfono o el banco todavía no lo muestra"
        NO_SE_SABE = "NSS", "No se sabe por qué"
        OTRO = "OTR", "Otro motivo"

    sesion = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name="diferencias")
    medio = models.CharField(max_length=3, choices=Medio.choices)
    esperado = models.DecimalField(max_digits=12, decimal_places=2)
    contado = models.DecimalField(max_digits=12, decimal_places=2)
    diferencia = models.DecimalField(max_digits=12, decimal_places=2, help_text="Contado − esperado: negativo = falta")
    motivo = models.CharField(max_length=3, choices=Motivo.choices, blank=True)
    explicacion = models.CharField("explicación", max_length=300, blank=True)

    class Meta:
        verbose_name = "diferencia de cierre"
        verbose_name_plural = "diferencias de cierre"
        ordering = ["sesion", "medio"]
        constraints = [
            models.UniqueConstraint(fields=["sesion", "medio"], name="una_diferencia_por_medio"),
            models.CheckConstraint(condition=~models.Q(diferencia=0), name="diferencia_distinta_de_cero"),
        ]

    def __str__(self):
        return f"Caja #{self.sesion_id} — {self.get_medio_display()}: {self.diferencia}"

    @property
    def justificada(self):
        return bool(self.motivo and self.explicacion.strip())
