"""Reglas de la manada: registro, cupón de bienvenida, mascotas y uso en caja.

El sitio web (allpetcr-web) llama a estas funciones a través de la API
(api/views.py), servidor a servidor y con token. La caja las usa a través de
ventas.services.registrar_venta.
"""
import base64
import binascii
import io
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from ventas.models import Cliente

from .models import Cupon, Mascota, PerfilManada, Regalia

logger = logging.getLogger(__name__)

# Sin letras ni números que se confunden al dictarlos o leerlos en un
# celular con brillo bajo: ni O/0, ni I/1/L. El cajero lo teclea mirando la
# pantalla del cliente; un código ambiguo es un cliente esperando en caja.
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PREFIJO_CUPON = "AP-"
MAX_MASCOTAS = 5
# El sitio ya la achica en el celular antes de mandarla (~150 KB); esto es el
# techo para lo que llegue sin achicar.
MAX_FOTO_BYTES = 6 * 1024 * 1024
LADO_MAX_FOTO = 1200


def _foto_limpia(dato, nombre_mascota):
    """Recibe la foto como texto base64 (con o sin el prefijo "data:image/...")
    y devuelve un JPEG nuevo, de 1200 px como máximo.

    Se vuelve a dibujar la imagen en vez de guardar el archivo tal cual por
    dos razones: (1) las fotos de celular traen escondida la ubicación GPS de
    la casa del cliente, y no queremos guardarla; (2) un archivo que solo
    dice ser imagen no pasa por Pillow sin romperse."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not isinstance(dato, str) or not dato:
        return None
    if dato.startswith("data:"):
        dato = dato.split(",", 1)[-1]
    if len(dato) > MAX_FOTO_BYTES * 4 // 3 + 4:
        raise ValidationError(f"La foto de {nombre_mascota} es muy pesada. Probá con otra.")
    try:
        crudo = base64.b64decode(dato, validate=True)
        imagen = Image.open(io.BytesIO(crudo))
        imagen.load()
    except (binascii.Error, ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError(f"La foto de {nombre_mascota} no se pudo leer. Probá con otra.")
    imagen = ImageOps.exif_transpose(imagen)   # que no quede de lado
    if imagen.mode not in ("RGB", "L"):
        fondo = Image.new("RGB", imagen.size, (255, 255, 255))
        fondo.paste(imagen.convert("RGBA"), mask=imagen.convert("RGBA").split()[-1])
        imagen = fondo
    imagen.thumbnail((LADO_MAX_FOTO, LADO_MAX_FOTO))
    salida = io.BytesIO()
    imagen.convert("RGB").save(salida, "JPEG", quality=85, optimize=True)   # sin exif=: sale limpia
    return ContentFile(salida.getvalue(), name=f"{uuid.uuid4().hex}.jpg")


def _nuevo_codigo() -> str:
    while True:
        codigo = PREFIJO_CUPON + "".join(secrets.choice(_ALFABETO) for _ in range(6))
        if not Cupon.objects.filter(codigo=codigo).exists():
            return codigo


def normalizar_codigo(texto: str) -> str:
    """Lo que el cajero teclee ("ap 7k3p9q", "AP7K3P9Q", "7k3p9q") termina
    en la forma guardada: AP-7K3P9Q. El cajero no tiene que acordarse del
    guion ni de las mayúsculas."""
    limpio = "".join(c for c in (texto or "").upper() if c.isalnum())
    # Con prefijo son 8 caracteres; sin él, 6. Se mira el largo y no solo si
    # empieza con "AP", porque un código como AP-APX2K9 también existe.
    if len(limpio) == 8 and limpio.startswith("AP"):
        limpio = limpio[2:]
    return PREFIJO_CUPON + limpio if limpio else ""


@dataclass
class ResultadoRegistro:
    cliente: Cliente
    perfil: PerfilManada
    cupon: Cupon | None
    cupon_nuevo: bool
    cliente_nuevo: bool


def _limpiar_telefono(texto: str) -> str:
    """Solo dígitos y un + inicial. Un número de Costa Rica de 8 dígitos
    queda tal cual; uno con código de país, con su +506."""
    texto = (texto or "").strip()
    digitos = "".join(c for c in texto if c.isdigit())
    if not digitos:
        return ""
    if len(digitos) < 8 or len(digitos) > 15:
        raise ValidationError("El número de WhatsApp no parece válido.")
    return ("+" if texto.startswith("+") else "") + digitos


@transaction.atomic
def registrar_miembro(*, empresa, email, nombre="", telefono="", google_sub="",
                      verificado=False, acepta_promociones=False, fuente="") -> ResultadoRegistro:
    """Une a una persona a la manada y le da el cupón de bienvenida, una sola
    vez en la vida.

    - Se busca primero por la cuenta de Google y después por el correo: la
      misma persona nunca crea dos clientes ni recibe dos cupones.
    - Si ya existía como cliente de la caja (con ese correo), se usa ESE
      cliente: así su historial de compras queda junto.
    - Registrarse otra vez no da otro cupón: devuelve el que ya tiene.
    """
    email = (email or "").strip().lower()[:254]
    try:
        validate_email(email)
    except ValidationError:
        raise ValidationError("El correo no parece válido.")
    nombre = " ".join((nombre or "").split())[:150]
    telefono = _limpiar_telefono(telefono)
    google_sub = (google_sub or "").strip()[:64]
    fuente = "".join(c for c in (fuente or "").lower() if c.isalnum() or c in "-_")[:40]

    perfil = None
    if google_sub:
        perfil = (PerfilManada.objects.select_for_update().select_related("cliente")
                  .filter(google_sub=google_sub, cliente__empresa=empresa).first())
    cliente = perfil.cliente if perfil else None
    if cliente is None:
        cliente = (Cliente.objects.select_for_update()
                   .filter(empresa=empresa, email__iexact=email, activo=True).order_by("id").first())
    cliente_nuevo = cliente is None
    if cliente_nuevo:
        cliente = Cliente.objects.create(
            empresa=empresa, nombre=nombre or email.split("@")[0], email=email, telefono=telefono,
        )
    else:
        cambios = []
        if not cliente.email:
            cliente.email = email; cambios.append("email")
        if telefono and not cliente.telefono:
            cliente.telefono = telefono; cambios.append("telefono")
        # Un nombre "de correo" (lo que se usó cuando no dieron nombre) se
        # reemplaza por el real; un nombre que ya escribió alguien en caja no.
        if nombre and cliente.nombre == cliente.email.split("@")[0]:
            cliente.nombre = nombre; cambios.append("nombre")
        if cambios:
            cliente.save(update_fields=cambios)

    if perfil is None:
        perfil = PerfilManada.objects.select_for_update().filter(cliente=cliente).first()
    if perfil is None:
        perfil = PerfilManada.objects.create(
            cliente=cliente,
            origen=PerfilManada.Origen.GOOGLE if google_sub else PerfilManada.Origen.CORREO,
            google_sub=google_sub or None, fuente=fuente,
        )
    cambios = ["acepta_promociones", "consentimiento_en"]
    perfil.acepta_promociones = bool(acepta_promociones)
    perfil.consentimiento_en = timezone.now()
    if google_sub and not perfil.google_sub:
        perfil.google_sub = google_sub; cambios.append("google_sub")
    if verificado and not perfil.correo_verificado:
        perfil.correo_verificado = True; cambios.append("correo_verificado")
    if perfil.mascotas_registradas_en is None and not perfil.token_mascotas:
        perfil.token_mascotas = secrets.token_urlsafe(32); cambios.append("token_mascotas")
    perfil.save(update_fields=cambios)

    cupon = Cupon.objects.filter(cliente=cliente, tipo=Cupon.Tipo.BIENVENIDA).first()
    cupon_nuevo = False
    if cupon is None:
        regalia = Regalia.vigente(empresa)
        if regalia is not None:
            vence = (timezone.localdate() + timedelta(days=regalia.dias_vigencia)
                     if regalia.dias_vigencia else None)
            try:
                with transaction.atomic():
                    cupon = Cupon.objects.create(
                        empresa=empresa, codigo=_nuevo_codigo(), cliente=cliente, regalia=regalia,
                        porcentaje=regalia.porcentaje, descripcion=regalia.texto_cliente, vence_en=vence,
                    )
                cupon_nuevo = True
            except IntegrityError:
                # Dos registros simultáneos de la misma persona: el otro ganó.
                cupon = Cupon.objects.get(cliente=cliente, tipo=Cupon.Tipo.BIENVENIDA)

    return ResultadoRegistro(cliente=cliente, perfil=perfil, cupon=cupon,
                             cupon_nuevo=cupon_nuevo, cliente_nuevo=cliente_nuevo)


def _fecha_nacimiento(anios, meses) -> date | None:
    try:
        anios = int(anios or 0)
        meses = int(meses or 0)
    except (TypeError, ValueError):
        raise ValidationError("La edad debe ser un número.")
    if anios < 0 or meses < 0 or anios > 40 or meses > 11:
        raise ValidationError("Revisá la edad: años entre 0 y 40, meses entre 0 y 11.")
    if not anios and not meses:
        return None
    hoy = timezone.localdate()
    total = hoy.year * 12 + (hoy.month - 1) - (anios * 12 + meses)
    return date(total // 12, total % 12 + 1, 1)


@transaction.atomic
def registrar_mascotas(*, token, mascotas) -> PerfilManada:
    """Guarda las mascotas que el cliente contó. Una sola vez (pedido de
    Oscar): la llave se borra al usarse, así que el mismo enlace no sirve
    para volver a mandar ni para cambiar lo ya mandado."""
    token = (token or "").strip()
    if len(token) < 20:
        raise ValidationError("Este enlace no es válido.")
    perfil = PerfilManada.objects.select_for_update().filter(token_mascotas=token).first()
    if perfil is None:
        raise ValidationError("Este enlace ya se usó o no es válido.")
    if not isinstance(mascotas, list) or not mascotas:
        raise ValidationError("Contanos de al menos una mascota.")
    if len(mascotas) > MAX_MASCOTAS:
        raise ValidationError(f"Se pueden registrar hasta {MAX_MASCOTAS} mascotas.")

    nuevas = []
    for i, m in enumerate(mascotas, 1):
        if not isinstance(m, dict):
            raise ValidationError("Datos de mascota inválidos.")
        nombre = " ".join(str(m.get("nombre") or "").split())[:60]
        if not nombre:
            raise ValidationError(f"Falta el nombre de la mascota {i}.")
        especie = m.get("especie")
        if especie not in Mascota.Especie.values:
            raise ValidationError(f"Elegí si {nombre} es perro, gato u otro.")
        peso = m.get("peso_kg")
        if peso in (None, ""):
            peso = None
        else:
            try:
                peso = Decimal(str(peso).replace(",", ".")).quantize(Decimal("0.01"))
            except InvalidOperation:
                raise ValidationError(f"El peso de {nombre} debe ser un número.")
            if peso <= 0 or peso > 150:
                raise ValidationError(f"Revisá el peso de {nombre} (en kilos).")
        nuevas.append((Mascota(
            cliente=perfil.cliente, nombre=nombre, especie=especie,
            raza=" ".join(str(m.get("raza") or "").split())[:80],
            fecha_nacimiento_aprox=_fecha_nacimiento(m.get("edad_anios"), m.get("edad_meses")),
            peso_kg=peso, notas=" ".join(str(m.get("notas") or "").split())[:200],
        ), _foto_limpia(m.get("foto"), nombre)))
    # Todo se valida ANTES de guardar nada: si la foto de la tercera mascota
    # no sirve, no quedan las dos primeras a medias.
    for mascota, foto in nuevas:
        if foto is not None:
            mascota.foto.save(foto.name, foto, save=False)
        mascota.save()
    perfil.token_mascotas = ""
    perfil.mascotas_registradas_en = timezone.now()
    perfil.save(update_fields=["token_mascotas", "mascotas_registradas_en"])
    return perfil


def cupon_para_venta(empresa, codigo, *, bloquear=False) -> Cupon:
    """El cupón que la caja quiere aplicar, ya validado. Con `bloquear`
    toma la fila con bloqueo: lo usa registrar_venta para que dos cajas no
    puedan quemar el mismo cupón al mismo tiempo."""
    codigo = normalizar_codigo(codigo)
    if not codigo:
        raise ValidationError("Escriba el código del cupón.")
    qs = Cupon.objects.select_related("cliente", "factura")
    if bloquear:
        qs = qs.select_for_update(of=("self",))
    cupon = qs.filter(empresa=empresa, codigo=codigo).first()
    if cupon is None:
        raise ValidationError(f"El cupón {codigo} no existe. Revise que esté bien escrito.")
    if cupon.usado_en:
        cuando = timezone.localtime(cupon.usado_en).strftime("%d/%m/%Y")
        donde = f" en la venta {cupon.factura.numero}" if cupon.factura_id else ""
        raise ValidationError(f"El cupón {codigo} ya se usó el {cuando}{donde}.")
    if cupon.vencido:
        raise ValidationError(f"El cupón {codigo} venció el {cupon.vence_en:%d/%m/%Y}.")
    return cupon


def marcar_usado(cupon, factura):
    cupon.factura = factura
    cupon.usado_en = timezone.now()
    cupon.save(update_fields=["factura", "usado_en"])


def liberar_por_anulacion(factura):
    """Una venta anulada no cuenta como "primera compra": el cliente se
    lleva de vuelta su cupón. Una devolución parcial, en cambio, no lo
    libera: la compra sí ocurrió."""
    Cupon.objects.filter(factura=factura).update(factura=None, usado_en=None)
