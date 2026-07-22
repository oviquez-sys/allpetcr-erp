from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from compras.models import Compra
from ventas.models import DevolucionVenta, FacturaVenta

from .dashboard import indicadores
from .models import Empresa
from .roles import GERENTE, es_gerente, rol_de, rol_requerido


@staff_member_required
def dashboard(request):
    empresa = Empresa.objects.first()
    ctx = {
        "es_gerente": es_gerente(request.user),
        "rol": rol_de(request.user),
    }
    if empresa is None:
        ctx["sin_empresa"] = True
        return render(request, "core/dashboard.html", ctx)
    ctx.update(indicadores(empresa))
    ctx["empresa"] = empresa
    return render(request, "core/dashboard.html", ctx)


@rol_requerido(GERENTE)
def actividad(request):
    """Bitácora de ventas y compras recientes con opción de anular, y un
    historial separado de anulaciones (quién, cuándo, por qué): la vista
    anti-fraude, porque anular es el punto donde se esconde el robo."""
    ventas = (FacturaVenta.objects
              .select_related("cliente", "usuario", "anulada_por")
              .order_by("-id")[:40])
    compras = (Compra.objects
               .select_related("proveedor", "usuario", "anulada_por")
               .order_by("-id")[:40])
    ventas_anuladas = (FacturaVenta.objects
                       .filter(estado=FacturaVenta.Estado.ANULADA)
                       .select_related("anulada_por").order_by("-anulada_en")[:50])
    compras_anuladas = (Compra.objects
                        .filter(estado=Compra.Estado.ANULADA)
                        .select_related("anulada_por").order_by("-anulada_en")[:50])
    devoluciones = (DevolucionVenta.objects
                    .select_related("factura", "usuario").order_by("-creado_en")[:50])
    return render(request, "core/actividad.html", {
        "ventas": ventas,
        "compras": compras,
        "ventas_anuladas": ventas_anuladas,
        "compras_anuladas": compras_anuladas,
        "devoluciones": devoluciones,
    })
