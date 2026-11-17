"""Inscribir a una persona en la campaña vigente, desde la caja o la web.

Inscribirse en la campaña y aceptar publicidad son dos permisos distintos
(pedido de Oscar): acá viajan separados. La inscripción siempre deja a la
persona como miembro de La manada —es el mismo registro de siempre, solo que
mientras dure la campaña no trae cupón— porque el participante tiene que ser
alguien a quien se le pueda avisar que ganó.
"""
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from manada.models import PerfilManada
from manada.services import registrar_miembro

from . import reglas
from .models import Participante


@dataclass
class Inscripcion:
    participante: Participante
    creada: bool            # False = ya participaba
    cliente_nuevo: bool
    miembro_nuevo: bool

    @property
    def numeros(self):
        return reglas.saldo(self.participante)


def _campana_abierta(empresa):
    campana = reglas.que_acepta(empresa)
    if campana is None:
        vigente = reglas.vigente(empresa)
        raise ValidationError("Las inscripciones ya cerraron." if vigente is not None
                              else "No hay ninguna campaña con inscripciones abiertas.")
    return campana


@transaction.atomic
def inscribir_persona(*, empresa, canal, nombre="", telefono="", email="", acepta_promociones=False,
                      origen_visita="", google_sub="", verificado=False, usuario=None) -> Inscripcion:
    """Alguien que se inscribe con sus datos (la web, o un cliente nuevo en
    caja). Si ya era cliente o miembro, se reconoce y no se duplica."""
    campana = _campana_abierta(empresa)
    en_tienda = canal == Participante.Canal.TIENDA
    r = registrar_miembro(
        empresa=empresa, nombre=nombre, telefono=telefono, email=email, google_sub=google_sub,
        verificado=verificado, acepta_promociones=acepta_promociones,
        fuente=origen_visita or ("caja" if en_tienda else "web"),
        origen=PerfilManada.Origen.CAJA if en_tienda else None,
    )
    participante, creada = reglas.inscribir(
        campana=campana, cliente=r.cliente, canal=canal, origen_visita=origen_visita, usuario=usuario,
        cliente_nuevo=r.cliente_nuevo, miembro_nuevo=r.perfil_nuevo,
    )
    return Inscripcion(participante, creada, r.cliente_nuevo, r.perfil_nuevo)


@transaction.atomic
def inscribir_cliente(*, cliente, canal, acepta_promociones=False, usuario=None, origen_visita="") -> Inscripcion:
    """Un cliente que la caja ya tiene identificado y dice que sí quiere
    participar. Si no era miembro de La manada, lo hace miembro."""
    campana = _campana_abierta(cliente.empresa)
    perfil = PerfilManada.objects.select_for_update().filter(cliente=cliente).first()
    miembro_nuevo = perfil is None
    if miembro_nuevo:
        perfil = PerfilManada.objects.create(
            cliente=cliente, origen=PerfilManada.Origen.CAJA, fuente="caja",
            acepta_promociones=bool(acepta_promociones),
        )
    elif acepta_promociones and not perfil.acepta_promociones:
        # Está en el mostrador y acaba de decir que sí. Lo contrario no se
        # hace acá: no marcar la casilla no le QUITA un permiso que ya dio.
        perfil.acepta_promociones = True
        perfil.consentimiento_en = timezone.now()
        perfil.save(update_fields=["acepta_promociones", "consentimiento_en"])
    if not origen_visita and cliente.como_nos_conocio:
        origen_visita = cliente.get_como_nos_conocio_display()
    participante, creada = reglas.inscribir(
        campana=campana, cliente=cliente, canal=canal, origen_visita=origen_visita, usuario=usuario,
        miembro_nuevo=miembro_nuevo,
    )
    return Inscripcion(participante, creada, False, miembro_nuevo)


def estado_de(cliente, campana=None) -> dict:
    """Lo que la caja muestra al identificar al cliente."""
    campana = campana or reglas.vigente(cliente.empresa)
    if campana is None:
        return {}
    participante = reglas.participante_de(campana, cliente)
    return {"participa": participante is not None,
            "numeros": reglas.saldo(participante) if participante else 0}
