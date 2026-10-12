from django import forms

from catalogo.models import Producto

from .models import Bodega


# Tipos de ajuste (auditoría 26/09/2026, INV-05). Antes el motivo era solo
# texto libre: no había forma de sumar "cuánto se perdió por daño este mes".
# El tipo se guarda al inicio del motivo del kardex, entre corchetes, así no
# hace falta cambiar la tabla más grande del sistema y el reporte lo lee igual.
TIPOS_AJUSTE = [
    ("Conteo físico", "Conteo físico (lo contado no calza con el sistema)"),
    ("Daño", "Producto dañado"),
    ("Vencido", "Producto vencido"),
    ("Merma", "Merma (se perdió en el manejo)"),
    ("Robo o pérdida", "Robo o pérdida"),
    ("Uso interno", "Uso interno de la tienda"),
    ("Otro", "Otro (explicar en el motivo)"),
]


class AjusteInventarioForm(forms.Form):
    """Ajuste manual de inventario.

    El selector se acota a la empresa del usuario (auditoría 2026-07-28,
    ARQ-01). Antes ofrecía TODOS los productos activos del sistema, así que el
    día que haya una segunda empresa se podría ajustar el stock de la otra
    desde este formulario. Los queryset se definen vacíos a nivel de clase y
    se llenan en __init__ con la empresa recibida: si alguien instancia el
    formulario sin pasarla, no ve nada — que es el valor seguro.
    """

    producto = forms.ModelChoiceField(queryset=Producto.objects.none(), label="Producto")
    bodega = forms.ModelChoiceField(queryset=Bodega.objects.none(), label="Bodega")
    cantidad = forms.DecimalField(
        label="Cantidad",
        help_text="Positiva entra (sobrante), negativa sale (faltante/dañado)",
        max_digits=12,
        decimal_places=2,
    )
    costo_unitario = forms.DecimalField(
        label="Costo unitario (solo entradas)",
        required=False,
        initial=0,
        min_value=0,
        max_digits=12,
        decimal_places=2,
    )
    tipo = forms.ChoiceField(label="Tipo de ajuste", choices=[("", "— elegir —")] + TIPOS_AJUSTE)
    motivo = forms.CharField(
        label="Motivo (obligatorio, queda en auditoría)",
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=200,
    )

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa is not None:
            # ── EXCEPCIÓN DELIBERADA a la regla "solo en existencia" del
            # 02/08/2026 ── Este formulario existe para corregir el conteo
            # cuando la base dice cero y en la bodega hay tres, o al revés.
            # Filtrar por stock acá sería filtrar por el mismo dato que se
            # viene a corregir: el producto mal contado es exactamente el que
            # desaparecería del selector. Verificado en
            # core/test_arquitectura.py.
            self.fields["producto"].queryset = (
                Producto.objects.filter(activo=True, empresa=empresa).order_by("nombre")
            )
            self.fields["bodega"].queryset = (
                Bodega.objects.filter(sucursal__empresa=empresa).order_by("nombre")
            )

    def clean_cantidad(self):
        cantidad = self.cleaned_data["cantidad"]
        if cantidad == 0:
            raise forms.ValidationError("La cantidad no puede ser cero.")
        return cantidad


# --------------------------------------------------------------------------
# Ajustes de inventario (12/10/2026, a pedido de Oscar)
# --------------------------------------------------------------------------
# Una sola pantalla por producto para corregir lo que haya que corregir:
# cuántas hay, sus datos y su foto. Antes la existencia se corregía en una
# pantalla escondida detrás de Etiquetas, que pedía la DIFERENCIA ("+12"), y
# los datos solo se tocaban en el admin de Django.

