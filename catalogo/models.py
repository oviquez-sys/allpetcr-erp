from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from core.models import Empresa

from . import alimentos
from .codigos import siguiente_interno

validar_cabys = RegexValidator(
    r"^\d{13}$",
    "El código CABYS son 13 dígitos numéricos, tal cual lo publica Hacienda "
    "(con ceros a la izquierda si los tiene). No se inventa: se copia del "
    "catálogo oficial https://www.hacienda.go.cr/consultacabys/",
)


class Categoria(models.Model):
    """Familia de productos (taxonomía limpia). La categoría original del
    Excel se conserva en Producto.categoria_original hasta depurarla.

    Desde el inventario del 02/08/2026 el árbol tiene DOS niveles reales:
    la categoría web (`padre=None`, ej. "Juguetes") y la subcategoría
    (`padre=Juguetes`, ej. "Pelotas"). Antes era plano — nueve familias sin
    hijas— y el sitio ya sabía recorrer `padre_id`, así que no hizo falta un
    modelo nuevo: la jerarquía que ya existía pasó a usarse de verdad."""

    nombre = models.CharField(max_length=80, unique=True)
    padre = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="hijas")
    # Orden de exhibición, compartido por el ERP y el sitio web (01/09/2026).
    #
    # Antes el menú del sitio tenía las categorías escritas a mano en
    # `allpetcr-web/lib/navegacion.ts`: crear una categoría en el ERP no la
    # hacía aparecer en la web hasta que alguien editara ese archivo. Dos
    # listas separadas que se desincronizan es cuestión de tiempo.
    #
    # Con este campo el orden es un dato, no código: `exportar_catalogo_web`
    # lo publica, el sitio ordena por él, y una categoría nueva aparece en el
    # lugar correcto sin tocar una línea del sitio. El POS y "Recibir
    # mercadería" usan el mismo orden, que es lo que hace que buscar un
    # producto se sienta igual en las dos pantallas.
    #
    # Menor sale primero. Se dejan huecos de 10 en 10 para poder intercalar
    # una categoría nueva sin renumerar las demás.
    orden = models.PositiveSmallIntegerField(
        default=100,
        help_text="Posición en los menús del ERP y del sitio. Menor sale primero.",
    )

    class Meta:
        verbose_name_plural = "categorías"
        # `nombre` como segundo criterio: las categorías que nadie ordenó
        # explícitamente (orden=100) siguen saliendo alfabéticas, igual que antes.
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


# Tarifa general del IVA en Costa Rica (Ley 9635, art. 10). Se usa cuando un
# producto no tiene tarifa asignada. Por qué 13 y no 0: en la ley, cualquier
# bien que no esté expresamente en una tarifa reducida o exento paga la
# general. Suponer 0 (lo que hacía el motor antes del 20/09/2026) le quitaba
# el IVA a la venta en silencio, y el negocio lo debía igual.
# Verificado el 20/09/2026 en el catálogo CABYS oficial de Hacienda: comida
# para perros y gatos (2331100000200), arneses y correas (2921001000000),
# ropa para mascotas (2921099000000) e higiene para animales (3532307...)
# llevan 13 %. El 1 % de "alimento animal" es para insumos agropecuarios,
# no para comida de mascotas.
TARIFA_GENERAL_IVA = Decimal("13.00")


class Impuesto(models.Model):
    """Tarifas con vigencia, listas para cambios de Hacienda. En régimen
    simplificado la venta no desglosa impuesto: el motor fiscal decide."""

    nombre = models.CharField(max_length=60)
    tarifa = models.DecimalField(max_digits=5, decimal_places=2, help_text="Porcentaje, ej. 13.00")
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_hasta = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "impuestos"

    def __str__(self):
        return f"{self.nombre} ({self.tarifa}%)"


