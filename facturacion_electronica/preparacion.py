"""¿Qué falta para poder emitir factura electrónica? (auditoría 26/09/2026, FE-01…FE-09)

No emite nada: revisa los DATOS que un comprobante va a necesitar y dice, en
palabras simples, qué falta. Así el día que llegue la llave criptográfica no
aparecen de golpe 300 productos sin CABYS ni la empresa sin actividad
económica. Los requisitos exactos de Hacienda los confirma el contador: esta
lista cubre los datos que el ERP ya sabe que va a necesitar.
"""
from dataclasses import dataclass


@dataclass
class Punto:
    listo: bool
    texto: str
    detalle: str = ""


def revisar(empresa) -> list[Punto]:
    from catalogo.models import Producto
    from ventas.models import Cliente

    puntos = []
    faltan = [et for campo, et in (("identificacion", "cédula jurídica"), ("codigo_actividad", "código de actividad"),
                                   ("provincia", "provincia"), ("canton", "cantón"), ("distrito", "distrito"),
                                   ("telefono", "teléfono"), ("correo", "correo"))
              if not getattr(empresa, campo, "")]
    puntos.append(Punto(not faltan, "Datos de la empresa (emisor)",
                        ("Faltan: " + ", ".join(faltan) + ". Se llenan en Admin → Empresas.") if faltan else ""))
    puntos.append(Punto(empresa.regimen == empresa.Regimen.TRADICIONAL, "Régimen tradicional",
                        "" if empresa.regimen == empresa.Regimen.TRADICIONAL else "La empresa sigue marcada como simplificada."))

    activos = Producto.objects.filter(empresa=empresa, activo=True)
    sin_cabys = activos.filter(cabys="").count()
    puntos.append(Punto(sin_cabys == 0, "Código CABYS en cada producto",
                        f"{sin_cabys} producto(s) activo(s) sin CABYS. Ver «asignar_cabys» y el Excel para el contador."
                        if sin_cabys else ""))

    clientes = Cliente.objects.filter(empresa=empresa, activo=True).exclude(identificacion="")
    sin_tipo = clientes.filter(tipo_identificacion="").count()
    puntos.append(Punto(sin_tipo == 0, "Tipo de identificación de los clientes con cédula",
                        f"{sin_tipo} cliente(s) con cédula pero sin tipo (física, jurídica…). Se corrige en Admin → Clientes."
                        if sin_tipo else ""))

    puntos.append(Punto(False, "Llave criptográfica (.p12), usuario de la API de Hacienda y XSD oficiales",
                        "Trámite pendiente (ver CLAUDE.md, pendiente 5). Sin eso no se puede firmar ni enviar."))
    puntos.append(Punto(False, "Anulaciones y devoluciones como nota de crédito",
                        "Hoy una anulación o devolución no genera nota de crédito electrónica. Se conecta al activar FE."))
    return puntos
