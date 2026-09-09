# Auditoría UX de operaciones — ALLPETCR ERP

**Fecha:** 26 de agosto de 2026
**Método:** lectura directa del código en `CLAUDE/allpetcr-erp`. Cada afirmación cita archivo y línea. Los conteos de campos del catálogo se midieron sobre `data/INVENTARIO_ALLPETCR.xlsx` con openpyxl, no se estimaron.
**Alcance leído:** las 31 plantillas de `templates/`, las vistas, formularios, servicios y URLs de `caja`, `catalogo`, `compras`, `inventario`, `ventas`, `core`; `static/css/allpetcr.css`; los comandos `sincronizar_inventario` y `exportar_catalogo_web`; y `AUDITORIA_UX_2026-07-22.md`.
**No verificado:** la base real. `db.sqlite3` está en 0 bytes y PostgreSQL no es accesible desde acá. Todo lo que digo sobre datos sale del Excel fuente, no de la base.

---

## 0. Lo primero: dos premisas del encargo son falsas, y una de ellas cambia el plan

**Premisa 1 — «estas cinco plantillas extienden `admin/base_site.html` sin cargar `allpetcr.css`».** No es cierto hoy. Las cinco hacen `{% block extrahead %}{{ block.super }}` y `base_site.html:18` linkea la hoja compartida. Además ya fueron rediseñadas: tienen tarjeta, inputs grandes, foco azul de marca y mensajes con color.

| Plantilla | `{{ block.super }}` | Rediseñada |
|---|---|---|
| `templates/caja/abrir.html:6` | sí | sí (`.oc-*`, 66 líneas) |
| `templates/caja/cerrar.html:6` | sí | sí (`.cc-*`, 93 líneas) |
| `templates/inventario/ajuste.html:6` | sí | sí (`.aj-*`, 91 líneas) |
| `templates/catalogo/precios.html` | sí | sí (`.pr-*`, con margen, markup y tooltips) |
| `templates/ventas/estado_cuenta.html:6` | sí | sí (`.ec-*`, métricas + badges) |

Barrí las 8 plantillas del sistema que extienden `base_site.html` y sobreescriben `extrahead`. **Hay exactamente una que sí pierde `allpetcr.css`, y no está en la lista:**

> `templates/catalogo/precio_producto.html:6` abre `{% block extrahead %}<style>` sin `{{ block.super }}`. Se cae el `<link>` a `allpetcr.css` y con él todo el tema del admin (barra blanca, azul de marca, tipografía). Es la pantalla donde el gerente cambia un precio.

Arreglo, una línea:

```django
{# templates/catalogo/precio_producto.html:6 #}
{% block extrahead %}{{ block.super }}<style>
```

**Premisa 2 — «el campo `mascota` está vacío en la mayoría de productos».** Está vacío en la *base*, no en los datos. Ver sección 4: el Excel lo trae lleno en 532 de 532 productos y el comando que lo carga ya existe y ya se ensayó.

---

## 1. Recorrido de una venta de mostrador, hoy

Supuestos: caja abierta, producto con etiqueta legible, pago en efectivo. Cuento clic = clic de mouse; campo = dato que la persona elige o escribe.

| # | Acción | Clics | Campos | Anclaje |
|---|---|---|---|---|
| 1 | En Inicio, el héroe ya dice **«Ir a vender»** porque detecta caja abierta. Un clic. | 1 | 0 | `templates/core/dashboard.html:212-226` |
| 2 | El cursor ya está en el escáner al cargar el POS. | 0 | 0 | `pos.html:489` `document.getElementById('buscar').focus()` |
| 3 | Pistola al código. La pistola manda Enter; el handler busca coincidencia **exacta** por `codigo_barras` o `sku` y agrega la línea. | 0 | 0 | `pos.html:459-470` |
| 4 | Repetir por cada producto. | 0 | 0 | ídem |
| 5 | Cobrar: **F1** efectivo, **F2** tarjeta, **F3** SINPE. Sin soltar la pistola. | 0 | 0 | `pos.html:472-483` |
| 6 | Sale el tiquete en ventana aparte, se limpia el carrito, se limpia el cliente y el cursor vuelve al escáner. | 0 | 0 | `pos.html:445-455` |

**Total: 1 clic desde Inicio, 0 clics dentro del POS, 0 campos.** Con mouse en vez de teclado: 2 clics. Ninguna tarea supera 3 pasos.

Esto es correcto y no lo tocaría. Es más rápido que la mayoría de POS comerciales.

### 1.b El mismo flujo al mínimo absoluto

`escanear → F1`. Una acción física y una tecla. No hay nada que quitar sin perder control: quitar el paso de cobro significaría adivinar el medio de pago, y el medio de pago es lo que determina si entra efectivo a la caja, si va a Bancos o si crea una cuenta por cobrar (`ventas/services.py`, `ventas/cxc.py`). No es ceremonia; es la única decisión real de la venta.

### 1.c Pero el conteo mide el camino feliz, y el camino feliz no es el problema