class Producto(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="productos")
    sku = models.CharField("código (REF)", max_length=30, unique=True)
    nombre = models.CharField(max_length=200)
    categoria = models.ForeignKey(Categoria, null=True, blank=True, on_delete=models.PROTECT, related_name="productos")
    categoria_original = models.CharField(max_length=120, blank=True, help_text="Categoría del Excel original, pendiente de depurar")
    codigo_barras = models.CharField(max_length=30, blank=True, db_index=True)
    presentacion = models.CharField(max_length=120, blank=True)
    # Texto de venta que publica el sitio. Vive en el ERP y no en el sitio
    # web a propósito: si viviera allá, cada corrección de una descripción
    # sería un despliegue, y el personal de la tienda —que es quien conoce el
    # producto— no podría tocarla.
    descripcion = models.TextField(blank=True, help_text="Descripción pública del producto (la publica el sitio web)")
    # Especie a la que va dirigido: "Perro", "Gato", "Perro y gato", "Peces"…
    # El sitio no tenía este dato y por eso su navegación NO podía ser
    # Perros/Gatos, que es como piensa quien compra (ver el comentario largo
    # en allpetcr-web/lib/navegacion.ts). Con este campo ya puede.
    mascota = models.CharField(max_length=30, blank=True, db_index=True, help_text="Especie destino: Perro, Gato, Perro y gato, Peces, Tortugas, Otros")
    imagen = models.CharField(max_length=200, blank=True, help_text="Ruta relativa dentro de media/ (ej. productos/75564.png)")
    marca = models.CharField(max_length=80, blank=True, db_index=True, help_text="Marca del producto (ej. Royal Canin, Pedigree)")

    class UnidadPeso(models.TextChoices):
        KILOGRAMO = "kg", "kg"
        GRAMO = "g", "g"
        LIBRA = "lb", "lb"
        ONZA = "oz", "oz"
        LITRO = "l", "l"
        MILILITRO = "ml", "ml"
        UNIDAD = "un", "unidad"

    peso_valor = models.DecimalField(
        max_digits=8, decimal_places=3, null=True, blank=True,
        help_text="Contenido neto del empaque (ej. 15 para una bolsa de 15 kg)",
    )
    peso_unidad = models.CharField(max_length=2, choices=UnidadPeso.choices, blank=True)
    # Desde el 21/09/2026 lo carga `manage.py asignar_cabys` por categoría,
    # solo con códigos verificados en la API de Hacienda (catalogo/cabys.py),
    # y deja un Excel para que el contador revise. Un código puesto a mano
    # (o corregido por el contador) no lo vuelve a pisar. Nunca se inventa
    # uno: un CABYS inexistente rebota la factura electrónica.
    # (El help_text de abajo quedó de antes; cambiarlo exigiría una migración
    # que no aporta nada.)
    cabys = models.CharField(
        "código CABYS", max_length=13, blank=True, validators=[validar_cabys],
        help_text="13 dígitos del Catálogo de Bienes y Servicios de Hacienda. "
                  "Vacío hasta que se confirme a mano — no se inventa.",
    )
    impuesto = models.ForeignKey(Impuesto, null=True, blank=True, on_delete=models.PROTECT)
    # Costo y stock: denormalizados para lectura rápida.
    # La fuente de verdad es el kardex (inventario.MovimientoInventario).
    costo_promedio = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=2, default=2)
    activo = models.BooleanField(default=True)
    # Marcador de trabajo para la pantalla de Etiquetas (26/09/2026, a pedido
    # de Oscar): separar "ya tiene su etiqueta física puesta" de "todavía no",
    # mientras se pone al día con las cargas nuevas (ZeeDog, Gosbi). Se pone
    # solo al imprimir desde esa pantalla (`impresion.servicio.imprimir_etiqueta`)
    # o a mano, con el botón de la misma pantalla — nunca al cargar el
    # producto. NO es una garantía de que el papel salió bien pegado en el
    # estante (eso solo lo sabe Oscar mirando el estante); es nada más el
    # último momento en que se mandó o se marcó como impresa. Vacío = pendiente.
    etiqueta_impresa_en = models.DateTimeField(null=True, blank=True)
    # Vitrina de la home del sitio (26/09/2026, a pedido de Oscar). Hasta acá
    # "La vitrina" de la portada se armaba sola: repartía productos por
    # categoría (allpetcr-web/app/page.tsx) sin que nadie eligiera cuáles se
    # ven primero. Para un escaparate comercial eso no alcanza — Oscar quiere
    # decidir qué producto recibe al visitante, no que lo decida el orden en
    # que quedó cargado en el catálogo.
    #
    # Estos dos campos son SOLO para esa sección de la portada. No tocan el
    # catálogo del sitio (/catalogo), la API (sigue ordenando por `nombre`,
    # ver api/views.py) ni ninguna pantalla del ERP — Meta.ordering de acá
    # abajo sigue siendo alfabético, como siempre.
    #
    # `destacado_home` prende o apaga el producto en la vitrina manual.
    # `orden_home` decide el lugar (menor sale primero) y solo importa si
    # `destacado_home` es True — por eso puede quedar vacío en cualquier otro
    # producto. `clean()` exige el número apenas se marca destacado, y la
    # restricción `orden_home_unico_por_empresa` de abajo impide que dos
    # destacados de la misma empresa compitan por el mismo lugar: así el
    # aviso sale en el formulario del admin, no como un choque silencioso en
    # la vitrina del sitio (dos productos peleando el puesto 1, ninguno en
    # el 2). Si faltan destacados para llenar la sección, o si uno se queda
    # sin stock, el sitio completa los espacios solo — ver el comentario
    # largo en allpetcr-web/lib/vitrina.ts.
    destacado_home = models.BooleanField(
        default=False,
        help_text="Aparece primero en «La vitrina» de la portada del sitio, "
                  "en el lugar que diga 'Orden en home'.",
    )
    orden_home = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Lugar dentro de «La vitrina». Menor sale primero. Solo se "
                  "usa si «Destacado en home» está marcado.",
    )
    # Ficha de alimento (26/09/2026): la información nutricional investigada
    # vive en la FÓRMULA, no en cada bolsa. "Balance Adult" en 2, 5, 9,07 y
    # 14,97 kg es la misma comida: se investiga una vez y las cuatro bolsas
    # apuntan a la misma ficha. Vacío en todo lo que no es alimento.
    ficha_alimento = models.ForeignKey(
        "FichaAlimento", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="productos",
        help_text="Fórmula a la que pertenece esta presentación (solo alimentos).",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.CheckConstraint(condition=models.Q(precio_venta__gte=0), name="precio_no_negativo"),
            models.CheckConstraint(condition=models.Q(stock_actual__gte=0), name="stock_no_negativo"),
            models.UniqueConstraint(
                fields=["empresa", "orden_home"],
                condition=models.Q(destacado_home=True),
                name="orden_home_unico_por_empresa",
                violation_error_message="Ya hay otro producto destacado en ese mismo lugar de la vitrina.",
            ),
        ]

    def __str__(self):
        return f"{self.sku} — {self.nombre}"

    def clean(self):
        super().clean()
        # Un destacado sin número de orden no tiene dónde ubicarse en la
        # vitrina: dejarlo pasar solo pospone el error hasta que alguien
        # mire la portada y no lo encuentre (o lo encuentre al final, por
        # casualidad). Se avisa acá, en el formulario, no en el sitio.
        if self.destacado_home and self.orden_home is None:
            raise ValidationError({
                "orden_home": "Un producto destacado en home necesita su número de orden.",
            })

    def save(self, *args, **kwargs):
        """Al crear un producto sin código de barras, le asigna uno interno.

        Así CUALQUIER producto nuevo queda listo para imprimir su etiqueta, sin
        importar por dónde se creó (Admin, Recibir mercadería o importación).
        No toca los productos que ya traen código —el EAN de fábrica— ni los
        que ya existen.

        Antes se copiaba el SKU. Se cambió el 06/09/2026 por una razón física:
        un SKU como "RC-15KG-001" son 156 módulos de Code128, y en la etiqueta
        de 35 mm eso obliga a barras de 0,125 mm que la pistola no lee (se
        comprobó en papel). El código interno es un EAN-8: 67 módulos, barras
        de 0,375 mm. El porqué completo está en catalogo/codigos.py."""
        if self._state.adding and not self.codigo_barras:
            # Se traen todos los códigos: tienen que ser únicos en TODO el
            # sistema —el escáner del POS no sabe de empresas— y con 532
            # productos la consulta es una sola y barata.
            usados = set(Producto.objects.values_list("codigo_barras", flat=True))
            self.codigo_barras = siguiente_interno(usados)
        super().save(*args, **kwargs)

    @property
    def bajo_minimo(self):
        return self.stock_actual <= self.stock_minimo

    # ------------------------------------------------------------------
    # Precio, IVA y ganancia (20/09/2026)
    #
    # En régimen tradicional el precio de venta INCLUYE el IVA, y ese IVA es
    # de Hacienda, no del negocio. Hasta esta fecha el margen, el markup y la
    # ganancia se calculaban contra el precio completo: en un producto de
    # ₡5.300 contaban como ganancia ₡610 que había que pagarle a Hacienda.
    # Además la ficha de precio mostraba "Ganancia" como precio + costo − 1
    # (un filtro de plantilla que sumaba en vez de restar).
    #
    # Todo sale de `precio_sin_iva`, para que el margen de la lista de
    # precios, el de la ficha, el del admin y el del chat no puedan
    # contarse distinto. En régimen simplificado no se desglosa IVA: ahí
    # `precio_sin_iva` es el precio completo, igual que antes.
    # ------------------------------------------------------------------

    @property
    def tarifa_iva(self):
        """Tarifa de IVA del producto (%). Sin tarifa asignada, la general."""
        return self.impuesto.tarifa if self.impuesto_id else TARIFA_GENERAL_IVA

    @property
    def desglosa_iva(self):
        """True si la empresa está en régimen tradicional (el precio incluye IVA)."""
        return self.empresa.regimen == Empresa.Regimen.TRADICIONAL

    @property
    def precio_sin_iva(self):
        """Lo que le queda al negocio de cada unidad vendida a precio de lista."""
        if not self.desglosa_iva:
            return self.precio_venta
        return (self.precio_venta / (1 + self.tarifa_iva / 100)).quantize(Decimal("0.01"))

    @property
    def iva_unitario(self):
        """Parte del precio que se le paga a Hacienda (0 en régimen simplificado)."""
        return self.precio_venta - self.precio_sin_iva

    @property
    def ganancia_unitaria(self):
        """Ganancia bruta por unidad: precio sin IVA − costo promedio."""
        return self.precio_sin_iva - self.costo_promedio

    @property
    def margen_pct(self):
        """Margen de ganancia (%) sobre el precio sin IVA.
        Fórmula: ((PrecioSinIVA - Costo) / PrecioSinIVA) * 100
        Retorna Decimal con 2 decimales, o None si el precio es 0."""
        base = self.precio_sin_iva
        if base == 0:
            return None
        return round((base - self.costo_promedio) / base * Decimal("100"), 2)

    @property
    def markup_pct(self):
        """Markup o recargo (%) sobre el costo, con el precio sin IVA.
        Fórmula: ((PrecioSinIVA - Costo) / Costo) * 100
        Retorna Decimal con 2 decimales, o None si el costo es 0."""
        if self.costo_promedio == 0:
            return None
        return round((self.precio_sin_iva - self.costo_promedio) / self.costo_promedio * Decimal("100"), 2)


