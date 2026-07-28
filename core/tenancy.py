"""Punto ÚNICO de resolución de la empresa activa y de acceso a documentos.

Por qué existe este módulo
--------------------------
Las vistas que abren un documento por su ID (`get_object_or_404(Factura,
pk=...)`) no verificaban a qué empresa pertenece ese documento. Hoy no es
explotable —hay una sola empresa y todo usuario staff pertenece a ella— pero
el día que el sistema sea multi-empresa, un usuario de la empresa A podría
ver o anular un documento de la empresa B con solo cambiar el número en la
URL. Eso se llama IDOR, y la auditoría técnica del 22/07/2026 lo marcó como
la mejora #1: hay que cerrarlo ANTES de volverse multi-tenant, no después.

Cómo lo cierra
--------------
`empresa_actual(request)` es el único lugar del sistema que decide "cuál es
la empresa de este usuario". Hoy devuelve la única empresa que existe. El día
que haya varias, se cambia SOLO esta función (leerá la empresa del usuario
autenticado) y todas las vistas que usan `documento_de_empresa` quedan
protegidas automáticamente, sin tener que auditarlas una por una.

Ese es el punto: no es que hoy filtre "de mentira". Es que la estructura del
filtro ya está puesta y pasa por un solo interruptor.
"""
from django.shortcuts import get_object_or_404


def empresa_actual(request):
    """La empresa del usuario que hace la petición.

    HOY: el sistema opera con una sola empresa, así que devuelve esa.

    MAÑANA (multi-empresa): reemplazar por la empresa asociada al usuario,
    por ejemplo `request.user.perfil.empresa`. Es el ÚNICO cambio necesario:
    todas las vistas que filtran con `documento_de_empresa` empiezan a
    respetar la separación entre empresas de inmediato.
    """
    from core.models import Empresa

    return Empresa.objects.first()


def documento_de_empresa(queryset_o_modelo, request, campo_empresa="empresa", **kwargs):
    """`get_object_or_404` pero acotado a la empresa del usuario.

    Si el documento existe pero es de OTRA empresa, responde 404 (no 403): no
    se le confirma al curioso que ese ID existe.

    `campo_empresa` permite alcanzar la empresa a través de una relación
    cuando el modelo no la tiene directamente. Ejemplos reales:
      - FacturaVenta  → "empresa"          (FK directa)
      - Cliente       → "empresa"          (FK directa)
      - DocumentoCxC  → "cliente__empresa" (vía el cliente)
    """
    empresa = empresa_actual(request)
    filtros = {campo_empresa: empresa, **kwargs}
    return get_object_or_404(queryset_o_modelo, **filtros)
