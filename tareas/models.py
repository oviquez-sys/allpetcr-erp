"""Tareas del día (23/11/2026, pedido de Oscar).

Oscar y Francisco trabajan en computadoras distintas y los dos entran al ERP
con su usuario: por eso la lista de tareas del plan de mercadeo vive acá y no
en una página aparte que solo uno de los dos puede marcar.

Las piezas:

- **Tarea**: lo que se marca. Es algo puntual de un día (publicar un reel,
  lanzar un anuncio, algo agregado a mano) o el ejemplar de una rutina en una
  fecha. Guarda quién la marcó y cuándo: eso es lo que permite ver, al cerrar
  la semana, qué se hizo de verdad.
- **Rutina**: lo que se repite (responder mensajes a las 9, subir historias…).
  Es una plantilla. Su tarea de cada día se crea la primera vez que alguien
  abre ese día o un resumen que lo incluye (`servicios.asegurar_rutinas`):
  así la rutina sigue apareciendo después del plan sin cargar nada a mano.
- **Plan**: agrupa días con contexto (semanas con su meta, el tema de las
  historias, lo que deja listo Claude, la cuenta regresiva del sorteo). Es
  opcional: una tarea o una rutina existen aunque no haya plan.

Quién hace cada tarea se guarda con tres valores fijos (Oscar, Francisco,
los dos) y no como usuario del sistema: la tarea es de una persona del
negocio, aunque un día la marque otro. Quién la MARCÓ sí es el usuario real
(`marcada_por`), que no se puede falsear desde la pantalla.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Responsable(models.TextChoices):
    OSCAR = "OSC", "Oscar"
    FRANCISCO = "FRA", "Francisco"
    LOS_DOS = "AMB", "Los dos"


class Plan(models.Model):
    """Un periodo de trabajo con fechas (hoy: el plan de mercadeo de Navidad)."""

    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="planes_de_tareas")
    clave = models.SlugField(max_length=60)
    nombre = models.CharField(max_length=120)
    inicio = models.DateField()
    fin = models.DateField()
    hito = models.CharField(
        max_length=60, blank=True,
        help_text="Lo que se cuenta en días al tope de la pantalla, por ejemplo «Sorteo».",
    )
    hito_fecha = models.DateField(null=True, blank=True)
    enlace = models.URLField(blank=True, help_text="Documento del plan, con guiones y textos.")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["-inicio"]
        verbose_name = "plan"
        verbose_name_plural = "planes"
        constraints = [models.UniqueConstraint(fields=["empresa", "clave"], name="tareas_plan_clave_unica")]

    def __str__(self):
        return self.nombre


class Semana(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="semanas")
    nombre = models.CharField(max_length=40, help_text="«Semana 1», «Cierre»…")
    titulo = models.CharField(max_length=160)
    inicio = models.DateField()
    fin = models.DateField()
    objetivo = models.TextField(blank=True)
    meta = models.TextField(blank=True)
    anuncios = models.TextField(blank=True)
    nota = models.TextField(blank=True)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "semana del plan"
        verbose_name_plural = "semanas del plan"

    def __str__(self):
        return f"{self.nombre} · {self.titulo}"


class Dia(models.Model):
    """Lo que un día del plan tiene de particular. No tiene tareas: las tareas
    se buscan por fecha, así una agregada a mano aparece aunque el día no
    esté en ningún plan."""

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="dias")
    fecha = models.DateField()
    etiqueta = models.CharField(max_length=60, blank=True, help_text="«Black Friday», «Día de arreglos»…")
    historias = models.CharField(max_length=200, blank=True, help_text="Tema de las historias de la mañana.")
    claude = models.CharField(max_length=240, blank=True, help_text="Lo que Claude deja listo ese día.")
    nota = models.TextField(blank=True)
    tienda_cerrada = models.BooleanField(default=False, help_text="Ese día no se crea la rutina.")
    sin_rutinas = models.JSONField(
        default=list, blank=True,
        help_text="Claves de rutina que ese día no aplican (ej. «post1h» si no hay publicación).",
    )

    class Meta:
        ordering = ["fecha"]
        verbose_name = "día del plan"
        verbose_name_plural = "días del plan"
        constraints = [models.UniqueConstraint(fields=["plan", "fecha"], name="tareas_dia_unico_por_plan")]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y} · {self.plan}"


class Rutina(models.Model):
    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="rutinas")
    clave = models.SlugField(max_length=40)
    orden = models.PositiveSmallIntegerField(default=0)
    hora = models.CharField(max_length=30, blank=True, help_text="Como se dice: «9 a.m.», «Todo el día», «Tarde».")
    titulo = models.CharField(max_length=160)
    detalle = models.TextField(blank=True)
    responsable = models.CharField(max_length=3, choices=Responsable.choices, default=Responsable.LOS_DOS)
    dias = models.CharField(
        max_length=7, default="012345",
        help_text="Días que aplica: 0 = lunes … 6 = domingo. «012345» = de lunes a sábado.",
    )
    minimo = models.BooleanField(default=False, help_text="Lo que no se deja de hacer ni en un día pesado.")
    con_historias = models.BooleanField(
        default=False, help_text="Agrega al detalle el tema de historias del día del plan.",
    )
    activa = models.BooleanField(default=True)
    # Sin fecha de inicio, mirar un día viejo le fabricaría tareas pendientes
    # a fechas en que la rutina no existía: por eso arranca el día que se crea.
    desde = models.DateField(default=timezone.localdate, help_text="Desde qué día se crea.")
    hasta = models.DateField(null=True, blank=True, help_text="Hasta qué día. Vacío = sin fin.")

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "rutina diaria"
        verbose_name_plural = "rutinas diarias"
        constraints = [models.UniqueConstraint(fields=["empresa", "clave"], name="tareas_rutina_clave_unica")]

    def __str__(self):
        return self.titulo


class Tarea(models.Model):
    class Tipo(models.TextChoices):
        PUBLICACION = "PUB", "Publicación"
        CRECIMIENTO = "CRE", "Crecimiento"
        ANUNCIO = "ANU", "Anuncio"
        ARREGLO = "ARR", "Arreglo"
        SEMANA = "SEM", "De la semana"
        DECISION = "DEC", "Decisión"
        SORTEO = "SOR", "Sorteo"
        RUTINA = "RUT", "Rutina"
        OTRA = "OTR", "Agregada"

    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Pendiente"
        HECHA = "HEC", "Hecha"
        NO_SE_HIZO = "NOH", "No se hizo"

    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="tareas")
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="tareas")
    # Si se borra una rutina, lo que ya se marcó de ella se conserva.
    rutina = models.ForeignKey(Rutina, on_delete=models.SET_NULL, null=True, blank=True, related_name="ejemplares")
    clave = models.CharField(
        max_length=60, blank=True,
        help_text="Identifica las tareas que vienen de un plan, para no duplicarlas al recargarlo.",
    )
    fecha = models.DateField(db_index=True)
    orden = models.PositiveSmallIntegerField(default=0)
    hora = models.CharField(max_length=30, blank=True)
    titulo = models.CharField(max_length=200)
    detalle = models.TextField(blank=True)
    responsable = models.CharField(max_length=3, choices=Responsable.choices, default=Responsable.LOS_DOS)
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.OTRA)
    minimo = models.BooleanField(default=False)
    a_mano = models.BooleanField(default=False, help_text="La agregó alguien en la pantalla: se puede borrar.")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    nota = models.TextField(blank=True)
    marcada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    marcada_en = models.DateTimeField(null=True, blank=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha", "orden", "id"]
        verbose_name = "tarea"
        verbose_name_plural = "tareas"
        constraints = [
            # Una rutina da UNA tarea por día, aunque dos personas abran el
            # mismo día a la vez (ver servicios.asegurar_rutinas).
            models.UniqueConstraint(
                fields=["rutina", "fecha"], condition=Q(rutina__isnull=False),
                name="tareas_una_por_rutina_y_dia",
            ),
            models.UniqueConstraint(
                fields=["empresa", "clave"], condition=~Q(clave=""),
                name="tareas_clave_unica",
            ),
        ]

    def __str__(self):
        return f"{self.fecha:%d/%m} · {self.titulo}"

    @property
    def es_de_rutina(self):
        return self.rutina_id is not None or self.tipo == self.Tipo.RUTINA
