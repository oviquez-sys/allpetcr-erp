"""Pantallas de la manada en el ERP (14/10/2026): clientes, ficha con
historial, recordatorios de comida y listas para promociones.

Solo gerente: muestran teléfonos, cédulas y qué compra cada persona.
"""
from django.contrib import messages
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.roles import GERENTE, rol_requerido
from core.tenancy import empresa_actual
from pedidos.models import Pedido
from ventas.models import Cliente, FacturaVenta

from . import historial as h
from .identificar import unir_clientes
from .models import Mascota, PosibleDuplicado


def _pendientes(empresa):
    return PosibleDuplicado.objects.filter(cliente__empresa=empresa, resolucion="").count()


def _pagina(request, plantilla, empresa, pestana, **ctx):
    """Las cuatro pantallas comparten pestañas; la de duplicados lleva la
    cuenta de pendientes para que no se queden sin revisar."""
    return render(request, plantilla, {"pestana": pestana, "pendientes": _pendientes(empresa), **ctx})


@rol_requerido(GERENTE)
def clientes(request):
    empresa = empresa_actual(request)
    lista = (
        Cliente.objects.filter(empresa=empresa, activo=True)
        .select_related("manada")
        .annotate(
            n_tienda=Count("compras", filter=Q(compras__estado=FacturaVenta.Estado.EMITIDA), distinct=True),
            n_web=Count("pedidos_web", filter=~Q(pedidos_web__estado=Pedido.Estado.CANCELADO), distinct=True),
            ultima_tienda=Max("compras__creado_en", filter=Q(compras__estado=FacturaVenta.Estado.EMITIDA)),
            ultima_web=Max("pedidos_web__creado_en"),
        )
        .order_by("nombre")
    )
    filas = []
    for c in lista:
        ultimas = [x for x in (c.ultima_tienda, c.ultima_web) if x]
        filas.append({"c": c, "compras": c.n_tienda + c.n_web, "miembro": hasattr(c, "manada"),
                      "ultima": timezone.localtime(max(ultimas)).date() if ultimas else None})
    return _pagina(request, "manada/clientes.html", empresa, "clientes", title="Clientes y manada",
                   filas=filas, miembros=sum(1 for f in filas if f["miembro"]))


@rol_requerido(GERENTE)
def ficha(request, cliente_id):
    empresa = empresa_actual(request)
    cliente = get_object_or_404(Cliente.objects.select_related("manada"), pk=cliente_id, empresa=empresa)
    compras = h.compras_de(cliente)
    hoy = timezone.localdate()
    perfil = getattr(cliente, "manada", None)
    acepta = bool(perfil and perfil.acepta_promociones)
    items = h.consumibles(compras, hoy)
    resumen = h.resumir(compras)
    for item in items:
        item.enlace = (h.enlace_whatsapp(cliente.telefono, h.mensaje_recordatorio(cliente, item))
                       if acepta and item.se_acaba else "")
    duplicados = (PosibleDuplicado.objects.filter(resolucion="")
                  .filter(Q(cliente=cliente) | Q(otro=cliente)).select_related("cliente", "otro"))
    for d in duplicados:
        d.el_otro = d.otro if d.cliente_id == cliente.pk else d.cliente
    return render(request, "manada/ficha.html", {
        "title": cliente.nombre, "cliente": cliente, "perfil": perfil, "acepta": acepta,
        "compras": compras, "resumen": resumen, "consumibles": items,
        "dias_desde": (hoy - resumen.ultima).days if resumen.ultima else None,
        "mascotas": Mascota.objects.filter(cliente=cliente), "duplicados": duplicados,
        "whatsapp": h.enlace_whatsapp(cliente.telefono, f"Hola {h.primer_nombre(cliente)}, "),
        "inicial": "".join(p[0] for p in cliente.nombre.split()[:2]).upper(),
    })


@rol_requerido(GERENTE)
@require_POST
def resolver_duplicado(request, aviso_id):
    empresa = empresa_actual(request)
    aviso = get_object_or_404(PosibleDuplicado, pk=aviso_id, cliente__empresa=empresa, resolucion="")
    # Se conserva la ficha desde la que se decidió: es la que la persona
    # estaba mirando y la que espera seguir viendo.
    conservar = get_object_or_404(Cliente, pk=request.POST.get("conservar"), empresa=empresa)
    if conservar.pk not in (aviso.cliente_id, aviso.otro_id):
        return redirect("manada:ficha", cliente_id=conservar.pk)
    if request.POST.get("accion") == "unir":
        otro = aviso.otro if conservar.pk == aviso.cliente_id else aviso.cliente
        unir_clientes(conservar=conservar, absorber=otro, usuario=request.user)
        messages.success(request, f"Listo: todo lo de «{otro.nombre}» quedó en esta ficha.")
    else:
        aviso.resolucion = PosibleDuplicado.Resolucion.DISTINTOS
        aviso.resuelto_en = timezone.now()
        aviso.resuelto_por = request.user
        aviso.save(update_fields=["resolucion", "resuelto_en", "resuelto_por"])
        messages.success(request, "Anotado: son personas distintas. No se vuelve a avisar.")
    return redirect("manada:ficha", cliente_id=conservar.pk)


@rol_requerido(GERENTE)
def duplicados(request):
    empresa = empresa_actual(request)
    avisos = (PosibleDuplicado.objects.filter(cliente__empresa=empresa, resolucion="")
              .select_related("cliente", "otro"))
    return _pagina(request, "manada/duplicados.html", empresa, "duplicados", title="Posibles duplicados",
                   avisos=avisos)


@rol_requerido(GERENTE)
def recordatorios(request):
    empresa = empresa_actual(request)
    try:
        dias = max(1, min(int(request.GET.get("dias", 7)), 60))
    except ValueError:
        dias = 7
    filas = h.recordatorios(empresa, dias=dias)
    return _pagina(request, "manada/recordatorios.html", empresa, "recordatorios",
                   title="Recordatorios de comida", filas=filas, dias=dias,
                   con_permiso=sum(1 for f in filas if f.acepta))


@rol_requerido(GERENTE)
def promociones(request):
    empresa = empresa_actual(request)
    marca = (request.GET.get("marca") or "").strip()
    especie = request.GET.get("especie") or ""
    if especie not in Mascota.Especie.values:
        especie = ""
    filas = h.destinatarios(empresa, marca=marca, especie=especie) if (marca or especie) else []
    for f in filas:
        f.numero = h.numero_whatsapp(f.cliente.telefono)
        f.primer_nombre = h.primer_nombre(f.cliente)
    return _pagina(request, "manada/promociones.html", empresa, "promociones", title="Listas para promociones",
                   marcas=h.marcas_compradas(empresa), marca=marca, especie=especie,
                   especies=Mascota.Especie.choices, filas=filas)
