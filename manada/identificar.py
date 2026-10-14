"""Reconocer a un cliente por cédula, teléfono o correo (14/10/2026).

Pedido de Oscar: "que sea como un control cruzado: si no lo encuentra de una,
lo encuentra de otra". Se busca en este orden:

1. **Cédula** — el único dato que no cambia nunca. Va primero porque si
   coincide, es esa persona.
2. **Teléfono** — el que se usa en el día a día. Se comparan los últimos 8
   dígitos: "8888-1234", "88881234" y "+506 8888 1234" son el mismo número.
3. **Correo** — respaldo.

El **nombre nunca une solo** (hay muchas "María Rodríguez" y cada quien lo
escribe distinto): sirve únicamente para sugerir un posible duplicado.

Y si dos datos apuntan a clientes DISTINTOS (la cédula a uno, el teléfono a
otro), se queda con el primero de la lista y deja un aviso de posible
duplicado para que una persona decida. Unir por error le pegaría a alguien las
compras y los recordatorios de otra persona.
"""
import unicodedata
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils import timezone

from ventas.models import Cliente


def solo_digitos(texto) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


def _normalizar_nombre(nombre) -> str:
    sin_tildes = unicodedata.normalize("NFD", (nombre or "").lower())
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return " ".join(sin_tildes.split())


def por_cedula(empresa, cedula):
    """La cédula se guarda con o sin guiones ("1-1234-0567", "112340567"):
    se compara solo la secuencia de dígitos. Menos de 9 dígitos no es una
    cédula (la física tiene 9; jurídica, DIMEX y NITE, más)."""
    digitos = solo_digitos(cedula)
    if len(digitos) < 9:
        return None
    candidatos = Cliente.objects.filter(
        empresa=empresa, activo=True, identificacion__endswith=digitos[-3:],
    ).order_by("id")
    return next((c for c in candidatos if solo_digitos(c.identificacion) == digitos), None)


def por_telefono(empresa, telefono):
    from .services import cliente_por_telefono

    return cliente_por_telefono(empresa, telefono)


def por_correo(empresa, correo):
    correo = (correo or "").strip()
    if "@" not in correo:
        return None
    return Cliente.objects.filter(empresa=empresa, activo=True, email__iexact=correo).order_by("id").first()


@dataclass
class Identificacion:
    cliente: Cliente | None = None
    por: str = ""                       # "cédula", "teléfono" o "correo"
    conflictos: list = field(default_factory=list)  # [(otro_cliente, motivo)]


def identificar(empresa, *, cedula="", telefono="", correo="") -> Identificacion:
    """Busca por cada dato que venga y junta lo que encontró."""
    resultado = Identificacion()
    hallazgos = []
    for nombre, buscar, valor in (("cédula", por_cedula, cedula),
                                  ("teléfono", por_telefono, telefono),
                                  ("correo", por_correo, correo)):
        if valor:
            encontrado = buscar(empresa, valor)
            if encontrado is not None:
                hallazgos.append((nombre, encontrado))
    if not hallazgos:
        return resultado
    resultado.por, resultado.cliente = hallazgos[0]
    for nombre, otro in hallazgos[1:]:
        if otro.pk != resultado.cliente.pk and all(o.pk != otro.pk for o, _ in resultado.conflictos):
            resultado.conflictos.append(
                (otro, f"La {resultado.por} es de {resultado.cliente.nombre}, pero el {nombre} es de {otro.nombre}.")
            )
    return resultado


def identificar_texto(empresa, texto) -> Identificacion:
    """Lo que se escribe en la casilla dorada del POS: un número o un correo.

    8 dígitos es un teléfono. 9 o más puede ser una cédula o un teléfono con
    el 506 adelante: se prueba primero como cédula y después como teléfono.
    """
    texto = (texto or "").strip()
    if "@" in texto:
        return identificar(empresa, correo=texto)
    digitos = solo_digitos(texto)
    if len(digitos) >= 9:
        r = identificar(empresa, cedula=digitos)
        return r if r.cliente else identificar(empresa, telefono=digitos)
    if len(digitos) == 8:
        return identificar(empresa, telefono=digitos)
    return Identificacion()


def avisar_duplicado(cliente, otro, motivo, origen=""):
    """Deja el aviso para que alguien decida. Una sola vez por par (en
    cualquier orden), y nunca de nuevo si ya se decidió."""
    from .models import PosibleDuplicado

    if cliente is None or otro is None or cliente.pk == otro.pk:
        return None
    ya = PosibleDuplicado.objects.filter(cliente__in=[cliente, otro], otro__in=[cliente, otro]).first()
    if ya is not None:
        return ya
    try:
        with transaction.atomic():
            return PosibleDuplicado.objects.create(cliente=cliente, otro=otro, motivo=motivo[:200],
                                                   origen=origen[:80])
    except IntegrityError:
        return PosibleDuplicado.objects.filter(cliente=cliente, otro=otro).first()


def avisar_conflictos(identificacion, origen=""):
    for otro, motivo in identificacion.conflictos:
        avisar_duplicado(identificacion.cliente, otro, motivo, origen)