El flujo de arriba asume que la etiqueta se escanea. Cuando no —etiqueta despegada, producto sin código impreso, producto que el proveedor trajo suelto— el cajero escribe el nombre. Ahí el sistema se cae, y es medible:

Sobre los 532 productos del Excel:

- **231 nombres únicos para 532 productos.** 409 productos (77%) comparten nombre con al menos otro.
- Largo promedio del nombre: **12,1 caracteres**. Ejemplos reales: `Aro`, `Hueso`, `Juguete`, `Peluche`, `Collar isabelino`, `Frisbee`.
- Repetidos más frecuentes: `Collar isabelino` ×18, `Juguete cuerda` ×15, `Rascador cartón` ×14, `Adorno acuario` ×14, `Juguete Navideño` ×11.
- **Cero nombres contienen un dígito.** Ni talla, ni medida, ni peso.

Lo que distingue a un `Hueso` de otro vive en `descripcion` («talla L, 20×9 cm», «talla S, 11 cm»), y:

- el POS **no carga `descripcion`** — el `values()` trae `id, sku, nombre, codigo_barras, precio_venta, stock_actual, presentacion, categoria__nombre, imagen` (`ventas/views.py:44-46`);
- el buscador tampoco la mira (`pos.html:289-297`);
- y `presentacion`, que sí se muestra en la tarjeta (`pos.html:302`), **el sincronizador nunca la escribe**: el mapa de columnas `COL` no la incluye (`catalogo/management/commands/sincronizar_inventario.py:62-73`).

Consecuencia verificable: después de correr el sincronizador, el cajero que escriba «hueso» verá varias tarjetas con el mismo nombre, la misma categoría, la presentación vacía, y solo la foto y el precio para distinguirlas.

Y peor, el mensaje de error miente:

```js
// pos.html:463-465
if (!prod){ const r = filtrar(); if (r.length === 1) prod = r[0]; }
if (prod){ ... }
else { msg("No encontré ese producto: " + q, true); }
```

Con 8 coincidencias el POS dice **«No encontré ese producto: Hueso»**. Sí lo encontró: encontró ocho. Un empleado nuevo, sin capacitación, con un cliente enfrente, concluye que el producto no existe.

Arreglo mínimo, sin rediseño:

```js
// pos.html:463 — decir la verdad y dejar el filtro puesto
if (!prod){
  const r = filtrar();
  if (r.length === 1) prod = r[0];
  else if (r.length > 1){
    msg(`Hay ${r.length} productos que coinciden con "${q}". Tocá el correcto abajo.`);
    pintarGrid(); return;   // deja la búsqueda escrita y las tarjetas filtradas
  }
}
```

Y en el mismo golpe, publicar `descripcion` al POS y hacerla buscable — dos líneas en `ventas/views.py:44` (agregar `"descripcion"` al `values()`) y una en `pos.html:295`.

---

## 2. Clics y campos por tarea diaria

Entrando siempre desde Inicio.

| Tarea | Clics | Campos | Pasos reales | ¿Más de 3? |
|---|---|---|---|---|
| **Venta simple** | 1 | 0 | vender → escanear → F1 | No |
| **Abrir caja** | 2 | 2 | abrir → sucursal → fondo → confirmar | Sí |
| **Cerrar caja** | 3 | 1 | cerrar → contado → confirmar → aceptar el `confirm()` del navegador | Sí |
| **Recibir mercadería** | 2 | 2 por línea + 1 | recibir → escanear → cantidad/costo por línea → proveedor → registrar | Sí |
| **Cambiar precio** | 3 a 5 | 1 a 2 | Admin → Precios → (buscar) → Ver/cambiar → precio → guardar | Sí |
| **Ajustar stock** | — | 4 a 5 | **no hay acceso; hay que escribir la URL** | Sí |
| **Cobrar un fiado** | — | 3 | **no hay acceso, ni siquiera por URL sin saber el ID del cliente** | Sí |

### Lo que sobra en cada una

**Abrir caja** pide sucursal aunque haya una sola. `caja/forms.py:7`:

```python
sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.filter(activa=True), label="Sucursal")
```

Ni predetermina ni filtra por empresa. Corrección:

```python
# caja/forms.py
class AbrirCajaForm(forms.Form):
    """Si hay una sola sucursal activa, no se pregunta: se predetermina y el
    campo queda oculto. Preguntar lo que tiene una sola respuesta posible es
    un paso que el cajero repite todos los días sin decidir nada."""
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.none(), label="Sucursal")
    monto_apertura = forms.DecimalField(
        label="Efectivo con el que arranca el turno (₡)", min_value=0,
        max_digits=12, decimal_places=2,
        help_text="Contá el efectivo físico de la gaveta antes de escribirlo",
    )

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Sucursal.objects.filter(activa=True)
        if empresa is not None:
            qs = qs.filter(empresa=empresa)
        self.fields["sucursal"].queryset = qs
        if qs.count() == 1:
            self.fields["sucursal"].initial = qs.first()
            self.fields["sucursal"].widget = forms.HiddenInput()
```