class ExistenciaRealForm(forms.Form):
    """Se pide lo que hay de verdad, no la diferencia.

    Quien cuenta piensa "hay 12", no "faltan +12 contra lo que dice el
    sistema": pedir la diferencia obligaba a restar de cabeza y es justo el
    tipo de cuenta que sale mal. La diferencia la saca el sistema y la muestra
    antes de guardar.
    """

    cantidad_real = forms.DecimalField(
        label="¿Cuántas hay de verdad?", min_value=0, max_digits=12, decimal_places=2,
    )
    costo_unitario = forms.DecimalField(
        label="Costo por unidad (solo si se suman)", required=False, min_value=0,
        max_digits=12, decimal_places=2,
    )
    tipo = forms.ChoiceField(label="Motivo del ajuste", choices=[("", "— elegir —")] + TIPOS_AJUSTE)
    motivo = forms.CharField(
        label="Explicación (queda en el historial)", max_length=180,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    bodega = forms.ModelChoiceField(queryset=Bodega.objects.none(), label="Bodega")

    def __init__(self, *args, producto=None, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.producto = producto
        bodegas = Bodega.objects.filter(sucursal__empresa=empresa).order_by("nombre")
        self.fields["bodega"].queryset = bodegas
        if bodegas.count() == 1:
            # Con una sola bodega preguntarla es ruido: se elige sola.
            self.fields["bodega"].initial = bodegas.first()
            self.fields["bodega"].widget = forms.HiddenInput()

    def clean(self):
        datos = super().clean()
        real = datos.get("cantidad_real")
        if real is None or self.producto is None:
            return datos
        diferencia = real - self.producto.stock_actual
        datos["diferencia"] = diferencia
        if diferencia == 0:
            raise forms.ValidationError(
                f"El sistema ya dice {format(self.producto.stock_actual.normalize(), 'f')}: no hay nada que ajustar."
            )
        if diferencia > 0:
            costo = datos.get("costo_unitario")
            if not costo and not self.producto.costo_promedio:
                # Sin costo, las unidades que se suman entran gratis y bajan
                # el costo promedio: la ganancia del producto se vería más
                # alta de lo que es.
                self.add_error("costo_unitario", "Poné lo que costó cada unidad: este producto todavía no tiene costo.")
            elif not costo:
                datos["costo_unitario"] = self.producto.costo_promedio
        return datos


class DatosProductoForm(forms.ModelForm):
    """Los datos del producto que se pueden corregir a mano.

    Quedan FUERA a propósito: el código interno (SKU), que es la llave con la
    que lo conocen las cargas y las fotos; el costo y la existencia, que solo
    cambian por el kardex; y el precio, que va aparte para que cada cambio
    quede firmado en su historial (`catalogo.services.cambiar_precio`).
    """

    precio_venta = forms.DecimalField(label="Precio de venta (con IVA)", min_value=0, max_digits=12, decimal_places=2)
    mascota = forms.ChoiceField(label="Mascota", required=False)

    class Meta:
        model = Producto
        fields = ["nombre", "codigo_barras", "marca", "categoria", "presentacion", "mascota",
                  "descripcion", "peso_valor", "peso_unidad", "stock_minimo", "cabys", "activo"]
        labels = {
            "codigo_barras": "Código de barras", "presentacion": "Presentación",
            "descripcion": "Descripción (la ve el cliente en el sitio)", "peso_valor": "Contenido",
            "peso_unidad": "Unidad", "stock_minimo": "Existencia mínima", "cabys": "Código CABYS",
            "activo": "Activo (se vende y aparece en el sitio)", "categoria": "Categoría",
        }
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        from catalogo.completar import MASCOTAS
        from catalogo.models import Categoria

        super().__init__(*args, **kwargs)
        # Sin los ".00": un precio de ₡15.490 se ve "15490", no "15490.00".
        # (normalize() solo no sirve: 15490 lo deja como "1.549E+4").
        def _limpio(v):
            return int(v) if v == v.to_integral_value() else v
        self.fields["precio_venta"].initial = _limpio(self.instance.precio_venta)
        if self.instance.pk and not self.is_bound:
            self.initial["stock_minimo"] = _limpio(self.instance.stock_minimo)
        actual = self.instance.mascota or ""
        opciones = [("", "— sin definir —")] + [(m, m) for m in MASCOTAS]
        if actual and actual not in MASCOTAS:
            opciones.append((actual, actual))  # un valor viejo no se pierde al guardar
        self.fields["mascota"].choices = opciones
        # Categorías con su madre al lado ("Alimento › Alimento seco"): con
        # solo el nombre de la hija no se sabe en qué rama del menú cae.
        cats = list(Categoria.objects.select_related("padre").order_by("orden", "nombre"))
        self.fields["categoria"].queryset = Categoria.objects.all()
        self.fields["categoria"].choices = [("", "— sin categoría —")] + sorted(
            ((c.pk, f"{c.padre.nombre} › {c.nombre}" if c.padre_id else c.nombre) for c in cats),
            key=lambda x: x[1].lower(),
        )

    def clean_codigo_barras(self):
        codigo = (self.cleaned_data.get("codigo_barras") or "").strip()
        if codigo and Producto.objects.filter(codigo_barras=codigo).exclude(pk=self.instance.pk).exists():
            otro = Producto.objects.filter(codigo_barras=codigo).exclude(pk=self.instance.pk).first()
            raise forms.ValidationError(f"Ese código ya es de «{otro.nombre}». El escáner no sabría cuál vender.")
        return codigo
