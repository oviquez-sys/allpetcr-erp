"""La manada AllPetcr: clientes que se registran desde el QR de la tienda.

Pedido de Oscar (13/10/2026): un QR en la tienda lleva a la página web, el
cliente se registra con un clic (Google) o con su correo, y a cambio recibe
una regalía —hoy 10 % en la primera compra— que el negocio puede cambiar
cuando quiera, sin tocar código. Opcionalmente cuenta de su mascota, una sola
vez.

Por qué se apoya en ventas.Cliente y no en una tabla aparte de "miembros"
----------------------------------------------------------------------------
Es la misma persona que después compra en la caja, recibe el tiquete por
correo y un día recibirá la factura electrónica. Dos tablas de clientes
terminan en dos versiones de la misma persona que nadie concilia. Lo propio
de la manada (cómo se registró, su consentimiento, sus mascotas, sus cupones)
cuelga del Cliente de siempre.
"""
from django.core.files.storage import storages
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import Empresa
from ventas.models import Cliente, FacturaVenta


class Regalia(models.Model):
    """Lo que recibe quien se une a la manada. La edita el gerente en el
    admin. Cada cupón copia el porcentaje y el texto AL EMITIRSE: cambiar la
    regalía afecta a los que se registren desde ese momento, nunca a los
    cupones que ya están en manos de clientes."""

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="regalias_manada")
    nombre = models.CharField(max_length=80, default="Bienvenida a la manada")
    porcentaje = models.DecimalField(
        "descuento (%)", max_digits=5, decimal_places=2,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Porcentaje de descuento sobre la compra. Ej.: 10",
    )
    texto_cliente = models.CharField(
        "texto que ve el cliente", max_length=160,
        default="10 % de descuento en tu primera compra",
        help_text="Así aparece en la página y en el correo. Debe coincidir con el porcentaje.",
    )
    dias_vigencia = models.PositiveSmallIntegerField(
        "días para usarlo", default=0,
        help_text="0 = el cupón no vence. Ej.: 60 = vence 60 días después de registrarse.",
    )
    activa = models.BooleanField(
        default=True,
        help_text="Solo puede haber UNA activa: es la que reciben los nuevos registros. "
                  "Si ninguna está activa, la gente se puede registrar pero no recibe cupón.",
    )
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "regalía de bienvenida"
        verbose_name_plural = "regalías de bienvenida"
        ordering = ["-activa", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa"], condition=models.Q(activa=True), name="una_regalia_activa_por_empresa",
            ),
        ]

    def __str__(self):
        return f"{self.nombre} — {self.porcentaje:g} %{'' if self.activa else ' (inactiva)'}"

    @classmethod
    def vigente(cls, empresa):
        return cls.objects.filter(empresa=empresa, activa=True).first()


class PerfilManada(models.Model):
    """Lo que el registro web agrega a un Cliente."""

    class Origen(models.TextChoices):
        GOOGLE = "GOO", "Google"
        CORREO = "COR", "Correo"
        FORMULARIO = "FOR", "Formulario web"
        CAJA = "CAJ", "En la caja"

    cliente = models.OneToOneField(Cliente, on_delete=models.PROTECT, related_name="manada")
    origen = models.CharField("se registró con", max_length=3, choices=Origen.choices)
    # El identificador que Google da a cada cuenta. No cambia aunque la
    # persona cambie su correo: con esto la misma cuenta nunca crea dos
    # clientes ni dos cupones.
    google_sub = models.CharField(max_length=64, null=True, blank=True, unique=True, editable=False)
    correo_verificado = models.BooleanField(
        default=False, help_text="Sí cuando Google confirmó que el correo es de esa persona.",
    )
    acepta_promociones = models.BooleanField(
        "acepta recibir promociones", default=False,
        help_text="Solo a quienes marcaron esta casilla se les puede escribir con ofertas.",
    )
    consentimiento_en = models.DateTimeField(
        "aceptó la política de privacidad el", default=timezone.now,
        help_text="Registro del consentimiento (Ley 8968).",
    )
    fuente = models.CharField(
        max_length=40, blank=True,
        help_text="De dónde llegó: qr-tienda, instagram, etc. Sirve para medir qué funciona.",
    )
    # Llave de un solo uso para "Contanos de tu mascota": va en el enlace del
    # correo o en la pantalla de bienvenida. Se borra al usarse.
    token_mascotas = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    mascotas_registradas_en = models.DateTimeField(null=True, blank=True, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "miembro de la manada"
        verbose_name_plural = "miembros de la manada"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.cliente.nombre} <{self.cliente.email}>"