En `caja/views.py:16` pasarle `empresa=empresa_actual(request)`, y en `abrir.html:49-53` envolver el bloque de sucursal en `{% if not form.sucursal.is_hidden %}`. Resultado: **1 clic y 1 campo.**

**Cerrar caja** termina en un `confirm()` nativo del navegador (`cerrar.html:68`) que dice «¿Confirma el cierre? La sesión quedará inmutable.» Dos problemas: «inmutable» no es castellano de mostrador, y el cuadro gris del navegador rompe la pantalla que sí está cuidada. Reemplazo dentro de la página:

```html
<!-- cerrar.html:67 — sustituye el confirm() -->
<div class="cc-actions">
  <button type="button" class="cc-btn" onclick="document.getElementById('confirmar').classList.add('on')">Cerrar caja</button>
  <a class="cc-back" href="{% url 'ventas:pos' %}">← Volver al POS</a>
</div>

<div class="apx-overlay" id="confirmar">
  <div class="apx-sheet">
    <h2>¿Cerrás la caja del turno?</h2>
    <div class="ssub">Al cerrar, el sistema compara tu conteo con lo que esperaba y guarda la diferencia.
      <b>Un cierre no se puede editar después</b>: si te equivocaste en el conteo, se corrige abriendo
      la caja de nuevo y dejando el detalle en el motivo — nunca borrando este.</div>
    <button class="close" onclick="this.closest('form') || document.forms[0].submit()">Sí, cerrar la caja</button>
    <button class="apx-btn soft block" style="margin-top:10px"
            onclick="document.getElementById('confirmar').classList.remove('on')">Todavía no</button>
  </div>
</div>
```

`.apx-overlay` y `.apx-sheet` ya existen en `allpetcr.css:111-126`. No se inventa estética; se usa la que hay.

**Recibir mercadería** son 2 campos por línea (cantidad y costo, `compras/nueva.html:404-405`) más el proveedor. Eso no es grasa: el costo por línea es el que alimenta el costo promedio ponderado del kardex (`inventario/services.py:52-55`), y si no se digita, el margen queda mal para siempre. Lo dejaría como está. Lo único que quitaría es tener que reelegir el proveedor cuando toda la entrega viene del mismo: ya está resuelto porque el selector es uno solo para toda la compra.

**Cambiar precio** son 3 clics si el producto cae en los primeros 60 (la lista carga sin buscar, `catalogo/views.py:39`) y 5 si hay que buscarlo. El paso caro es entrar al detalle solo para escribir un número. Edición en línea desde la tabla:

```html
<!-- catalogo/precios.html:142 — reemplaza la celda "Ver / cambiar →" -->
<td style="text-align:right;white-space:nowrap">
  <form method="post" action="{% url 'catalogo:precio_producto' p.pk %}" class="pr-quick">
    {% csrf_token %}
    <input type="number" name="nuevo_precio" step="1" min="0" value="{{ p.precio_venta|floatformat:0 }}"
           aria-label="Precio nuevo de {{ p.nombre }}">
    <input type="text" name="motivo" placeholder="Motivo" required>
    <button type="submit" class="apx-btn" style="padding:8px 16px;font-size:14px">Guardar</button>
  </form>
  <a class="pr-link" href="{% url 'catalogo:precio_producto' p.pk %}">Historial →</a>
</td>
```

La vista ya acepta ese POST tal cual (`catalogo/views.py:50-59`: lee `nuevo_precio` y `motivo` del POST y llama a `cambiar_precio`), así que **no hay que tocar Python**. Queda en 2 clics y 2 campos, y el cambio sigue firmado en `CambioPrecio`.

---

## 3. Las tres pantallas que existen y nadie puede encontrar

Este es el hallazgo estructural de la auditoría, y no está en el informe de julio.

Busqué en las 31 plantillas quién enlaza cada vista:

| Vista | URL | Enlaces entrantes en todo el sistema |
|---|---|---|
| `ventas:estado_cuenta` | `/pos/cliente/<id>/estado-cuenta/` | **ninguno** |
| `inventario:ajuste` | `/inventario/ajuste/` | **ninguno** |
| `catalogo:precios` | `/precios/` | 2 (`admin/index.html:256`, `core/reportes.html:67`) |
| `core:reportes` | `/reportes/` | 1 (`admin/index.html:244`) — no está en Inicio |
| `inventario:etiquetas` | `/inventario/etiquetas/` | 1 (`admin/index.html:252`) |

**El caso grave es Estado de cuenta.** Es la pantalla donde se cobra el fiado. La vista la autoriza el rol **Cajero** (`ventas/views.py:231` `@rol_requerido(CAJERO, GERENTE)`), o sea que fue diseñada para el mostrador. Pero:

- el Inicio de un cajero muestra solo *Vender* y *Abrir/Cerrar caja* — todo lo demás está detrás de `{% if es_gerente %}` (`dashboard.html:295-301`);
- la URL exige `cliente_id`, que es la llave primaria del cliente en la base;
- la única pantalla que lista los fiados pendientes, *Evidencia por cobrar*, enlaza a la **factura**, no al estado de cuenta (`core/evidencia_cxc.html:70`).

