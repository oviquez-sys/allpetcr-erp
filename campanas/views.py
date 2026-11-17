"""Pantallas de campañas (gerente): crear y revisar la campaña, ver quién
participa, congelar la lista, sortear, entregar el premio y medir.

Las reglas no viven acá: `reglas.py` (números y beneficios), `sorteo.py`
(lista, sorteo, entrega) y `medicion.py` (resultados).
"""
import csv
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogo.models import Producto
from core.roles import GERENTE, rol_requerido
from core.tenancy import empresa_actual

from . import demo, medicion, plantillas, reglas, sorteo
from .models import Campana, CanastaProducto, MovimientoNumeros, Participante

_FORMATO = "%Y-%m-%dT%H:%M"


def _fecha():
    # <input type="datetime-local">: se escribe y se lee en hora de Costa Rica
    # (Django convierte con TIME_ZONE); en la base queda con zona.
    return forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=_FORMATO), input_formats=[_FORMATO],
    )


class CampanaForm(forms.ModelForm):
    inicio = _fecha()
    cierre = _fecha()
    sorteo_en = _fecha()
    envio_gratis_hasta = _fecha()

    class Meta:
        model = Campana
        fields = ["nombre", "slug", "premio", "inicio", "cierre", "sorteo_en",
                  "numeros_inscripcion", "numeros_compra", "numeros_bono", "umbral_bono", "compra_minima",
                  "envio_gratis", "envio_gratis_hasta", "zonas_envio",
                  "reemplaza_bienvenida", "despues",
                  "bases", "suplentes", "plazo_reclamo_dias", "procedimiento_sin_respuesta",
                  "costo_impresion", "costo_reparto", "otros_costos"]
        widgets = {
            "bases": forms.Textarea(attrs={"rows": 22}),
            "zonas_envio": forms.Textarea(attrs={"rows": 3}),
            "procedimiento_sin_respuesta": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields["envio_gratis_hasta"].required = False
        self.fields["inicio"].label = "Inicio (hora de Costa Rica)"
        self.fields["cierre"].label = "Cierre de inscripciones (hora de Costa Rica)"
        self.fields["sorteo_en"].label = "Fecha y hora del sorteo (hora de Costa Rica)"
        self.fields["envio_gratis_hasta"].label = "Envío gratis hasta (vacío = hasta el cierre)"

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        repetida = Campana.objects.filter(empresa=self.empresa, slug=slug).exclude(pk=self.instance.pk)
        if repetida.exists():
            raise ValidationError("Ya hay una campaña con ese nombre corto.")
        return slug


class CostosForm(forms.ModelForm):
    """Lo único que se cambia con la campaña en marcha: lo que no altera lo
    que el cliente aceptó al inscribirse."""

    class Meta:
        model = Campana
        fields = ["costo_impresion", "costo_reparto", "otros_costos", "despues"]


def _campana(request, pk):
    return get_object_or_404(Campana, pk=pk, empresa=empresa_actual(request))


def _volver(campana, pestana="resumen"):
    return redirect(f"{campana_url(campana)}?t={pestana}")


def campana_url(campana):
    from django.urls import reverse
    return reverse("campanas:detalle", args=[campana.pk])


def _error(request, e):
    messages.error(request, " ".join(e.messages))


@rol_requerido(GERENTE)
def lista(request):
    empresa = empresa_actual(request)
    campanas = list(Campana.objects.filter(empresa=empresa))
    for c in campanas:
        c.n_participantes = c.participantes.count()
    return render(request, "campanas/lista.html", {
        "title": "Campañas", "campanas": [c for c in campanas if not c.es_demo],
        "demo": next((c for c in campanas if c.es_demo), None),
        "hay_navidad": any(c.slug == "navidad-2026" for c in campanas),
    })


@rol_requerido(GERENTE)
def editar(request, pk=None):
    empresa = empresa_actual(request)
    campana = _campana(request, pk) if pk else None
    if campana is not None and campana.es_demo:
        messages.error(request, "La demostración no se edita: se vuelve a crear desde la lista.")
        return redirect("campanas:detalle", pk=campana.pk)
    borrador = campana is None or campana.estado == Campana.Estado.BORRADOR
    Formulario = CampanaForm if borrador else CostosForm
    kwargs = {"empresa": empresa} if borrador else {}
    inicial = plantillas.navidad_2026(empresa) if (campana is None and request.GET.get("plantilla") == "navidad") else None
    form = Formulario(request.POST or None, instance=campana, initial=inicial, **kwargs)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.empresa = empresa
        obj.save()
        messages.success(request, "Guardado. La campaña sigue apagada hasta que la actives."
                         if obj.estado == Campana.Estado.BORRADOR else "Guardado.")
        return redirect("campanas:detalle", pk=obj.pk)
    return render(request, "campanas/editar.html", {
        "title": campana.nombre if campana else "Nueva campaña", "form": form, "campana": campana,
        "borrador": borrador,
    })


def _ejemplos(campana):
    """La tabla «qué pasa con una compra de…» que Oscar pidió ver antes de
    activar: sale de la misma función que usa la caja."""
    u = campana.umbral_bono
    montos = sorted({Decimal("5000"), u - 1500, u, u + 1, u + 5000} | (
        {campana.compra_minima} if campana.compra_minima else set()))
    filas = []
    for monto in montos:
        if monto <= 0:
            continue
        hab, bono = reglas.numeros_por_monto(campana, monto)
        filas.append({"monto": monto, "habituales": hab, "bono": bono, "total": hab + bono,
                      "envio": campana.envio_gratis and monto > u})
    return filas


@rol_requerido(GERENTE)
def detalle(request, pk):
    campana = _campana(request, pk)
    pestana = request.GET.get("t") or "resumen"
    if pestana not in ("resumen", "participantes", "sorteo", "canasta", "medicion"):
        pestana = "resumen"
    ctx = {"title": campana.nombre, "campana": campana, "pestana": pestana, "ahora": timezone.now(),
           "puede_sortear": sorteo.puede_sortear(request.user),
           "sorteo": getattr(campana, "sorteo", None) if hasattr(campana, "sorteo") else None}
    s = ctx["sorteo"]
    if pestana == "resumen":
        ctx.update(
            ejemplos=_ejemplos(campana), zonas=campana.lista_zonas,
            pendientes=campana.bases.count(plantillas.POR_DEFINIR),
            n_participantes=campana.participantes.count(),
            otra_activa=Campana.objects.filter(empresa=campana.empresa, es_demo=False,
                                               estado=Campana.Estado.ACTIVA).exclude(pk=campana.pk).first(),
        )
    elif pestana == "participantes":
        saldos = dict(MovimientoNumeros.objects.filter(campana=campana).values_list("participante")
                      .annotate(t=Sum("cantidad")))
        filas = [{"p": p, "numeros": saldos.get(p.pk, 0)}
                 for p in campana.participantes.select_related("cliente", "cliente__manada")]
        ctx.update(filas=filas, total_numeros=sum(f["numeros"] for f in filas))
    elif pestana == "sorteo":
        ctx.update(
            lista_previa=None if s else sorteo.armar_lista(campana),
            cambio=bool(s) and sorteo.cambios_despues_de_congelar(s),
            adjudicaciones=list(s.adjudicaciones.select_related("participante__cliente")) if s else [],
            titular=sorteo.titular(s) if s and s.realizado else None,
        )
        if ctx["lista_previa"] is not None:
            ctx["total_previo"] = sum(f["numeros"] for f in ctx["lista_previa"])
    elif pestana == "canasta":
        versiones = []
        for clave, nombre in CanastaProducto.Version.choices:
            items = list(campana.canasta.filter(version=clave).select_related("producto"))
            versiones.append({
                "clave": clave, "nombre": nombre, "items": items,
                "unidades": sum(i.cantidad for i in items), "costo": sorteo.costo_canasta(campana, clave),
                "faltan": [i for i in items if i.producto.stock_actual < i.cantidad],
            })
        ctx.update(versiones=versiones, titular=sorteo.titular(s) if s and s.realizado else None,
                   entrega=getattr(s, "entrega", None) if s and hasattr(s, "entrega") else None)
    else:
        ctx["m"] = medicion.resumen(campana)
    return render(request, "campanas/detalle.html", ctx)


@rol_requerido(GERENTE)
@require_POST
def accion(request, pk):
    """Todas las acciones de la campaña pasan por acá: cada una es un POST
    con `accion`, y lo que valida es el servicio, no el botón."""
    campana = _campana(request, pk)
    que = request.POST.get("accion")
    try:
        if que == "activar":
            if request.POST.get("revise") != "1":
                raise ValidationError("Marcá la casilla de que revisaste el monto, las zonas y las fechas.")
            reglas.activar(campana, request.user)
            messages.success(request, "Campaña activada. Desde ya la caja y la web inscriben, y no se emiten "
                                      "cupones de bienvenida nuevos.")
            return _volver(campana)
        if que == "congelar":
            if not sorteo.puede_sortear(request.user):
                raise ValidationError("No tenés permiso para congelar la lista.")
            s = sorteo.congelar(campana, request.user)
            messages.success(request, f"Lista congelada: {s.total_participantes} participantes y "
                                      f"{s.total_numeros} números.")
            return _volver(campana, "sorteo")
        if que == "sortear":
            s, nuevo = sorteo.sortear(campana, request.user)
            ganador = sorteo.titular(s) or s.adjudicaciones.first()
            nombre = ganador.participante.cliente.nombre if ganador else "—"
            if nuevo:
                messages.success(request, f"Sorteo realizado. Salió el número {s.numero_ganador}: {nombre}.")
            else:
                messages.info(request, f"El sorteo ya se había realizado el "
                                       f"{timezone.localtime(s.realizado_en):%d/%m/%Y a las %I:%M %p}. "
                                       f"Este es el resultado guardado: número {s.numero_ganador}.")
            return _volver(campana, "sorteo")
        if que == "no_respondio":
            siguiente = sorteo.no_respondio(campana.sorteo, request.user, nota=request.POST.get("nota", ""))
            messages.success(request, f"Anotado. Ahora el premio es de {siguiente.participante.cliente.nombre} "
                                      f"({siguiente.lugar.lower()})." if siguiente else
                             "Anotado. No quedan suplentes: el premio queda desierto.")
            return _volver(campana, "sorteo")
        if que == "canasta_agregar":
            _agregar_a_canasta(request, campana)
            return _volver(campana, "canasta")
        if que == "canasta_quitar":
            campana.canasta.filter(pk=request.POST.get("item")).delete()
            return _volver(campana, "canasta")
        if que == "entregar":
            from caja.services import sesion_abierta_de
            e = sorteo.entregar(
                campana.sorteo, version=request.POST.get("version"), usuario=request.user,
                recibe_nombre=request.POST.get("recibe_nombre"), nota=request.POST.get("nota", ""),
                recibe_identificacion=request.POST.get("recibe_identificacion", ""),
                sesion_caja=sesion_abierta_de(request.user),
            )
            messages.success(request, f"Entrega registrada ({e.factura.numero}). Los productos ya salieron del "
                                      f"inventario; costo ₡{e.costo:,.0f}.".replace(",", "."))
            return _volver(campana, "canasta")
        if que == "finalizar":
            reglas.finalizar(campana, request.user)
            messages.success(request, "Campaña finalizada. " + (
                "Vuelve el regalo de bienvenida de La manada." if campana.despues == Campana.Despues.BIENVENIDA
                else "Sigue sin emitirse el regalo de bienvenida, como quedó configurado."))
            return _volver(campana)
        if que == "borrar" and campana.estado == Campana.Estado.BORRADOR and not campana.participantes.exists():
            campana.delete()
            messages.success(request, "Borrador eliminado.")
            return redirect("campanas:lista")
        raise ValidationError("Acción desconocida.")
    except ValidationError as e:
        _error(request, e)
    return _volver(campana, request.POST.get("t") or "resumen")


def _agregar_a_canasta(request, campana):
    if hasattr(campana, "sorteo") and hasattr(campana.sorteo, "entrega"):
        raise ValidationError("El premio ya se entregó: la canasta no se cambia.")
    version = request.POST.get("version")
    if version not in CanastaProducto.Version.values:
        raise ValidationError("Elegí si es la canasta de perro o la de gato.")
    codigo = (request.POST.get("codigo") or "").strip()
    productos = Producto.objects.filter(empresa=campana.empresa, activo=True)
    producto = (productos.filter(codigo_barras=codigo).first() or productos.filter(sku__iexact=codigo).first()
                ) if codigo else None
    if producto is None:
        raise ValidationError(f"No encontré un producto con el código «{codigo}». Escaneá su código de barras.")
    try:
        cantidad = max(1, int(request.POST.get("cantidad") or 1))
    except ValueError:
        raise ValidationError("La cantidad tiene que ser un número.")
    item, creado = CanastaProducto.objects.get_or_create(
        campana=campana, version=version, producto=producto, defaults={"cantidad": cantidad})
    if not creado:
        item.cantidad += cantidad
        item.save(update_fields=["cantidad"])
    messages.success(request, f"Agregado: {producto.nombre}.")


@rol_requerido(GERENTE)
def acta(request, pk):
    """El documento para formalizar el acto: se imprime o se guarda en PDF
    desde el navegador. Antes del sorteo sirve como constancia de la lista."""
    campana = _campana(request, pk)
    s = get_object_or_404(sorteo.Sorteo, campana=campana)
    return render(request, "campanas/acta.html", {
        "campana": campana, "sorteo": s, "empresa": campana.empresa,
        "adjudicaciones": list(s.adjudicaciones.select_related("participante__cliente")),
        "entrega": getattr(s, "entrega", None) if hasattr(s, "entrega") else None,
        "huella_ok": sorteo.huella_de(s.lista) == s.huella,
    })


@rol_requerido(GERENTE)
def lista_csv(request, pk):
    """La lista congelada, para adjuntarla al acta o abrirla en Excel."""
    campana = _campana(request, pk)
    s = get_object_or_404(sorteo.Sorteo, campana=campana)
    r = HttpResponse(content_type="text/csv; charset=utf-8")
    r["Content-Disposition"] = f'attachment; filename="lista-{campana.slug}.csv"'
    r.write("﻿")   # para que Excel lea bien las tildes
    w = csv.writer(r, delimiter=";")
    w.writerow(["Participante", "Teléfono (últimos 4)", "Números", "Desde", "Hasta"])
    for f in s.lista:
        w.writerow([f["nombre"], f["telefono"], f["numeros"], f["desde"], f["hasta"]])
    w.writerow([])
    w.writerow(["Huella SHA-256", s.huella])
    w.writerow(["Congelada", timezone.localtime(s.congelada_en).strftime("%d/%m/%Y %I:%M %p")])
    return r


@rol_requerido(GERENTE)
def participantes_csv(request, pk):
    campana = _campana(request, pk)
    r = HttpResponse(content_type="text/csv; charset=utf-8")
    r["Content-Disposition"] = f'attachment; filename="participantes-{campana.slug}.csv"'
    r.write("﻿")
    w = csv.writer(r, delimiter=";")
    w.writerow(["Nombre", "WhatsApp", "Correo", "Inscrito el", "Canal", "Origen de la visita", "Números",
                "Cliente nuevo", "Miembro nuevo", "Acepta promociones"])
    for p in campana.participantes.select_related("cliente", "cliente__manada"):
        perfil = getattr(p.cliente, "manada", None) if hasattr(p.cliente, "manada") else None
        w.writerow([p.cliente.nombre, p.cliente.telefono, p.cliente.email,
                    timezone.localtime(p.creado_en).strftime("%d/%m/%Y %H:%M"), p.get_canal_display(),
                    p.origen_texto, reglas.saldo(p), "sí" if p.cliente_nuevo else "no",
                    "sí" if p.miembro_nuevo else "no",
                    "sí" if perfil is not None and perfil.acepta_promociones else "no"])
    return r


@rol_requerido(GERENTE)
@require_POST
def demostracion(request):
    """Crea (o vuelve a crear) la demostración con datos ficticios, o la borra."""
    empresa = empresa_actual(request)
    if request.POST.get("accion") == "borrar":
        demo.borrar(empresa)
        messages.success(request, "Demostración borrada.")
        return redirect("campanas:lista")
    campana = demo.crear(empresa)
    messages.success(request, "Demostración lista: son datos ficticios, no tocan ventas ni inventario.")
    return redirect("campanas:detalle", pk=campana.pk)
