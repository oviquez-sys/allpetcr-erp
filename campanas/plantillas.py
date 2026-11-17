"""Valores de partida para una campaña nueva y el borrador de sus bases.

Nada de esto se guarda solo: llena el formulario para que Oscar lo revise,
lo corrija y lo guarde. Lo que es decisión del negocio y nadie ha tomado va
marcado «[POR DEFINIR]», y la campaña no se deja activar mientras quede uno:
así no se publica una regla que nadie decidió.
"""
from datetime import datetime

from django.utils import timezone

POR_DEFINIR = "[POR DEFINIR"


def _cr(anio, mes, dia, hora=0, minuto=0):
    return timezone.make_aware(datetime(anio, mes, dia, hora, minuto))


def navidad_2026(empresa) -> dict:
    """Navidad AllPet 2026 tal como la describió Oscar el 16/11/2026."""
    ahora = timezone.localtime().replace(second=0, microsecond=0)
    return {
        "nombre": "Navidad AllPet 2026",
        "slug": "navidad-2026",
        "premio": "Canasta con 15 productos, en versión para perro o para gato a elección de quien gane",
        "inicio": ahora,
        "cierre": _cr(2026, 12, 23, 23, 59),
        "sorteo_en": _cr(2026, 12, 24, 12, 0),
        "envio_gratis_hasta": _cr(2026, 12, 24, 23, 59),
        "zonas_envio": "Heredia / Heredia\nHeredia / Mercedes\nHeredia / San Francisco\nHeredia / Ulloa",
        "suplentes": 2,
        "plazo_reclamo_dias": 5,
        "bases": bases_borrador(empresa),
    }


def bases_borrador(empresa) -> str:
    cedula = getattr(empresa, "identificacion", "") or "[POR DEFINIR: cédula jurídica]"
    return f"""BASES DE LA CAMPAÑA «NAVIDAD ALLPET 2026»

1. Organizador. AllPetcr.com (cédula jurídica {cedula}), tienda de Heredia centro.

2. Vigencia. Desde la fecha de inicio publicada hasta el 23 de diciembre de 2026 a las 11:59 p. m. (hora de Costa Rica). El sorteo es el 24 de diciembre de 2026 a las 12:00 m. d.

3. Quién participa. Personas físicas mayores de edad [POR DEFINIR: ¿se excluye a dueños, personal y familiares directos?]. Una sola inscripción por persona.

4. Cómo participar. La inscripción es gratuita y no exige comprar: en www.allpetcr.com o en la tienda, con nombre y WhatsApp (o correo). Inscribirse no obliga a recibir publicidad: ese permiso se pide aparte.

5. Números para el sorteo.
   a) Inscribirse da 1 número.
   b) Cada compra de una persona inscrita, en la tienda o en la web, da 1 número.
   c) Si esa compra supera ₡20.000, da 1 número más («doble puntaje»). Una compra de ₡20.000 exactos no lo gana.
   d) El monto se mide por lo pagado en productos, con IVA, después de descuentos y promociones. El costo del envío no cuenta.
   e) Solo cuentan las compras hechas ya inscrito. Un pedido web cuenta cuando se paga.
   f) Si una compra se devuelve o se anula, se quitan los números que dio.
   g) Los números no son dinero, no se canjean ni se transfieren.

6. Cómo se sortea. Al cierre se hace la lista de participantes con sus números. El 24 de diciembre se elige un número al azar por medio del sistema de la tienda; todos los números tienen la misma probabilidad, así que quien tiene más números tiene más oportunidades. Queda un acta con la fecha, el responsable, el método, la lista usada y el resultado.

7. Premio. Una canasta con 15 productos. Quien gane elige la versión para perro o para gato. No se cambia por dinero ni por otros productos.

8. Aviso y reclamo. Se avisa a la persona ganadora por WhatsApp o correo [POR DEFINIR: ¿se publica el nombre en redes?]. Tiene 5 días naturales para reclamar el premio en la tienda con su cédula. Si no lo reclama, pierde el derecho y el premio pasa al suplente que sigue (se sortean 2 suplentes). Si no quedan suplentes, el premio se declara desierto.

9. Envío gratis. Durante la campaña y hasta el 24 de diciembre de 2026, los pedidos web que superen ₡20.000 en productos tienen envío gratis dentro de los distritos Heredia, Mercedes, San Francisco y Ulloa del cantón central de Heredia. Fuera de esa zona el envío se cotiza. El retiro en tienda no tiene costo y también gana números.

10. Regalo de bienvenida. Mientras dure la campaña no se entregan cupones nuevos del 10 % de bienvenida de La manada. Los cupones entregados antes siguen valiendo en sus condiciones.

11. Datos personales. Los datos se usan para administrar la campaña y la relación con el cliente, según la Ley 8968 y la política de privacidad de www.allpetcr.com/privacidad.

12. Dudas y reclamos. servicioalcliente@allpetcr.com o WhatsApp 8856-2992.
"""