Resultado: el POS deja **fiar** con un botón grande (`pos.html:206`), y no hay ninguna ruta en la interfaz para **cobrar** ese fiado. El dinero sale por una puerta que no tiene la puerta de vuelta.

Arreglo, ~20 minutos:

```html
<!-- dashboard.html:284 — dentro de .qa-row, ANTES del {% if es_gerente %} -->
<a class="qa-item" href="/evidencia/por-cobrar/">
  <div class="qa-ic i-cash">…</div><div class="lb">Cobrar fiados</div></a>
```

```html
<!-- core/evidencia_cxc.html:69 — que el nombre del cliente lleve a su cuenta -->
<td><a href="{% url 'ventas:estado_cuenta' f.doc.cliente_id %}"
       style="color:var(--brand);font-weight:600">{{ f.doc.cliente.nombre }}</a></td>
```

Y en el POS, junto al selector de cliente, un enlace que aparezca solo cuando el cliente elegido tiene saldo. Eso cierra el circuito donde ocurre: el cliente que llega a pagar el fiado está parado en el mostrador.

**Ajuste de inventario** tampoco tiene acceso. Va en `/admin/`, no en el Inicio: corregir un conteo no es tarea de mostrador y `@rol_requerido(GERENTE)` ya lo dice (`inventario/views.py:24`).

```html
<!-- admin/index.html:252 — junto a los otros .ax-tool -->
<a class="ax-tool" href="/inventario/ajuste/">
  <div class="ti" style="background:linear-gradient(140deg,#8e8e93,#5a5a5e)">…</div>
  <div><div class="th">Corregir existencias</div>
       <div class="td">Cuando lo que hay en la bodega no coincide con lo que dice el sistema.</div></div></a>
```

**El centro de reportes** existe y está bien hecho (`core/reportes.html`, 12 tarjetas), pero solo se llega desde `/admin/`. Como el Inicio ya tiene el botón *Admin*, esto es tolerable; lo dejo como nota, no como hallazgo.

---

## 4. `mascota`: no hay que llenarlo. Hay que sincronizarlo

Medí `data/INVENTARIO_ALLPETCR.xlsx`, hoja «Inventario Claude», 532 filas con SKU:

| Mascota | Productos |
|---|---|
| Perro | 261 |
| Perro y gato | 174 |
| Gato | 70 |
| Peces | 24 |
| Otros | 2 |
| Tortugas | 1 |
| **Vacío** | **0** |

**532 de 532, sin un solo blanco.** Descripción: 532 de 532 también.

Y `sincronizar_inventario` ya lee esa columna y ya escribe el campo, tanto al crear como al actualizar:

```python
# catalogo/management/commands/sincronizar_inventario.py
COL = { ..., "mascota": 5, ... }              # línea 67
ENCABEZADOS_ESPERADOS = { ..., 5: "Mascota" }  # línea 78 — valida antes de leer una fila
mascota=_texto(fila[COL["mascota"]], 30)       # línea 246, producto nuevo
("mascota", _texto(fila[COL["mascota"]], 30)), # línea 270, producto existente
```

Y `CLAUDE.md` dice, textual: *«los comandos NO se han corrido contra la base real: sigue con 184 productos, precios viejos, sin descripciones y sin fotos»*, con el flujo completo ya ensayado contra una SQLite desechable.

**Entonces la respuesta a «cuál es la forma más rápida de llenar `mascota`» es: ninguna de las tres que se plantean.** No hace falta inferencia por nombre y categoría, ni edición masiva en el admin, ni captura en Excel. Hace falta correr un comando que ya existe, ya está probado, y está pendiente por otra razón. Los pasos están en `ACTUALIZAR_INVENTARIO.txt`.

Lo único que sí agregaría, y es barato, es que `mascota` sea visible y corregible en lote para el día que un producto entre por otra vía:

```python
# catalogo/admin.py — en ProductoAdmin
list_display = (..., "mascota", ...)
list_filter  = (..., "mascota", ...)
list_editable = (..., "mascota", ...)   # cuidado: list_editable exige que el campo NO sea el primero de list_display
```

Nota de honestidad sobre el orden: correr el sincronizador contra la base real es una decisión de negocio con consecuencias (cambia 184 productos a 532, cambia precios, da de alta stock inicial), no un arreglo de UX. Lo señalo porque bloquea este hallazgo y varios más, no porque me corresponda decidirlo.

---

## 5. `marca` y peso: la migración es correcta, la estrategia de carga propuesta no funciona acá

Confirmado: `catalogo/models.py:44-72` no tiene `marca` ni peso estructurado. `presentacion` es `CharField(max_length=120, blank=True)` (línea 51).

**Antes de proponer cómo poblarlos, medí si se puede.** Sobre los 532 nombres del Excel:

- nombres que contienen un dígito: **0**
- nombres con unidad de peso o volumen (`kg`, `g`, `ml`, `l`, `lb`, `oz`): **0**
- tokens más frecuentes: `juguete` 63, `peluche` 40, `collar` 34, `arnés` 34, `comedero` 24 — todos sustantivos de categoría, ninguna marca