def avisar_si_mismo_nombre(cliente, origen=""):
    """Para un cliente recién creado: si otro cliente activo se llama igual
    (sin contar tildes ni mayúsculas), se sugiere revisar. Solo sugiere."""
    clave = _normalizar_nombre(cliente.nombre)
    if len(clave) < 5 or " " not in clave:
        return  # "Ana" o un número de teléfono como nombre: demasiado común
    # Se recorren todos (son cientos, y esto pasa solo al crear un cliente):
    # filtrar en la base con icontains no ve que "María" y "Maria" son iguales.
    for otro in (Cliente.objects.filter(empresa=cliente.empresa, activo=True)
                 .exclude(pk=cliente.pk).only("id", "nombre")):
        if _normalizar_nombre(otro.nombre) == clave:
            avisar_duplicado(otro, cliente, f"Se llaman igual: «{cliente.nombre}». ¿Es la misma persona?", origen)
            return


def cliente_para_pedido(pedido):
    """Liga un pedido del sitio con un cliente: lo reconoce o lo crea.

    Si no se reconoce, se crea el cliente (para que su historial exista),
    pero NO como miembro de la manada: eso exige su consentimiento.
    """
    r = identificar(pedido.empresa, cedula=pedido.cliente_identificacion,
                    telefono=pedido.cliente_telefono, correo=pedido.cliente_email)
    origen = f"Pedido web {pedido.numero}"
    if r.cliente is not None:
        avisar_conflictos(r, origen)
        _completar_datos(r.cliente, identificacion=pedido.cliente_identificacion,
                         telefono=pedido.cliente_telefono, email=pedido.cliente_email)
        return r.cliente
    nuevo = Cliente.objects.create(
        empresa=pedido.empresa, nombre=pedido.cliente_nombre[:150] or pedido.cliente_telefono,
        identificacion=(pedido.cliente_identificacion or "")[:30], telefono=(pedido.cliente_telefono or "")[:30],
        email=(pedido.cliente_email or "")[:254], notas=f"Creado por el {origen}.",
    )
    avisar_si_mismo_nombre(nuevo, origen)
    return nuevo


def _completar_datos(cliente, **datos):
    """Solo llena lo vacío: un dato ya guardado no lo cambia un formulario
    que cualquiera puede llenar con el teléfono de otro."""
    cambios = []
    for campo, valor in datos.items():
        valor = (valor or "").strip()
        if valor and not getattr(cliente, campo):
            setattr(cliente, campo, valor[:Cliente._meta.get_field(campo).max_length])
            cambios.append(campo)
    if cambios:
        cliente.save(update_fields=cambios)


@transaction.atomic
def unir_clientes(*, conservar, absorber, usuario=None):
    """Junta dos fichas que eran la misma persona.

    Todo lo de `absorber` pasa a `conservar`: compras de la caja, pedidos del
    sitio, cuentas por cobrar (con su saldo), mascotas y, si `conservar` no los
    tenía, su perfil de la manada y su cupón. `absorber` queda inactivo (no se
    borra: sus documentos viejos lo siguen nombrando) con una nota de a quién
    se unió.
    """
    from pedidos.models import Pedido
    from ventas.models import DocumentoCxC, FacturaVenta

    from .models import Cupon, Mascota, PerfilManada, PosibleDuplicado

    if conservar.pk == absorber.pk:
        return conservar
    conservar = Cliente.objects.select_for_update().get(pk=conservar.pk)
    absorber = Cliente.objects.select_for_update().get(pk=absorber.pk)

    FacturaVenta.objects.filter(cliente=absorber).update(cliente=conservar)
    Pedido.objects.filter(cliente=absorber).update(cliente=conservar)
    DocumentoCxC.objects.filter(cliente=absorber).update(cliente=conservar)
    Mascota.objects.filter(cliente=absorber).update(cliente=conservar)
    if absorber.saldo:
        conservar.saldo += absorber.saldo
        absorber.saldo = 0
    if not PerfilManada.objects.filter(cliente=conservar).exists():
        PerfilManada.objects.filter(cliente=absorber).update(cliente=conservar)
    if not Cupon.objects.filter(cliente=conservar, tipo=Cupon.Tipo.BIENVENIDA).exists():
        Cupon.objects.filter(cliente=absorber, tipo=Cupon.Tipo.BIENVENIDA).update(cliente=conservar)

    for campo in ("tipo_identificacion", "identificacion", "telefono", "email", "direccion",
                  "provincia", "canton", "distrito"):
        if not getattr(conservar, campo) and getattr(absorber, campo):
            setattr(conservar, campo, getattr(absorber, campo))
    if conservar.limite_credito < absorber.limite_credito:
        conservar.limite_credito = absorber.limite_credito
    conservar.save()

    absorber.activo = False
    absorber.notas = (f"Unido a «{conservar.nombre}» (#{conservar.pk}) el "
                      f"{timezone.localtime():%d/%m/%Y}.\n" + absorber.notas)[:5000]
    absorber.save(update_fields=["activo", "notas", "saldo"])

    PosibleDuplicado.objects.filter(cliente__in=[conservar, absorber], otro__in=[conservar, absorber],
                                    resolucion="").update(
        resolucion=PosibleDuplicado.Resolucion.UNIDOS, resuelto_en=timezone.now(), resuelto_por=usuario,
    )
    return conservar
