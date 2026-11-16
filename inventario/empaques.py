"""Abrir una caja para vender sus unidades sueltas (16/11/2026).

Pedido de Oscar: "que se pueda tomar un producto que traiga sobres
individuales, abrirlo y vender el mismo producto pero individual". Caso
típico: la caja de 12 sobres de alimento húmedo se vende entera, y cuando
alguien quiere un solo sobre se abre una.

Cómo se modela, y por qué:

- La caja y el sobre son DOS productos. Cada uno tiene su código de barras
  (el sobre trae el suyo de fábrica), su precio y su existencia. Si fuera un
  solo producto con "media caja" el POS, las etiquetas, el sitio y el kardex
  tendrían que entender fracciones de caja, y vender "0,083 cajas" no lo
  entiende nadie en el mostrador.
- La caja apunta a su unidad (`Producto.unidad_suelta`) y dice cuántas trae
  (`unidades_por_empaque`). Se configura una vez; después abrir es un clic.
- Abrir NO es un ajuste: es un movimiento propio (ABR) con UN documento
  (APE-…) que deja dos filas en el kardex: sale la caja y entran sus
  unidades. Así, al revisar la existencia del sobre, se ve de dónde salió.
- El costo viaja con la mercadería: cada unidad entra al costo promedio de la
  caja dividido entre las unidades. La plata en inventario no cambia (salvo
  céntimos de redondeo: ₡8.333,33 / 12 = ₡694,44 → ₡0,05 en la caja entera).
  Por eso NO hay asiento contable: caja y sobres están en la misma cuenta de
  Inventario, y un asiento de ₡0 entre la misma cuenta solo sería ruido.
- No se puede abrir lo que no hay (la regla de stock negativo de
  `registrar_movimiento` lo frena) y todo pasa en una transacción: o salen
  las cajas y entran los sobres, o no pasa nada.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from catalogo.models import Producto

from .models import MovimientoInventario
from .services import registrar_movimiento

MAX_UNIDADES = 500  # una caja de más de 500 unidades es casi seguro un dedazo


def _consecutivo():
    return f"APE-{timezone.now():%Y%m%d-%H%M%S}"


def costo_por_unidad(empaque: Producto) -> Decimal:
    """Costo promedio de la caja repartido entre sus unidades (2 decimales)."""
    n = empaque.unidades_por_empaque or 0
    if n <= 0:
        return Decimal("0")
    return (empaque.costo_promedio / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sku_para_unidad(empaque: Producto) -> str:
    """<SKU de la caja>-U, o -U2, -U3… si ya existe. Cabe en 30 caracteres."""
    base = empaque.sku[:26]
    for i in range(1, 100):
        candidato = f"{base}-U" if i == 1 else f"{base}-U{i}"
        if not Producto.objects.filter(sku=candidato).exists():
            return candidato
    raise ValidationError("No se pudo armar un código para la unidad suelta.")


def _validar_unidades(unidades) -> int:
    try:
        unidades = int(unidades)
    except (TypeError, ValueError):
        raise ValidationError("Escribí cuántas unidades trae la caja.")
    if unidades < 2:
        raise ValidationError("Una caja que se abre trae al menos 2 unidades.")
    if unidades > MAX_UNIDADES:
        raise ValidationError(f"¿Seguro que trae {unidades}? El máximo es {MAX_UNIDADES}.")
    return unidades


def _validar_par(empaque: Producto, unidad: Producto):
    if unidad.pk == empaque.pk:
        raise ValidationError("La unidad suelta tiene que ser otro producto, no la misma caja.")
    if unidad.empresa_id != empaque.empresa_id:
        raise ValidationError("La unidad suelta es de otra empresa.")
    if unidad.unidad_suelta_id == empaque.pk:
        raise ValidationError(f"«{unidad.nombre}» ya se abre en «{empaque.nombre}»: quedaría en círculo.")


@transaction.atomic
def vincular_unidad(*, empaque: Producto, unidad: Producto, unidades) -> Producto:
    """La caja ya tiene su producto suelto en el catálogo: solo se enlazan."""
    unidades = _validar_unidades(unidades)
    _validar_par(empaque, unidad)
    empaque.unidad_suelta = unidad
    empaque.unidades_por_empaque = unidades
    empaque.save(update_fields=["unidad_suelta", "unidades_por_empaque", "actualizado_en"])
    return empaque


@transaction.atomic
def crear_unidad(*, empaque: Producto, unidades, nombre: str, precio_venta, codigo_barras: str = "",
                 presentacion: str = "") -> Producto:
    """Crea el producto suelto a partir de la caja y los enlaza.

    Hereda lo que es igual en la caja y en el sobre (categoría, marca,
    mascota, IVA, CABYS, foto, descripción y ficha de alimento: la fórmula es
    la misma). Lo que cambia se pide: nombre, precio y código de barras. El
    peso NO se calcula dividiendo el de la caja: "12 × 85 g" cargado como
    1 kg daría 83 g; mejor la presentación que diga el sobre."""
    unidades = _validar_unidades(unidades)
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValidationError("Ponele nombre a la unidad suelta.")
    precio_venta = Decimal(str(precio_venta or 0))
    if precio_venta <= 0:
        raise ValidationError("Poné el precio de venta de la unidad suelta.")
    codigo_barras = (codigo_barras or "").strip()
    if codigo_barras:
        otro = Producto.objects.filter(codigo_barras=codigo_barras).first()
        if otro:
            raise ValidationError(f"El código {codigo_barras} ya es de «{otro.nombre}». "
                                  "Si ese es el sobre, elegilo en «Ya existe en el catálogo».")
    unidad = Producto.objects.create(
        empresa=empaque.empresa, sku=sku_para_unidad(empaque), nombre=nombre[:200],
        categoria=empaque.categoria, categoria_original=empaque.categoria_original,
        codigo_barras=codigo_barras, presentacion=(presentacion or "").strip()[:120],
        descripcion=empaque.descripcion, mascota=empaque.mascota, imagen=empaque.imagen,
        marca=empaque.marca, cabys=empaque.cabys, impuesto=empaque.impuesto,
        precio_venta=precio_venta, ficha_alimento=empaque.ficha_alimento,
        # El mínimo de estante de un sobre no es el de la caja: con 2 sobres
        # el aviso llega a tiempo para abrir otra caja.
        stock_minimo=Decimal("2"),
    )
    empaque.unidad_suelta = unidad
    empaque.unidades_por_empaque = unidades
    empaque.save(update_fields=["unidad_suelta", "unidades_por_empaque", "actualizado_en"])
    return unidad


@transaction.atomic
def abrir_empaque(*, empaque: Producto, cajas, bodega, usuario=None) -> dict:
    """Saca `cajas` del empaque y mete sus unidades sueltas, en un documento."""
    try:
        cajas = int(cajas)
    except (TypeError, ValueError):
        raise ValidationError("Escribí cuántas cajas vas a abrir (un número entero).")
    if cajas < 1:
        raise ValidationError("Escribí cuántas cajas vas a abrir.")
    # Se relee bloqueado: la configuración y el costo tienen que ser los de
    # este instante, no los que tenía la página cuando se abrió.
    empaque = Producto.objects.select_for_update().get(pk=empaque.pk)
    unidad = empaque.unidad_suelta
    n = empaque.unidades_por_empaque or 0
    if unidad is None or n < 2:
        raise ValidationError("Primero decí qué producto se vende suelto y cuántas unidades trae la caja.")
    costo = costo_por_unidad(empaque)
    referencia = _consecutivo()
    motivo = f"Se abrieron {cajas} × {empaque.nombre} ({n} unidades c/u)"[:200]
    salida = registrar_movimiento(
        producto=empaque, bodega=bodega, tipo=MovimientoInventario.Tipo.APERTURA,
        cantidad=Decimal(-cajas), referencia=referencia, motivo=motivo, usuario=usuario,
    )
    entrada = registrar_movimiento(
        producto=unidad, bodega=bodega, tipo=MovimientoInventario.Tipo.APERTURA,
        cantidad=Decimal(cajas * n), costo_unitario=costo, referencia=referencia,
        motivo=motivo, usuario=usuario,
    )
    return {"referencia": referencia, "salida": salida, "entrada": entrada,
            "unidades": cajas * n, "costo_unidad": costo}


def aperturas(empaque: Producto, limite: int = 8):
    """Las últimas aperturas de esta caja (la fila de salida de cada una)."""
    return (MovimientoInventario.objects
            .filter(producto=empaque, tipo=MovimientoInventario.Tipo.APERTURA, cantidad__lt=0)
            .select_related("usuario").order_by("-fecha", "-id")[:limite])