Es decir: **una regla de extracción por expresiones regulares sobre `nombre` y `presentacion` acertaría en cero productos del catálogo actual.** La razón es simple y está en el modelo de negocio: el catálogo de apertura son accesorios, no alimento. Marca y peso son atributos de alimento. Cuando entren Royal Canin, Hill's y Pro Plan, esos productos vendrán con marca y peso **en los datos del proveedor**, que es de donde hay que tomarlos, no de una heurística sobre un nombre de 12 caracteres.

Mi recomendación, entonces, es partirlo en dos:

**Ahora (barato, sin riesgo):** aplicar la migración estructural, dejarla vacía, y exponer los campos en el export. Así el sitio web ya sabe leerlos el día que existan, y no hay que coordinar dos repositorios bajo presión.

```python
# catalogo/models.py
class Marca(models.Model):
    """Marca comercial. Entidad propia y no texto libre porque el sitio web
    la usa como filtro de navegación: 'Royal Canin' escrito de cuatro formas
    distintas son cuatro filtros distintos para el cliente."""
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="marcas")
    nombre = models.CharField(max_length=80)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "nombre"], name="marca_unica_por_empresa"),
        ]

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    ...
    marca = models.ForeignKey(
        Marca, null=True, blank=True, on_delete=models.PROTECT, related_name="productos",
    )
    # Masa comparable, en gramos. NO se mezclan mililitros ni unidades: el día
    # que se guarde "500" para un shampoo de 500 ml, ordenar por peso deja de
    # significar algo. Los líquidos y los paquetes siguen en `presentacion`.
    peso_gramos = models.DecimalField(
        max_digits=9, decimal_places=3, null=True, blank=True,
        verbose_name="peso (gramos)",
    )
```

```python
# catalogo/management/commands/exportar_catalogo_web.py:116 — dentro de `fila`
"marca": p.marca.nombre if p.marca_id else "",
"peso_gramos": float(p.peso_gramos) if p.peso_gramos is not None else None,
```

y agregar `.select_related("categoria", "marca")` en la línea 105 para no disparar una consulta por producto.

**Cuando entre alimento:** extender el mapa `COL` de `sincronizar_inventario` con dos columnas nuevas del Excel (`Marca`, `Peso (g)`) y agregarlas a `ENCABEZADOS_ESPERADOS`. El comando ya aborta si alguien reordena la hoja (líneas 62-83) — ese guard es el precedente correcto y hay que reusarlo, no reinventar un comando de enriquecimiento por heurística.

**El campo que sí falta hoy** no es marca ni peso: es el que distingue dos productos con el mismo nombre. Ver sección 1.c. Con 77% del catálogo compartiendo nombre, lo más rentable es llenar `presentacion` desde el Excel (agregar `"presentacion"` a `COL`, si la hoja llega a tener esa columna) o publicar `descripcion` al POS, que ya está llena al 100%.

---

## 6. Errores y deshacer

### ¿Los mensajes dicen qué hacer?

**Los que sí** — y son la mayoría de los que importan:

| Mensaje | Archivo | Por qué está bien |
|---|---|---|
| «Stock insuficiente de {sku} — {nombre}: hay X, se pidió sacar Y» | `inventario/services.py:45-49` | nombra el producto, la existencia y lo pedido |
| «El abono (₡X) excede el saldo pendiente (₡Y)» | `ventas/cxc.py:92-94` | da los dos números |
| «Crédito insuficiente para {cliente}: disponible ₡X, venta ₡Y» + aviso si el saldo denormalizado no cuadra | `ventas/cxc.py:57-66` | explica incluso el caso raro |
| «Para devolver dinero en efectivo debe tener una caja abierta. Abra la caja primero y vuelva a intentar» | `ventas/devoluciones.py:153-156` | dice exactamente el siguiente paso |
| «Para fiar, elegí primero el cliente arriba» | `pos.html:436` | señala dónde |
| «No se puede anular: la venta a crédito ya tiene abonos. Gestione primero la devolución del dinero cobrado» | `ventas/cxc.py:130-133` | dice qué hacer… salvo que la acción que nombra no existe en la interfaz (ver abajo) |

**Los que no:**

1. **`"Datos de venta inválidos."`** (`ventas/views.py:95`) y **`"Datos de compra inválidos."`** (`compras/views.py:182`) y **`"Datos de producto inválidos."`** (`compras/views.py:260`). Son el `except` genérico de `JSONDecodeError, KeyError, DoesNotExist`. No dan recuperación ni identifican el dato.

2. **El más caro: `"No se pudo conectar con el servidor."`** (`pos.html:455`, `nueva.html:443`). Es el `catch` del `fetch`. El problema no es el texto: es que **la venta pudo haberse registrado igual**. Si la conexión se corta después de que el POST llegó al servidor, la transacción se confirmó y el cajero ve un error. No hay clave de idempotencia en `registrar_venta` (`ventas/services.py`), así que si el cajero repite el cobro se crea una segunda factura y se descuenta el inventario dos veces. Mínimo, decirlo:

```js
} catch(e){
  msg("⛔ Se cortó la conexión. La venta PUDO haberse registrado. "
    + "Antes de volver a cobrar, revisá Actividad y buscá el número de tiquete.", true);
}
```

Lo correcto de fondo es una clave de idempotencia por venta, pero eso es trabajo de servidor, no de mensaje.

3. **El tiquete sale por `window.open`** (`pos.html:452`). Si el navegador bloquea la ventana emergente, el tiquete no aparece y el mensaje de éxito dice «Abriendo tiquete…» — que es falso. Un enlace de respaldo en el mismo aviso lo resuelve.

4. **El cambio de precio muestra la excepción cruda de Python** al gerente: `messages.error(request, f"No se pudo cambiar el precio: {e}")` (`catalogo/views.py:68`). Está bien que se registre en el log (línea 67, y ese `logger.exception` es correcto); lo que no está bien es que `{e}` llegue a la pantalla.

### ¿Qué se puede deshacer?

| Operación | ¿Se deshace? | Anclaje |
|---|---|---|
| Venta | Sí. Anulación total con motivo (gerente) o devolución parcial por línea | `ventas/services.py:217-219`, `ventas/devoluciones.py` |
| Compra recibida | Sí, con motivo, solo si el stock todavía alcanza | `compras/services.py:106-113` |
| Devolución | No. Es un documento propio, no se reversa | `ventas/devoluciones.py:1-10` |
| Ajuste de inventario | No se edita; se corrige con un ajuste inverso. La pantalla lo dice | `inventario/ajuste.html:41` |
| Precio | No se «deshace»; se cambia de vuelta y queda historial firmado | `catalogo/models.py:126-149` |
| Cierre de caja | No. Queda cerrado | `caja/services.py:60` |
| **Abono a crédito** | **No** | ver abajo |

**Corrección a lo que dije en la sesión anterior.** Afirmé que una factura a crédito con abono parcial queda imposible de deshacer para siempre. Es más matizado, y me equivoqué por no leer `devoluciones.py` antes de opinar:

- La **anulación** sí queda bloqueada mientras existan abonos (`ventas/cxc.py:129-133`).
- Pero la **devolución** sí resuelve el caso económico: si el cliente devuelve la mercadería, `registrar_devolucion` reduce la CxC hasta donde alcanza y **devuelve en efectivo la parte ya pagada** (`ventas/devoluciones.py:129-146`), moviendo la caja y generando el asiento.

Lo que de verdad no tiene salida es el **abono mal digitado sin mercadería de por medio**: monto equivocado, cliente equivocado, documento equivocado. Ahí no hay devolución posible (no hay producto que regrese) y tampoco hay reversa: `Abono` es de solo lectura en el admin (`ventas/admin.py:99`) y `DocumentoCxC` tiene `has_delete_permission` en falso (línea 116). La única salida es tocar la base a mano, y eso descuadra el asiento que `asentar_abono` ya generó.

Es una brecha estrecha y real. Un servicio `reversar_abono(abono, motivo, usuario)` que devuelva el saldo al documento y al cliente, saque el efectivo de la caja abierta y asiente el contrasiento cierra el círculo. Es la única operación de dinero del sistema sin vuelta.

---

## 7. Celular

Conté `@media` en las 31 plantillas: **8 la tienen, y 3 de esas son solo para impresión** (`etiquetas.html`, `tiquete.html`, y una de las tres de `factura.html`).

Con adaptación real a pantalla angosta: `core/dashboard.html` (3), `ventas/pos.html` (2, corta a una columna bajo 900px, `pos.html:146`), `compras/nueva.html` (1, línea 127), `admin/index.html` (1), `core/_evidencia_base.html` (1) y `ventas/factura.html`.

**`static/css/allpetcr.css` sigue con cero `@media`** — igual que en julio. La fuente compartida no aporta nada a móvil, así que cada pantalla nueva nace sin adaptación salvo que alguien se acuerde.

Inservibles o de alto riesgo en un teléfono angosto (tabla ancha, sin breakpoint):

| Pantalla | Columnas | Gravedad |
|---|---|---|
| `core/actividad.html` | 4 tablas, 30 encabezados | alta |
| `core/reporte_arqueo.html` | 16 | media |
| `core/evidencia_medios.html` | 14 | media |
| `catalogo/precio_producto.html` | 12 (+ pierde `allpetcr.css`) | alta |
| `ventas/estado_cuenta.html` | 7 + 4 controles de abono por fila | **la peor en la práctica** |
| `catalogo/precios.html` | 7 | media |
| `caja/cerrar.html` | 5 (movimientos) | media |
| `contabilidad/*` | 4 a 6 cada uno | baja |
| Admin de Productos | 11 columnas | media |

**Dónde pondría el esfuerzo, y por qué no en todas.** El negocio es primero en línea y la tienda física es vitrina. Nadie va a ajustar inventario ni leer un balance desde un teléfono angosto: eso se hace sentado. La excepción es **Estado de cuenta**, que se consulta de pie y frente al cliente que llegó a abonar. Esa sí la haría móvil, y con el patrón que ya existe en el POS:

```css
/* estado_cuenta.html — al final del <style> */
@media(max-width:760px){
  .ec-metrics{grid-template-columns:1fr;gap:12px}
  .ec-card table,.ec-card thead,.ec-card tbody,.ec-card th,.ec-card td,.ec-card tr{display:block}
  .ec-card thead{position:absolute;left:-9999px}          /* cabecera fuera, cada fila se rotula sola */
  .ec-card tr{border-bottom:1px solid var(--line);padding:14px 4px}
  .ec-card td{border:none;padding:4px 14px;text-align:left !important}
  .ec-card td::before{content:attr(data-l);display:block;font-size:11.5px;text-transform:uppercase;
    letter-spacing:.03em;color:var(--ink2);font-weight:600}
  .ec-form{flex-direction:column;align-items:stretch}
  .ec-form input,.ec-form select,.ec-form button{width:100% !important}
}
```

y en el HTML, agregar `data-l="Factura"`, `data-l="Fecha"`, `data-l="Saldo"`… a cada `<td>` (`estado_cuenta.html:75-95`). Es el patrón «tabla a tarjeta» sin JavaScript y sin tocar la vista de escritorio.

Ese mismo bloque, movido a `allpetcr.css` como `.apx-table.stack`, sirve después para `cerrar.html`, `precios.html` y `actividad.html` sin volver a escribirlo. **Ahí está el arreglo de la deuda de consistencia: no en rediseñar las cinco pantallas otra vez, sino en que la hoja compartida por fin tenga algo que compartir en móvil.**

---

## 8. Lenguaje técnico visible

Separo por quién lo ve, porque no es lo mismo.

### Lo que ve el mostrador (POS, abrir y cerrar caja)

Está casi limpio. El POS usa «Fiado (venta a crédito)», «Regalo», «Escaneá o buscá el producto», «Elegí cómo paga el cliente» — bien. Quedan tres:

| Visible hoy | Dónde | Sustituir por |
|---|---|---|
| `Caja #{{ sesion.pk }}` | `pos.html:173`, `cerrar.html:48` | «Turno abierto por {usuario} desde las {hora}» — el número es la llave de la base, no significa nada |
| «arqueo ciego» | `cerrar.html:49` | «Contá primero; el sistema compara después» (ya está explicado al lado, sobra el término) |
| «La sesión quedará inmutable» | `cerrar.html:68` | «Un cierre no se puede editar después» |

### Lo que ve el gerente

| Visible hoy | Dónde | Sustituir por |
|---|---|---|
| Kardex | `ajuste.html:41` y `:86`, `precios.html:88`, `precio_producto.html:43,133,153` | Historial de movimientos |
| inmutable | `ajuste.html:41` | «no se puede editar; se corrige con otro registro» |
| Bodega | `ajuste.html:59` (label del form) | «Dónde está» / «Ubicación» |
| Markup | `precios.html`, `precio_producto.html:87` | Recargo sobre el costo |
| Margen | `precios.html` | Ganancia (%) — ya tiene tooltip, es el menos urgente |
| Costo prom. | `precios.html` | Costo promedio |
| SKU crudo | `precios.html:126` | el modelo ya llama al campo «código (REF)» (`models.py:46`); la plantilla debería usar ese rótulo |

Justo es decirlo: `precios.html` ya trae tooltips que explican margen, markup y costo promedio (`precios.html:84-96`). Eso no estaba en julio y baja bastante la urgencia de esta sección.

### Lo que ve el contador

«Debe / Haber / Débitos / Balance de comprobación / factor RTS» (`contabilidad/*`). **No los traduciría.** Son los términos correctos de la profesión y el contador los espera. Traducirlos sería el error opuesto.

---

## 9. Estado de la auditoría del 22 de julio

| Hallazgo de julio | Estado verificado hoy |
|---|---|
| Abrir/cerrar caja crudos | **Ejecutado.** Tarjeta, inputs de 17px, foco de marca, mensajes con color. `abrir.html:6-32`, `cerrar.html:6-43` |
| Ajuste y Precios crudos | **Ejecutado.** `ajuste.html:6-35`, `precios.html` con margen y markup |
| Estado de cuenta crudo | **Ejecutado.** Métricas, badges de estado, abono integrado. `estado_cuenta.html:6-40` |
| POS roto en celular | **Ejecutado.** Una columna bajo 900px. `pos.html:146-166` |
| Recibir mercadería roto en celular | **Ejecutado.** `nueva.html:127` |
| Falta indicador de margen en Precios | **Ejecutado.** Margen y markup con semáforo. `precios.html:97-106` |
| No hay centro de reportes | **Ejecutado.** `core/reportes.html`, 12 tarjetas |
| Colores de marca duplicados en 5 archivos | **Parcial.** El admin y las cinco pantallas heredan de `allpetcr.css`. Siguen redeclarando `--brand` local: `pos.html`, `compras/nueva.html`, `actividad.html`, `dashboard.html` |
| Una sola fuente de estilos | **Abierto.** Cada pantalla mantiene su prefijo propio (`.oc-`, `.cc-`, `.aj-`, `.pr-`, `.ec-`) duplicando tarjeta, input y botón que ya existen como `.apx-card`, `.apx-input`, `.apx-btn` |
| Cero `@media` en `allpetcr.css` | **Abierto, sin cambio.** Sigue en 0 |
| Edición rápida de precio | **Abierto** |
| Cuadrícula con miniaturas en el admin de Productos | **Abierto** |
| Dashboard configurable, acciones directas desde alertas, modo oscuro POS | **Abiertos** |