def _almacen_privado():
    # Callable y no el almacén en sí: así la migración no guarda en qué
    # bucket vive, y cambiar de almacenamiento no pide migrar.
    return storages["privado"]


class Mascota(models.Model):
    class Especie(models.TextChoices):
        PERRO = "PER", "Perro"
        GATO = "GAT", "Gato"
        OTRO = "OTR", "Otro"

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="mascotas")
    nombre = models.CharField(max_length=60)
    especie = models.CharField(max_length=3, choices=Especie.choices)
    raza = models.CharField(max_length=80, blank=True)
    # El cliente da la edad ("2 años y 3 meses"); se guarda como fecha de
    # nacimiento aproximada para que la edad siga siendo correcta el año que
    # viene y para poder saludar en el mes de su cumpleaños.
    fecha_nacimiento_aprox = models.DateField("nacimiento (aproximado)", null=True, blank=True)
    peso_kg = models.DecimalField("peso (kg)", max_digits=5, decimal_places=2, null=True, blank=True,
                                  validators=[MinValueValidator(0)])
    notas = models.CharField(max_length=200, blank=True,
                             help_text="Alimento que come, alergias o lo que el cliente quiso contar.")
    # La sube el cliente desde el sitio. Se guarda ya achicada y sin datos
    # ocultos de la cámara (ver manada.services._foto_limpia).
    foto = models.ImageField(upload_to="mascotas/", storage=_almacen_privado, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mascota"
        verbose_name_plural = "mascotas"
        ordering = ["cliente_id", "id"]

    def __str__(self):
        return f"{self.nombre} ({self.get_especie_display()})"

    @property
    def edad_texto(self):
        if not self.fecha_nacimiento_aprox:
            return ""
        hoy = timezone.localdate()
        meses = (hoy.year - self.fecha_nacimiento_aprox.year) * 12 + hoy.month - self.fecha_nacimiento_aprox.month
        anios, meses = divmod(max(meses, 0), 12)
        partes = []
        if anios:
            partes.append(f"{anios} año{'s' if anios != 1 else ''}")
        if meses or not anios:
            partes.append(f"{meses} mes{'es' if meses != 1 else ''}")
        return " y ".join(partes)


class Cupon(models.Model):
    """Código de un solo uso. Lo valida y lo quema la caja, dentro de la
    misma transacción que registra la venta (ventas.services.registrar_venta):
    o la venta queda con el cupón usado, o no queda ninguna de las dos."""

    class Tipo(models.TextChoices):
        BIENVENIDA = "BIE", "Bienvenida a la manada"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT)
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="cupones")
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.BIENVENIDA, editable=False)
    regalia = models.ForeignKey(Regalia, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="cupones", editable=False)
    porcentaje = models.DecimalField("descuento (%)", max_digits=5, decimal_places=2, editable=False)
    descripcion = models.CharField(max_length=160, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    vence_en = models.DateField(null=True, blank=True)
    usado_en = models.DateTimeField(null=True, blank=True, editable=False)
    factura = models.OneToOneField(FacturaVenta, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="cupon_manada", editable=False)

    class Meta:
        verbose_name = "cupón"
        verbose_name_plural = "cupones"
        ordering = ["-creado_en"]
        constraints = [
            # "Un solo uso por cliente" (Oscar, 13/10/2026): la misma persona
            # no recibe dos cupones de bienvenida aunque se registre dos veces.
            models.UniqueConstraint(
                fields=["cliente"], condition=models.Q(tipo="BIE"), name="un_cupon_bienvenida_por_cliente",
            ),
        ]

    def __str__(self):
        return f"{self.codigo} — {self.porcentaje:g} % ({self.estado_display})"

    @property
    def vencido(self):
        return self.vence_en is not None and timezone.localdate() > self.vence_en

    @property
    def estado(self):
        if self.usado_en:
            return "USADO"
        if self.vencido:
            return "VENCIDO"
        return "DISPONIBLE"

    @property
    def estado_display(self):
        return {"USADO": "usado", "VENCIDO": "vencido", "DISPONIBLE": "disponible"}[self.estado]