class CambioPrecio(models.Model):
    """Bitácora inmutable de cada cambio manual del precio de venta: quién lo
    cambió, cuándo, de cuánto a cuánto y por qué. Un empleado no puede
    modificar precios en silencio; todo queda firmado. (El histórico del COSTO
    ya vive en el kardex: cada MovimientoInventario guarda el costo resultante.)"""

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="cambios_precio")
    valor_anterior = models.DecimalField(max_digits=12, decimal_places=2)
    valor_nuevo = models.DecimalField(max_digits=12, decimal_places=2)
    costo_al_momento = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Costo promedio del producto cuando se cambió el precio, para ver el margen histórico",
    )
    motivo = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "cambio de precio"
        verbose_name_plural = "cambios de precio"
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"{self.producto.sku}: ₡{self.valor_anterior} → ₡{self.valor_nuevo}"

    @property
    def variacion(self):
        """Diferencia absoluta (positiva sube, negativa baja)."""
        return self.valor_nuevo - self.valor_anterior


class FichaAlimento(models.Model):
    """Información oficial de UNA fórmula de alimento (26/09/2026).

    INVESTIGAR → VERIFICAR → ALMACENAR → MOSTRAR
    --------------------------------------------
    Todo lo de acá se investiga una vez contra la fuente oficial (fabricante
    o su distribuidor oficial en Costa Rica) y se guarda. El sitio lo lee de
    esta tabla; nunca consulta al fabricante cuando un cliente abre la ficha.

    Qué es estructurado y qué es JSON, y por qué
    --------------------------------------------
    Lo que va a filtrar o comparar es columna o lista de CLAVES del
    vocabulario de catalogo/alimentos.py (especie, tipo, etapas, tamaños,
    necesidades, proteína principal, calorías). Lo que cada fabricante
    publica distinto —análisis garantizado, guía de alimentación, fuentes—
    va en JSONField: una tabla por nutriente o por fila de guía serían cinco
    tablas más para un catálogo de ~130 fórmulas, sin ganar nada que
    PostgreSQL no haga ya sobre JSON.

    Regla absoluta: un campo vacío es un dato que el fabricante no publicó.
    Nunca se completa con el de otra fórmula ni se deduce.
    """

    clave = models.SlugField(max_length=80, unique=True, help_text="Identificador estable, ej. nutrisource-adult-chicken-rice")
    marca = models.CharField(max_length=80)
    linea = models.CharField(max_length=80, blank=True, help_text="Línea dentro de la marca, ej. Grain Free, Exclusive")
    nombre = models.CharField(max_length=160, help_text="Nombre oficial de la fórmula, como lo publica el fabricante")
    especie = models.CharField(max_length=10, choices=[(k, v) for k, v in alimentos.ESPECIES.items()])
    tipo = models.CharField(max_length=10, choices=[(k, v) for k, v in alimentos.TIPOS.items()])
    etapas = models.JSONField(default=list, blank=True, help_text="Claves de catalogo/alimentos.py ETAPAS")
    tamanos_raza = models.JSONField(default=list, blank=True, help_text="Claves de TAMANOS_RAZA")
    necesidades = models.JSONField(default=list, blank=True, help_text="Claves de NECESIDADES que declara el fabricante")
    proteina_principal = models.CharField(max_length=60, blank=True, help_text="Primer ingrediente proteico, ej. Pollo")
    sabor = models.CharField(max_length=120, blank=True)

    descripcion_corta = models.CharField(max_length=300, blank=True)
    descripcion = models.TextField(blank=True)
    # [{"clave": "digestion", "texto": "Prebióticos y probióticos..."}]
    beneficios = models.JSONField(default=list, blank=True)
    # Lista oficial, en el orden del fabricante. No se reordena ni se "mejora".
    ingredientes = models.TextField(blank=True)
    aditivos = models.TextField(blank=True, help_text="Vitaminas, minerales y aditivos, tal como los declara el fabricante")
    # [{"clave": "proteina", "etiqueta": "Proteína cruda", "calificador": "min", "valor": "26", "unidad": "%"}]
    analisis = models.JSONField(default=list, blank=True)
    kcal_kg = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True, help_text="Energía metabolizable por kg")
    kcal_unidad = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Por taza, lata o sobre")
    unidad_kcal = models.CharField(max_length=20, blank=True, help_text="Qué es la 'unidad' de kcal_unidad: taza, lata, sobre")
    # {"titulo": "...", "columnas": ["Peso", "Adulto"], "filas": [["1–5 lb", "¼–⅝ taza"]], "nota": "..."}
    guia_alimentacion = models.JSONField(default=dict, blank=True)

    # [{"url": "...", "tipo": "fabricante", "entidad": "Tuffy's Pet Foods", "region": "EE. UU.", "verificado_en": "2026-09-26"}]
    fuentes = models.JSONField(default=list, blank=True)
    estado = models.CharField(
        max_length=16, default="sin_investigar",
        choices=[(k, v) for k, v in alimentos.ESTADOS.items()],
    )
    verificado_en = models.DateField(null=True, blank=True, help_text="Última vez que se contrastó contra la fuente oficial")
    notas_internas = models.TextField(blank=True, help_text="Dudas, diferencias entre fuentes, qué falta. No se publica.")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ficha de alimento"
        verbose_name_plural = "fichas de alimento"
        ordering = ["marca", "nombre"]

    def __str__(self):
        return f"{self.marca} · {self.nombre}"

    def clean(self):
        errores = {}
        for campo, vocabulario in alimentos.LISTAS.items():
            desconocidas = [c for c in getattr(self, campo) or [] if c not in vocabulario]
            if desconocidas:
                errores[campo] = f"Claves desconocidas: {', '.join(desconocidas)}"
        malas = [b.get("clave") for b in self.beneficios or [] if b.get("clave") not in alimentos.BENEFICIOS]
        if malas:
            errores["beneficios"] = f"Beneficios desconocidos: {', '.join(map(str, malas))}"
        malos = [n.get("clave") for n in self.analisis or [] if n.get("clave") not in alimentos.NUTRIENTES]
        if malos:
            errores["analisis"] = f"Nutrientes desconocidos: {', '.join(map(str, malos))}"
        if self.estado == "verificado" and not (self.fuentes and self.verificado_en):
            errores["estado"] = "Una ficha verificada necesita al menos una fuente y la fecha de verificación."
        if errores:
            raise ValidationError(errores)