Dos matices sobre el informe de julio, ahora que hay más evidencia:

- Decía que el POS «no le falta casi nada». Le falta lo de la sección 1.c, que en julio no era visible porque el catálogo tenía 184 productos; con 532 y 77% de nombres repetidos, sí lo es.
- Decía «cero adaptación móvil fuera del Inicio». Hoy son seis plantillas con adaptación real. El problema cambió de «no hay» a «no está en la hoja compartida».

---

## 10. Prioridad por frecuencia de uso

Lo que se hace veinte veces al día pesa más que lo que se hace una vez al mes. El orden es ese, no la gravedad estética.

| # | Hallazgo | Archivo | Impacto | Esfuerzo |
|---|---|---|---|---|
| — | La venta simple ya está en el mínimo operativo. **No tocar.** | `ventas/pos.html:459-483` | Muy alto, positivo | — |
| 1 | El POS dice «no encontré ese producto» cuando encontró varios; 77% del catálogo comparte nombre y la descripción que los distingue no llega al POS | `pos.html:454`, `ventas/views.py:44` | **Muy alto** — es el único punto donde un empleado nuevo se traba con el cliente enfrente | Bajo |
| 2 | Cobrar un fiado no tiene ningún acceso en la interfaz; el POS sí deja fiar | `dashboard.html:284`, `core/evidencia_cxc.html:70` | **Muy alto** — dinero que sale sin puerta de vuelta | Bajo |
| 3 | Abrir caja pide sucursal habiendo una sola | `caja/forms.py:7` | Alto, diario | Bajo |
| 4 | Cerrar caja termina en un `confirm()` del navegador que dice «inmutable» | `caja/cerrar.html:68` | Alto, diario | Bajo |
| 5 | «No se pudo conectar» puede ocultar una venta ya registrada; sin idempotencia, repetir duplica | `pos.html:455`, `ventas/services.py` | Alto, dinero e inventario | Bajo el mensaje / Medio la idempotencia |
| 6 | Un abono mal digitado no tiene reversa por ninguna vía | `ventas/cxc.py`, `ventas/admin.py:99` | Alto, dinero | Medio |
| 7 | `precio_producto.html` pierde `allpetcr.css` por un `block.super` faltante | `catalogo/precio_producto.html:6` | Medio | **Trivial** (una línea) |
| 8 | Ajuste de inventario no tiene acceso visible | `admin/index.html`, `inventario/urls.py:8` | Medio-alto cuando hay que corregir un conteo | Bajo |
| 9 | Cambiar un precio exige entrar al detalle | `catalogo/precios.html:142` | Medio-alto | Bajo (la vista ya acepta el POST) |
| 10 | `mascota` vacío en la base con el dato al 100% en el Excel y el comando listo | `sincronizar_inventario.py:67,246,270` | Medio-alto (habilita la navegación del sitio) | **Cero código** — decisión de negocio |
| 11 | Estado de cuenta inservible en teléfono | `ventas/estado_cuenta.html:67` | Medio | Bajo con el patrón `.apx-table.stack` |
| 12 | `allpetcr.css` sin `@media` y cinco prefijos de CSS duplicando `.apx-*` | `static/css/allpetcr.css:1` | Medio, mantenimiento | Medio |
| 13 | `marca` y peso no estructurados | `catalogo/models.py:44` | Medio, y solo cuando entre alimento | Medio |
| 14 | `mascota` no editable en lote en el admin | `catalogo/admin.py` | Bajo | Bajo |
| 15 | Tablas administrativas sin móvil (actividad, arqueo, contabilidad) | varios | Bajo — no se usan de pie | Medio |

**Los cinco primeros suman menos de un día de trabajo y todos tocan el mostrador.** El 7 son treinta segundos.

---

## Límites de esta auditoría

- **No hay telemetría de uso por pantalla.** El orden de la sección 10 sale del rol que autoriza cada vista y de la naturaleza de la tarea, no de datos de uso reales. Es inferencia razonada, no medición.
- **No pude ver la base de producción.** Los conteos del catálogo salen del Excel fuente. Si la base real diverge del Excel, las secciones 4 y 5 cambian.
- **No corrí el sistema.** No hay capturas ni pruebas de navegador. Todo sale de leer el código, que es lo que el navegador ejecuta, pero no sustituye ver a un cajero usarlo. La prueba que más valor daría ahora no es otra auditoría: es sentar a alguien que nunca vio el sistema frente al POS con diez productos y mirarlo sin ayudarlo.
