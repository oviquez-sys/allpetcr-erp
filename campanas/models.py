"""Campañas con sorteo (Navidad AllPet 2026, pedido de Oscar del 16/11/2026).

Qué es una campaña acá
----------------------
Una persona se inscribe gratis (en la web o en la caja) y entra al sorteo de
un premio. Cada inscripción y cada compra le dan NÚMEROS para el sorteo
—lo que la tarjeta impresa llama «puntaje»—:

- inscribirse: 1 número;
- cada compra de un inscrito: 1 número;
- si esa compra supera el umbral (₡20.000): 1 número más de bono.

Los números NO son plata ni puntos canjeables (decisión de Oscar, 16/11/2026:
«serían como los números de una rifa»). Por eso el sorteo es parejo POR
NÚMERO, no por persona: quien tiene 6 números tiene 6 veces la oportunidad
de quien tiene 1, y las bases lo tienen que decir.

Por qué se apoya en lo que ya existe
------------------------------------
- El participante ES un `ventas.Cliente` (y miembro de La manada): no hay una
  tercera tabla de personas que después nadie concilia.
- La venta es `ventas.FacturaVenta` (caja) o `pedidos.Pedido` (pasarela). El
  pedido web que se arregla por WhatsApp conserva su número
  (`pedidos.PedidoPorConfirmar`) hasta que se cobra en caja.
- La canasta se entrega como una venta de regalía (kardex REG + asiento de
  gasto de promoción): el mismo camino de cualquier regalo de la tienda.

Las reglas viven en `campanas/reglas.py` y el sorteo en `campanas/sorteo.py`.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from catalogo.models import Producto
from core.models import Empresa
from ventas.models import Cliente, FacturaVenta


class Campana(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BOR", "Borrador (apagada)"
        ACTIVA = "ACT", "Activa"
        CERRADA = "CER", "Cerrada (lista congelada)"
        SORTEADA = "SOR", "Sorteada"
        FINALIZADA = "FIN", "Finalizada"

    class Despues(models.TextChoices):
        # «Al finalizar, dejá configurable qué campaña sigue» (Oscar).
        BIENVENIDA = "BIE", "Vuelve el regalo de bienvenida de La manada"
        NADA = "NAD", "Queda sin regalo de bienvenida hasta que se decida"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="campanas")
    nombre = models.CharField(max_length=80)
    slug = models.SlugField(max_length=40, help_text="Nombre corto para enlaces y la API. Ej.: navidad-2026")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.BORRADOR)
    # La demostración vive en las mismas tablas pero nunca es «la vigente»:
    # no da números en ventas reales ni frena el cupón de bienvenida.
    es_demo = models.BooleanField("demostración con datos ficticios", default=False, editable=False)

    premio = models.CharField(
        max_length=200, default="Canasta de 15 productos (versión para perro o para gato, a elección)",
    )

    # Fechas: se guardan con zona y se muestran SIEMPRE en hora de Costa Rica
    # (TIME_ZONE del proyecto). El formulario las pide en esa hora.
    inicio = models.DateTimeField("inicio", help_text="Desde cuándo se puede inscribir y las compras dan números.")
    cierre = models.DateTimeField(
        "cierre de inscripciones",
        help_text="Último momento para inscribirse y para que una compra dé números.",
    )
    sorteo_en = models.DateTimeField("fecha y hora del sorteo")

    # Números para el sorteo.
    numeros_inscripcion = models.PositiveSmallIntegerField("números por inscribirse", default=1)
    numeros_compra = models.PositiveSmallIntegerField("números por cada compra", default=1)
    numeros_bono = models.PositiveSmallIntegerField("números extra si la compra supera el umbral", default=1)
    umbral_bono = models.DecimalField(
        "umbral del bono (₡)", max_digits=12, decimal_places=2, default=Decimal("20000"),
        help_text="La compra tiene que SUPERAR este monto. ₡20.000 exactos no ganan el bono.",
    )
    compra_minima = models.DecimalField(
        "compra mínima para dar número (₡)", max_digits=12, decimal_places=2, default=Decimal("0"),
        help_text="0 = cualquier compra da número. Subirlo evita que alguien parta una compra en muchas chiquitas.",
    )

    # Envío gratis de pedidos web.
    envio_gratis = models.BooleanField("envío gratis en pedidos web sobre el umbral", default=True)
    envio_gratis_hasta = models.DateTimeField(
        "envío gratis hasta", null=True, blank=True,
        help_text="Vacío = hasta el cierre de inscripciones.",
    )
    zonas_envio = models.TextField(
        "zonas con envío gratis", blank=True, default="Heredia / Heredia\nHeredia / Mercedes\nHeredia / San Francisco\nHeredia / Ulloa",
        help_text="Una por línea. Un cantón («Heredia») o cantón / distrito («Heredia / Mercedes»). "
                  "Se comparan sin tildes ni mayúsculas con lo que escribe el cliente en el pedido.",
    )

    # La campaña reemplaza el 10 % de bienvenida (los cupones ya emitidos se
    # respetan: esto solo frena los NUEVOS, ver manada.services).
    reemplaza_bienvenida = models.BooleanField(
        "mientras dure, no se emiten cupones de bienvenida nuevos", default=True,
    )
    despues = models.CharField("al finalizar", max_length=3, choices=Despues.choices, default=Despues.NADA)

    # Bases.
    bases = models.TextField(
        "bases de la campaña", blank=True,
        help_text="El texto completo que ve el cliente. La web lo publica tal cual.",
    )
    suplentes = models.PositiveSmallIntegerField(
        "suplentes previstos en las bases", default=0,
        help_text="0 = no hay suplentes. Solo se sortean si las bases los prevén.",
    )
    plazo_reclamo_dias = models.PositiveSmallIntegerField("días para reclamar el premio", default=5)
    procedimiento_sin_respuesta = models.TextField(
        "qué pasa si el ganador no responde", blank=True,
        default="Si la persona ganadora no reclama el premio dentro del plazo, pierde el derecho y el premio "
                "pasa al suplente que sigue. Si no quedan suplentes, el premio se declara desierto.",
    )

    # Costos que no salen de ninguna venta: se anotan para medir la campaña.
    costo_impresion = models.DecimalField("costo de impresión (₡)", max_digits=12, decimal_places=2, default=0)
    costo_reparto = models.DecimalField("costo de reparto de tarjetas (₡)", max_digits=12, decimal_places=2, default=0)
    otros_costos = models.DecimalField("otros costos (₡)", max_digits=12, decimal_places=2, default=0)

    activada_en = models.DateTimeField(null=True, blank=True, editable=False)
    activada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
                                     on_delete=models.SET_NULL, related_name="+")
    finalizada_en = models.DateTimeField(null=True, blank=True, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "campaña"
        verbose_name_plural = "campañas"
        ordering = ["-inicio", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "slug"], name="campana_slug_unico_por_empresa"),
            # Una sola campaña corriendo a la vez (sin contar la demostración):
            # así «la vigente» nunca es ambigua en la caja ni en la API.
            models.UniqueConstraint(
                fields=["empresa"], condition=models.Q(estado="ACT", es_demo=False),
                name="una_campana_activa_por_empresa",
            ),
        ]
        permissions = [
            # «Permití a un administrador autorizado seleccionar al ganador».
            # El superusuario lo tiene siempre; a un gerente se le da en el admin.
            ("sortear", "Puede congelar la lista y realizar el sorteo"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.get_estado_display()})"

    def clean(self):
        super().clean()
        if self.inicio and self.cierre and self.cierre <= self.inicio:
            raise ValidationError({"cierre": "El cierre tiene que ser después del inicio."})
        if self.cierre and self.sorteo_en and self.sorteo_en < self.cierre:
            raise ValidationError({"sorteo_en": "El sorteo no puede ser antes del cierre de inscripciones."})
        if self.umbral_bono is not None and self.umbral_bono <= 0:
            raise ValidationError({"umbral_bono": "El umbral tiene que ser mayor que cero."})
        if (self.compra_minima is not None and self.umbral_bono is not None
                and self.compra_minima > self.umbral_bono):
            raise ValidationError({"compra_minima": "La compra mínima no puede pasar del umbral del bono."})

    # --- en qué momento está -------------------------------------------------
    def acepta(self, momento=None) -> bool:
        """¿En `momento` se puede inscribir y una compra da números?"""
        momento = momento or timezone.now()
        return self.estado == self.Estado.ACTIVA and self.inicio <= momento <= self.cierre

    @property
    def envio_hasta(self):
        return self.envio_gratis_hasta or self.cierre

    def da_envio_gratis(self, momento=None) -> bool:
        momento = momento or timezone.now()
        return (self.envio_gratis and self.estado in (self.Estado.ACTIVA, self.Estado.CERRADA, self.Estado.SORTEADA)
                and self.inicio <= momento <= self.envio_hasta)

    @property
    def lista_zonas(self):
        return [z.strip() for z in (self.zonas_envio or "").splitlines() if z.strip()]

    @property
    def costos_fijos(self):
        return self.costo_impresion + self.costo_reparto + self.otros_costos


class Participante(models.Model):
    """Una persona inscrita en una campaña. Una sola vez por campaña."""

    class Canal(models.TextChoices):
        WEB = "WEB", "Sitio web"
        TIENDA = "TIE", "En la tienda"

    campana = models.ForeignKey(Campana, on_delete=models.PROTECT, related_name="participantes")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="participaciones")
    canal = models.CharField("se inscribió en", max_length=3, choices=Canal.choices)
    # De dónde llegó la visita, si se sabe: "qr-tarjeta", "instagram / navidad".
    # Vacío se muestra como «origen desconocido»; nunca se inventa.
    origen_visita = models.CharField(max_length=80, blank=True)
    # Aceptar las bases y aceptar publicidad son dos cosas distintas (Oscar:
    # «separá la inscripción del permiso para recibir publicidad»). Acá queda
    # la primera; la segunda vive en PerfilManada.acepta_promociones.
    acepto_bases_en = models.DateTimeField(default=timezone.now)
    # Para medir: ¿esta inscripción trajo a alguien que no estaba?
    cliente_nuevo = models.BooleanField(default=False, editable=False)
    miembro_nuevo = models.BooleanField(default=False, editable=False)
    inscrito_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+", help_text="Quién lo inscribió en caja (vacío = se inscribió solo en la web).")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "participante"
        verbose_name_plural = "participantes"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(fields=["campana", "cliente"], name="un_participante_por_campana_y_cliente"),
        ]

    def __str__(self):
        return f"{self.cliente.nombre} — {self.campana.nombre}"

    @property
    def origen_texto(self):
        return self.origen_visita or "origen desconocido"


class NumerosVenta(models.Model):
    """Lo que UNA venta le dio a un participante, tal como está hoy.

    Se crea una sola vez, cuando la venta se concreta, y se recalcula si la
    venta cambia (devolución, anulación, pedido cancelado). El detalle de
    cada cambio queda en `MovimientoNumeros`; acá está la foto vigente, que
    es lo que muestran la caja y el comprobante."""

    class Canal(models.TextChoices):
        TIENDA = "TIE", "Tienda"
        WEB = "WEB", "Web"

    campana = models.ForeignKey(Campana, on_delete=models.PROTECT, related_name="ventas")
    participante = models.ForeignKey(Participante, on_delete=models.PROTECT, related_name="ventas")
    factura = models.OneToOneField(FacturaVenta, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="numeros_campana")
    pedido = models.OneToOneField("pedidos.Pedido", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="numeros_campana")
    # Número del documento (FV-…, PED-…) o el de la demostración.
    documento = models.CharField(max_length=30)
    canal = models.CharField("canal de compra", max_length=3, choices=Canal.choices)
    fecha = models.DateTimeField(default=timezone.now)
    # Monto contra el que se midió el umbral: lo pagado por productos, con IVA,
    # ya con descuentos, promociones, cupón y redondeo; sin envío.
    monto_evaluado = models.DecimalField(max_digits=12, decimal_places=2)
    monto_vigente = models.DecimalField(max_digits=12, decimal_places=2,
                                        help_text="El monto después de devoluciones.")
    # Ganancia bruta de la venta al acreditarse (sin IVA, menos el costo de
    # lo vendido). Es una foto para medir la campaña sin recorrer líneas.
    margen = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    habituales = models.PositiveSmallIntegerField(default=0)
    bono = models.PositiveSmallIntegerField(default=0)
    revertidos = models.PositiveSmallIntegerField(default=0, help_text="Números quitados por devoluciones o anulación.")
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "números de una venta"
        verbose_name_plural = "números por venta"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.documento}: {self.total} número(s)"

    @property
    def total(self):
        return self.habituales + self.bono

    @property
    def margen_vigente(self):
        """El margen que queda después de devoluciones, en proporción a lo
        que quedó de la venta (aproximación: no recorre qué línea se devolvió)."""
        if not self.monto_evaluado:
            return Decimal("0")
        return (self.margen * self.monto_vigente / self.monto_evaluado).quantize(Decimal("0.01"))


class MovimientoNumeros(models.Model):
    """Libro de números: cada alta o baja con su porqué. Nunca se edita; un
    error se corrige con otro movimiento. El saldo de un participante es la
    suma de esta tabla."""

    class Tipo(models.TextChoices):
        INSCRIPCION = "INS", "Inscripción"
        COMPRA = "COM", "Compra"
        BONO = "BON", "Bono por superar el umbral"
        REVERSION = "REV", "Reversión"
        AJUSTE = "AJU", "Ajuste manual"

    campana = models.ForeignKey(Campana, on_delete=models.PROTECT, related_name="movimientos")
    participante = models.ForeignKey(Participante, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    cantidad = models.SmallIntegerField(help_text="Positivo suma números, negativo quita.")
    venta = models.ForeignKey(NumerosVenta, null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos")
    motivo = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de números"
        verbose_name_plural = "movimientos de números"
        ordering = ["-creado_en", "-id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(cantidad=0), name="movimiento_numeros_distinto_de_cero"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.cantidad:+d} — {self.participante.cliente.nombre}"


class Sorteo(models.Model):
    """La lista congelada y, cuando se sortea, el resultado.

    Se crea al congelar la lista (cierre) y se completa al sortear. Lo que
    hay acá es lo que respalda el acta: fecha, responsable, método, la lista
    exacta que se usó (con su huella) y el número que salió."""

    campana = models.OneToOneField(Campana, on_delete=models.PROTECT, related_name="sorteo")
    # Lista: [{"p": id participante, "c": id cliente, "nombre", "telefono",
    #          "numeros", "desde", "hasta"}], ordenada por inscripción.
    lista = models.JSONField(default=list)
    total_participantes = models.PositiveIntegerField(default=0)
    total_numeros = models.PositiveIntegerField(default=0)
    huella = models.CharField("huella SHA-256 de la lista", max_length=64)
    congelada_en = models.DateTimeField()
    congelada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    # Si la lista se volvió a congelar antes del sorteo (hubo devoluciones),
    # acá queda cada versión anterior: fecha, quién, huella y totales.
    congelados_previos = models.JSONField(default=list, blank=True)

    realizado_en = models.DateTimeField(null=True, blank=True)
    realizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")
    metodo = models.TextField(blank=True)
    numero_ganador = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "sorteo"
        verbose_name_plural = "sorteos"

    def __str__(self):
        return f"Sorteo de {self.campana.nombre}"

    @property
    def realizado(self):
        return self.realizado_en is not None


class Adjudicacion(models.Model):
    """A quién le tocó: el ganador (orden 0) y, si las bases los prevén, los
    suplentes en el orden en que salieron."""

    class Estado(models.TextChoices):
        TITULAR = "TIT", "Tiene el premio (por reclamar)"
        ESPERA = "ESP", "Suplente en espera"
        NO_RESPONDIO = "NOR", "No respondió a tiempo"
        ENTREGADO = "ENT", "Premio entregado"

    sorteo = models.ForeignKey(Sorteo, on_delete=models.PROTECT, related_name="adjudicaciones")
    orden = models.PositiveSmallIntegerField(help_text="0 = ganador; 1, 2… = suplentes.")
    participante = models.ForeignKey(Participante, on_delete=models.PROTECT, related_name="adjudicaciones")
    numero = models.PositiveIntegerField(help_text="El número que salió.")
    estado = models.CharField(max_length=3, choices=Estado.choices)
    # Desde cuándo corre su plazo para reclamar y hasta cuándo.
    notificado_en = models.DateTimeField(null=True, blank=True)
    vence_en = models.DateTimeField(null=True, blank=True)
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "adjudicación"
        verbose_name_plural = "adjudicaciones"
        ordering = ["orden"]
        constraints = [
            models.UniqueConstraint(fields=["sorteo", "orden"], name="un_lugar_por_sorteo"),
            # Nadie sale dos veces en el mismo sorteo (ganador Y suplente).
            models.UniqueConstraint(fields=["sorteo", "participante"], name="una_adjudicacion_por_persona"),
        ]

    def __str__(self):
        return f"{'Ganador' if self.orden == 0 else f'Suplente {self.orden}'}: {self.participante.cliente.nombre}"

    @property
    def lugar(self):
        return "Ganador" if self.orden == 0 else f"Suplente {self.orden}"


class CanastaProducto(models.Model):
    """Qué lleva la canasta en cada versión. Sirve para estimar su costo
    antes del sorteo y para descontar el inventario al entregarla."""

    class Version(models.TextChoices):
        PERRO = "PER", "Para perro"
        GATO = "GAT", "Para gato"

    campana = models.ForeignKey(Campana, on_delete=models.CASCADE, related_name="canasta")
    version = models.CharField(max_length=3, choices=Version.choices)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="+")
    cantidad = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name = "producto de la canasta"
        verbose_name_plural = "productos de la canasta"
        ordering = ["version", "producto__nombre"]
        constraints = [
            models.UniqueConstraint(fields=["campana", "version", "producto"], name="producto_unico_por_canasta"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.producto.nombre} ({self.get_version_display()})"


class EntregaPremio(models.Model):
    """Constancia de la entrega: quién la recibió, qué versión eligió, con qué
    venta de regalía salió del inventario y cuánto costó."""

    sorteo = models.OneToOneField(Sorteo, on_delete=models.PROTECT, related_name="entrega")
    adjudicacion = models.OneToOneField(Adjudicacion, on_delete=models.PROTECT, related_name="entrega")
    version = models.CharField("canasta elegida", max_length=3, choices=CanastaProducto.Version.choices)
    factura = models.OneToOneField(FacturaVenta, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="entrega_premio",
                                   help_text="La venta de regalía con la que salieron los productos.")
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                help_text="Costo de lo entregado (sin IVA), al costo promedio del día.")
    recibe_nombre = models.CharField("quién recibió", max_length=150)
    recibe_identificacion = models.CharField("cédula de quien recibió", max_length=30, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    entregado_en = models.DateTimeField(default=timezone.now)
    entregado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "entrega del premio"
        verbose_name_plural = "entregas de premio"

    def __str__(self):
        return f"Entrega a {self.recibe_nombre} ({self.get_version_display()})"
