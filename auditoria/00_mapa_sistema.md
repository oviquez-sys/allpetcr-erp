# Fase 0 — Mapa de descubrimiento del sistema

> Generado según `prompt_maestro_auditoria_v2.md`. **Alcance de esta sesión:
> solo Fase 0** — descubrimiento y mapeo, sin juicios de severidad ni
> veredictos de seguridad (eso corresponde a las Fases 1 en adelante). Las
> cinco preguntas de 0.A se responden como determinaciones de hecho
> (EXISTE / EXISTE PARCIAL / NO EXISTE), no como hallazgos.
>
> Etiquetas: `[HECHO]` verificado con cita `archivo:línea` · `[NO ENCONTRADO]`
> se buscó explícitamente y no apareció · `[NO VERIFICADO]` no se pudo
> comprobar con el método usado en esta sesión.

---

## 0.A — Las cinco preguntas que se responden primero

### 1. ¿Existe facturación electrónica funcional para Costa Rica?

**NO EXISTE.** `[HECHO]`

- Búsqueda en todo el repo (excluido `.venv`) de `clave_numerica`, `.p12`,
  `api.hacienda`, `tribunet`, `xml` de factura, firma digital, certificado:
  sin resultados de implementación real — ningún archivo `.py` del proyecto
  contiene generación de XML v4.4, clave numérica de 50 dígitos, firma con
  `.p12`, ni llamadas a un API de Hacienda.
- `Empresa.Regimen` (`core/models.py:9-11`) define dos valores:
  `SIMPLIFICADO` ("Régimen de Tributación Simplificada", el `default`) y
  `TRADICIONAL` ("Régimen tradicional (IVA + FE v4.4)" — texto literal del
  choice, `core/models.py:11`). El régimen `TRADICIONAL` está declarado como
  opción pero no tiene ningún motor de facturación electrónica detrás; es un
  valor de enum sin implementación.
- El motor fiscal de ventas (`ventas/services.py:_desglose_fiscal`,
  líneas 28-34) solo decide si desglosa IVA en el precio o no, según el
  régimen. No genera ningún documento tributario electrónico.
- `contabilidad/views.py` tiene una vista `iva_trimestral` (`contabilidad/views.py:161-162`
  aprox., ver mapa 0.B) que es un reporte de IVA, no un emisor de comprobantes.
- No hay `.p12`, `.pem` ni `.key` en el repositorio (confirmado por búsqueda
  de archivos, fuera de `.venv`).
- No aplica la sub-pregunta de dónde vive el certificado, porque no existe
  certificado.

**Consecuencia declarada por el propio prompt maestro** (regla 0.A.1): si no
existe, es un punto que cualquier fase posterior de cumplimiento (Fase 4)
debe tratar como bloqueante. Esta sesión no evalúa severidad — solo constata
el hecho.

**Límite de esta determinación** `[NO VERIFICADO]`: no se verificó con un
contador si el régimen RTS (que hoy es el `default`, `core/models.py:20`)
exime legalmente de facturación electrónica en Costa Rica, ni desde cuándo.
Es un punto de negocio, no de código — señalado ya en `CLAUDE.md` como
pendiente ("decidir sobre régimen"/cédula jurídica).

### 2. ¿El stock es realmente derivado del kardex, o hay caminos que lo escriben directamente?

**Un solo camino de escritura, y es el kardex — con una excepción de solo lectura para el admin.** `[HECHO]`

- `catalogo.Producto.stock_actual` y `costo_promedio` (`catalogo/models.py:66,68`)
  se escriben en exactamente un lugar del código de aplicación:
  `inventario/services.py:registrar_movimiento` (líneas 23-74), función
  `@transaction.atomic` que:
  1. Bloquea la fila del producto (`select_for_update()`, línea 41).
  2. Calcula `nuevo_stock` y rechaza negativos (`ValidationError`, líneas 43-49).
  3. Recalcula costo promedio ponderado solo si la entrada trae costo
     (líneas 51-57).
  4. Crea el `MovimientoInventario` (líneas 59-70) y **en la misma
     transacción** guarda `producto.stock_actual`/`costo_promedio`
     (línea 71-73, `update_fields=["stock_actual","costo_promedio","actualizado_en"]`).
- Todos los flujos que mueven stock pasan por esta función, sin excepción
  encontrada: venta (`ventas/services.py:118-122`), anulación de venta
  (`ventas/services.py:170-174`), devolución de venta
  (`ventas/devoluciones.py:113-117`), compra recibida
  (`compras/services.py:67-71`), anulación de compra
  (`compras/services.py:117-121`, con cantidad negativa), ajuste manual
  (`inventario/views.py:33-42`, vía `AjusteInventarioForm`), carga inicial e
  importación desde Excel (`catalogo/management/commands/importar_inventario.py`,
  `sincronizar_inventario.py` — ambos delegan a `registrar_movimiento` según
  el mapa de la Sección 0.B).
- **Excepción encontrada, de solo lectura**: `inventario/admin.py` (31
  líneas) registra `Bodega` y `MovimientoInventario` en el admin de Django
  "sin `add/change/delete permission`" (reportado por el agente de
  exploración de `inventario`/`caja`/`compras`) — es decir, el admin no
  permite crear ni editar movimientos ni bodegas, solo consultarlos. No se
  encontró ningún `ModelAdmin` para `catalogo.Producto` que exponga
  `stock_actual`/`costo_promedio` como campos editables (`[NO VERIFICADO]`:
  `catalogo/admin.py` no fue leído en esta sesión — queda como pendiente
  explícito, ver tabla de cobertura).
- Migraciones con `RunPython`: solo `inventario/migrations/0005_bodega_principal_and_more.py`
  (marca/desmarca bodega principal, no toca stock) y `core/migrations/0003_roles.py`
  (crea/borra grupos de rol). Ninguna migración de datos escribe
  `stock_actual` directamente.

**Pendiente de verificar** `[NO VERIFICADO]`: contenido de `catalogo/admin.py`
y `compras/admin.py` en detalle (se citó su existencia pero no se leyó línea
por línea en esta sesión, salvo el fragmento de `compras/admin.py` que el
agente reportó: `LineaCompraInline.get_readonly_fields` bloquea edición si la
compra no está en `BORRADOR`, y `CompraAdmin.accion_recibir` invoca
`recibir_compra` desde el admin — ese camino SÍ pasa por el servicio, no lo
evita).

### 3. ¿`AuditLog` cubre realmente las acciones críticas?

**Cobertura documentada y deliberadamente parcial — no se evaluó si es suficiente (eso es Fase 8).** `[HECHO]` para lo que registra; `[NO EVALUADO]` si alcanza.

- `core/signals.py` conecta `pre_save`/`post_save`/`post_delete` **solo** a
  los modelos listados en `AUDITED` (líneas 47-63): `catalogo.categoria`,
  `catalogo.impuesto`, `catalogo.producto`, `inventario.bodega`,
  `inventario.movimientoinventario`, `caja.sesioncaja`, `caja.movimientocaja`,
  `ventas.cliente`, `ventas.facturaventa`, `ventas.documentocxc`,
  `ventas.abono`, `contabilidad.asiento`, `contabilidad.cuentacontable`,
  `compras.proveedor`, `compras.compra`.
- Explícitamente **excluidos a propósito** (`NO_AUDITADOS_A_PROPOSITO`,
  `core/signals.py:69-73`): `ventas.lineaventa`, `contabilidad.lineaasiento`,
  `compras.lineacompra` — su documento padre sí se audita y es inmutable
  (razón documentada en el comentario del módulo, líneas 8-35).
- El registro guarda: usuario (vía `core.middleware.get_current_user`), IP
  (vía `get_current_ip`, con la lógica anti-spoofing de
  `core/middleware.py:ip_de_la_peticion`), tabla, `objeto_id`, acción
  (crear/editar/borrar), y `antes`/`despues` — pero `antes` en una edición
  solo guarda los campos que **cambiaron** (`_solo_lo_que_cambio`,
  `core/signals.py:99-108`), no el objeto completo.
- Sobre "puede el propio administrador borrar o alterar el log": no se
  encontró (en esta sesión) un `ModelAdmin` para `AuditLog` — no se verificó
  si está registrado en `core/admin.py` `[NO VERIFICADO]`, `core/admin.py`
  no se leyó. `AuditLog` en sí no tiene protección a nivel de modelo contra
  `DELETE`; si está expuesto sin restricciones en el admin de Django (que
  requiere ser Gerente, `core/middleware.py:AdminSoloGerente`), un gerente
  con acceso a `/admin/` podría en teoría borrar filas — **esto no se
  confirmó ni se descartó**, queda para Fase 1/Fase 8.
- Acciones que el prompt maestro exige como mínimo (Fase 8) — login/logout,
  descuentos sobre umbral, exportaciones, ejecución de management commands,
  acciones desde el admin — **no se contrastaron aquí uno por uno**; ese
  contraste explícito es el contenido de la Fase 8, no de esta Fase 0.

### 4. ¿Está garantizado el aislamiento entre empresas y sucursales?

**Existe un mecanismo central (`core/tenancy.py`) pero su propio autor documenta que hoy es de una sola empresa; su cobertura real vista por vista no se auditó en esta sesión — es materia de Fase 1.** `[HECHO]` para lo que existe; `[NO EVALUADO]` la cobertura.

- `core/tenancy.py:empresa_actual(request)` (líneas 27-39): hoy devuelve
  `Empresa.objects.first()` — es decir, con una sola empresa en el sistema,
  cualquier usuario staff "pertenece" a ella por diseño. El propio docstring
  del módulo (líneas 1-23) dice explícitamente: *"Hoy no es explotable —hay
  una sola empresa y todo usuario staff pertenece a ella— pero el día que el
  sistema sea multi-empresa, un usuario de la empresa A podría ver o anular
  un documento de la empresa B con solo cambiar el número en la URL"*.
- `core/tenancy.py:documento_de_empresa(...)` (líneas 42-56) es el
  `get_object_or_404` acotado a empresa, y responde 404 (no 403) si el
  documento es de otra empresa. Encontrado en uso explícito en:
  `ventas/views.py:104,117,131,176,193,231,247` (tiquete, factura,
  factura_enviar, anular, devolver, estado_cuenta, abonar) y
  `contabilidad/views.py:72` (reabrir cierre) y `compras/views.py:191`
  (anular compra).
- **No verificado en esta sesión**: si TODAS las vistas que abren un
  documento por ID usan `documento_de_empresa` o si alguna usa
  `get_object_or_404` directo sin pasar por tenancy — eso requeriría grep
  exhaustivo de `get_object_or_404` en las 7 apps, que no se hizo aquí.
  `[NO VERIFICADO]` — recomendado como primer paso de Fase 1 (IDOR).
- Sucursal: no se encontró un mecanismo equivalente a `empresa_actual` para
  filtrar por sucursal del usuario — los querysets de `Producto` filtran por
  `empresa` (ej. `ventas/views.py:42`, `compras/views.py:119`) pero no se
  verificó filtrado por sucursal específica del cajero. `[NO VERIFICADO]`.

### 5. ¿Los asientos contables cuadran siempre y el cierre de periodo realmente cierra?

**Ambas cosas están garantizadas, pero a nivel de aplicación (un único punto de entrada), no a nivel de base de datos.** `[HECHO]`

- **Cuadre débito=crédito**: no hay validación en el modelo (`Asiento`ni
  `LineaAsiento` en `contabilidad/models.py` no tienen `clean()`/`save()`
  que sumen debe/haber — la única pieza relacionada en el modelo es la
  propiedad de solo lectura `Asiento.cuadra`, `contabilidad/models.py:77-79`,
  que no bloquea nada por sí sola). La validación real está en
  `contabilidad/services.py:registrar_asiento` (líneas 191-196):
  ```
  total_debe = sum(...); total_haber = sum(...)
  if total_debe != total_haber:
      raise ValidationError(f"Asiento descuadrado: debe {total_debe} ≠ haber {total_haber}.")
  ```
  Es aplicación (Python), no un `CHECK` de base de datos a nivel de
  agregado — sí existe un `CheckConstraint` de fila individual
  (`LineaAsiento`: `debe>0 XOR haber>0`, `contabilidad/models.py:130-137`),
  pero ese constraint no puede expresar "la suma del asiento cuadra", eso
  solo lo puede hacer código de aplicación o un trigger (no se encontró
  trigger).
- **¿Todo asiento pasa por `registrar_asiento`?** Se verificó que
  `ventas/contabilizar.py` (asentar_venta/devolución/abono/anulación) y
  `compras/services.py` (recibir_compra/anular_compra) llaman exclusivamente
  a `contabilidad.services.registrar_asiento` — no se encontró ningún
  `Asiento.objects.create(...)` fuera de ese archivo en las apps
  inspeccionadas (`[NO VERIFICADO]` de forma exhaustiva en TODO el repo con
  un grep global — se verificó por lectura directa de los módulos que
  generan asientos, no por búsqueda ciega).
- **Cierre de periodo**: `CierrePeriodo` (`contabilidad/models.py:82`) no
  tiene ningún chequeo en el modelo. El bloqueo real está, otra vez, en
  `contabilidad/services.py:registrar_asiento` (líneas 183-189): antes de
  crear el asiento, calcula `fecha_bloqueo(empresa)` (mayor `fecha_cierre`
  entre los `CierrePeriodo` con `activo=True`, líneas 25-33) y si la fecha
  del asiento es igual o anterior, lo rechaza con `ValidationError`. Como
  `registrar_asiento` es el único punto de creación de asientos encontrado,
  el cierre sí bloquea en la práctica de todos los flujos que se
  verificaron en esta sesión.
- **Reapertura**: `reabrir_periodo` (`contabilidad/services.py:56-70`) exige
  motivo obligatorio y dentro de la vista `cierres`
  (`contabilidad/views.py:51-91`) está protegida con `@rol_requerido(GERENTE)`
  (línea 51). Queda auditado vía `AuditLog` porque `contabilidad.cuentacontable`
  y otros están en `AUDITED`, pero `CierrePeriodo` **no está en la lista
  `AUDITED`** de `core/signals.py:47-63` — su creación/reapertura no genera
  fila de `AuditLog` por señal automática. `[HECHO]`: es una ausencia
  verificada, no una inferencia.

---

## 0.B — Mapa completo del sistema

### Modelos por app (campos relevantes, relaciones, `on_delete`, constraints/índices)

#### `core`

| Modelo | Cita | Campos | FKs (`on_delete`) | Meta |
|---|---|---|---|---|
| `Empresa` | `core/models.py:6` | `nombre`, `identificacion`, `regimen` (choices RTS/TRAD), `regimen_vigente_desde`, `moneda`, `factor_rts`, `creado_en` | — | `verbose_name_plural="empresas"` |
| `Sucursal` | `core/models.py:44` | `nombre`, `activa` | `empresa→Empresa` `PROTECT` | `verbose_name_plural="sucursales"` |
| `AuditLog` | `core/models.py:56` | `ip`, `fecha`, `tabla`, `objeto_id`, `accion`, `antes`/`despues` (JSONField) | `usuario→AUTH_USER_MODEL` `SET_NULL` (null/blank) | `ordering=["-fecha"]`; índices `audit_obj_idx(tabla,objeto_id)`, `audit_usuario_fecha_idx(usuario,fecha)`, `audit_fecha_idx(-fecha)` — `core/models.py:78,81,83` |
| `ChequeoIntegridad` | `core/models.py:90` | `fecha`, `revisados`, `descuadres`, `detalle` | — | `ordering=["-fecha"]` |
| `ChatMensaje` | `core/models.py:124` | `pregunta`, `respuesta`, `error`, `tokens_entrada/salida`, `creado_en` | `usuario→AUTH_USER_MODEL` `CASCADE` | `ordering=["-creado_en"]` |

Sin `unique_together`, `ManyToManyField` ni `OneToOneField` en `core`.

#### `catalogo`

| Modelo | Cita | Campos | FKs (`on_delete`) | Meta |
|---|---|---|---|---|
| `Categoria` | `catalogo/models.py:7` | `nombre` (unique) | `padre→"self"` `PROTECT` (null, `related_name="hijas"`) | `ordering=["nombre"]` |
| `Impuesto` | `catalogo/models.py:28` | `nombre`, `tarifa`, `vigente_desde/hasta` | — | — |
| `Producto` | `catalogo/models.py:44` | `sku` (unique), `nombre`, `categoria_original`, `codigo_barras` (indexado), `presentacion`, `descripcion`, `mascota` (indexado), `imagen`, `costo_promedio/precio_venta/stock_actual/stock_minimo`, `activo`, `creado_en/actualizado_en` | `empresa→Empresa` `PROTECT`; `categoria→Categoria` `PROTECT` (null); `impuesto→Impuesto` `PROTECT` (null) | `ordering=["nombre"]`; `CheckConstraint(precio_venta__gte=0)`, `CheckConstraint(stock_actual__gte=0)` — `catalogo/models.py:74-79`. `save()` auto-asigna `codigo_barras` desde `sku` al crear (`catalogo/models.py:84-97`) |
| `CambioPrecio` | `catalogo/models.py:126` | `valor_anterior/nuevo`, `costo_al_momento`, `motivo`, `fecha` | `producto→Producto` `PROTECT`; `usuario→AUTH_USER_MODEL` `SET_NULL` | `ordering=["-fecha","-id"]` |

#### `inventario`

| Modelo | Cita | Campos | FKs (`on_delete`) | Meta |
|---|---|---|---|---|
| `Bodega` | `inventario/models.py:8` | `nombre`, `principal` | `sucursal→Sucursal` `PROTECT` | `UniqueConstraint(sucursal, condition=Q(principal=True))` — una sola bodega principal por sucursal, `inventario/models.py:31-36`. Método `principal_de(sucursal)` (`:42-54`) |
| `MovimientoInventario` (kardex, inmutable por diseño) | `inventario/models.py:57` | `tipo` (INI/COM/VEN/REG/DEV/AJU/TRA), `cantidad`, `costo_unitario`, `costo_promedio_resultante`, `stock_resultante`, `referencia`, `motivo`, `fecha` | `producto→Producto` `PROTECT`; `bodega→Bodega` `PROTECT` (`related_name="kardex"`/`"movimientos"`) | `ordering=["-fecha","-id"]`; índices `kardex_prod_fecha_idx`, `kardex_fecha_idx`; `CheckConstraint(~Q(cantidad=0))`, `CheckConstraint(stock_resultante__gte=0)` |

#### `caja`

| Modelo | Cita | Campos | FKs (`on_delete`) | Meta |
|---|---|---|---|---|
| `SesionCaja` | `caja/models.py:7` | `estado` (ABI/CER), `monto_apertura`, `abierta_en`, `monto_esperado/contado/diferencia` (null hasta cierre), `cerrada_en` | `sucursal→Sucursal` `PROTECT`; `usuario→AUTH_USER_MODEL` `PROTECT` | `ordering=["-abierta_en"]`, sin constraints |
| `MovimientoCaja` | `caja/models.py:34` | `tipo` (APE/VEN/ING/EGR/ANU), `monto`, `descripcion`, `referencia`, `fecha` | `sesion→SesionCaja` `PROTECT`; `usuario→AUTH_USER_MODEL` `SET_NULL` | `ordering=["-fecha","-id"]`; `CheckConstraint(~Q(monto=0))` |

#### `ventas`

| Modelo | Cita | Campos | FKs (`on_delete`) | Meta |
|---|---|---|---|---|
| `Cliente` | `ventas/models.py:9` | `nombre`, `identificacion`, `limite_credito`, `saldo` (denormalizado), `activo` | `empresa→Empresa` `PROTECT` | `ordering=["nombre"]` |
| `Consecutivo` | `ventas/models.py:38` | `tipo` (default "FV"), `siguiente` | `empresa→Empresa` `PROTECT` | `UniqueConstraint(empresa, tipo)` |
| `FacturaVenta` | `ventas/models.py:61` | `numero` (unique), `estado`, `medio_pago`, `subtotal/descuento/impuesto/total`, `motivo_anulacion`, `anulada_en` | `empresa` `PROTECT`; `sucursal` `PROTECT`; `sesion_caja→SesionCaja` `PROTECT`; `cliente→Cliente` `PROTECT` (null); `usuario` `SET_NULL` (null); `anulada_por` `SET_NULL` (null) | `ordering=["-id"]`; índices `fv_creado_en_idx`, `fv_emp_est_fecha_idx` |
| `LineaVenta` | `ventas/models.py:131` | `cantidad`, `precio_unitario`, `descuento_pct/monto`, `es_regalia`, `costo_unitario`, `total` | `factura→FacturaVenta` `CASCADE`; `producto→Producto` `PROTECT` | `CheckConstraint(cantidad__gt=0)` |
| `DocumentoCxC` | `ventas/models.py:156` | `monto_original`, `saldo`, `estado` | `cliente→Cliente` `PROTECT`; `factura→FacturaVenta` **OneToOne** `PROTECT` | `ordering=["-id"]` |
| `DevolucionVenta` | `ventas/models.py:181` | `numero` (unique), `motivo`, `total` | `factura→FacturaVenta` `PROTECT`; `usuario` `SET_NULL` | `ordering=["-id"]` |
| `LineaDevolucion` | `ventas/models.py:204` | `cantidad`, `monto` | `devolucion→DevolucionVenta` `CASCADE`; `linea_venta→LineaVenta` `PROTECT` | `CheckConstraint(cantidad__gt=0)` |
| `Abono` | `ventas/models.py:221` | `monto`, `medio`, `referencia`, `fecha` | `documento→DocumentoCxC` `PROTECT`; `usuario` `SET_NULL` | `ordering=["-fecha","-id"]`; `CheckConstraint(monto__gt=0)` |

`Consecutivo.tomar(empresa, tipo)` (`ventas/models.py:51-58`): `transaction.atomic()` +
`select_for_update().get_or_create(...)` sobre `(empresa,tipo)`, incrementa
`siguiente`, retorna `f"{tipo}-{numero:08d}"`.

#### `contabilidad`

| Modelo | Cita | Campos | FKs (`on_delete`) | Meta |
|---|---|---|---|---|
| `CuentaContable` | `contabilidad/models.py:7` | `codigo`, `nombre`, `naturaleza`, `movimiento` (bool) | `empresa` `PROTECT`; `padre→"self"` `PROTECT` (null) | `UniqueConstraint(empresa, codigo)`; `ordering=["codigo"]` |
| `Asiento` | `contabilidad/models.py:37` | `numero` (unique), `fecha`, `descripcion`, `origen`, `referencia`; propiedad `cuadra` (solo lectura, `:77-79`) | `empresa` `PROTECT`; `usuario` `SET_NULL` | `ordering=["-id"]`; índices `asiento_fecha_idx`, `asiento_emp_fecha_idx` |
| `CierrePeriodo` | `contabilidad/models.py:82` | `fecha_cierre`, `nota`, `activo`, `reabierto_en`, `motivo_reapertura` | `empresa` `PROTECT`; `cerrado_por` `SET_NULL`; `reabierto_por` `SET_NULL` | `ordering=["-fecha_cierre","-id"]` |
| `LineaAsiento` | `contabilidad/models.py:119` | `debe`, `haber`, `detalle` | `asiento→Asiento` `CASCADE`; `cuenta→CuentaContable` `PROTECT` | `CheckConstraint`: `(debe>0 ∧ haber=0) ∨ (haber>0 ∧ debe=0)` |

#### `compras`

| Modelo | Cita | Campos | FKs (`on_delete`) | Meta |
|---|---|---|---|---|
| `Proveedor` | `compras/models.py:8` | `nombre`, `identificacion`, `telefono`, `email`, `notas`, `saldo` (CxP denormalizado), `activo` | `empresa` `PROTECT` | `ordering=["nombre"]` |
| `Compra` | `compras/models.py:28` | `numero` (unique), `factura_proveedor`, `estado` (BOR/REC/ANU), `forma_pago` (CON/CRE), `total`, `motivo_anulacion`, `anulada_en` | `empresa` `PROTECT`; `sucursal` `PROTECT`; `proveedor→Proveedor` `PROTECT`; `usuario` `SET_NULL`; `anulada_por` `SET_NULL` | `ordering=["-id"]`; índices `compra_recibida_idx`, `compra_emp_est_rec_idx` |
| `LineaCompra` | `compras/models.py:72` | `cantidad`, `costo_unitario`, `total` | `compra→Compra` `CASCADE`; `producto→Producto` `PROTECT` | `CheckConstraint(cantidad__gt=0)` |

### Mapa URL → View → Permiso → Template

`config/urls.py` monta: `""→core`, `"pos/"→ventas`, `"caja/"→caja`,
`"compras/"→compras`, `"inventario/"→inventario`, `"precios/"→catalogo`,
`"contabilidad/"→contabilidad`, `"admin/"→admin` de Django.

El control de acceso NO usa decoradores estándar de Django
(`login_required`/`permission_required` — 0 coincidencias en el repo). Usa
un esquema propio: `core/roles.py:rol_requerido(*roles)` (líneas 57-74), que
envuelve `@staff_member_required` (línea 63) y exige pertenencia a uno de
los grupos `Gerente`/`Cajero`/`Contador` (`en_roles`, líneas 40-44).

| App | Ruta | View | Control de acceso | Template / respuesta |
|---|---|---|---|---|
| core | `""` | `dashboard` — `core/views.py:38` | `@staff_member_required` — `core/views.py:37` (**sin** `@rol_requerido`, cualquier staff entra) | `core/dashboard.html` |
| core | `"actividad/"` | `actividad` — `:53` | `@rol_requerido(GERENTE)` — `:52` | `core/actividad.html` |
| core | `"reportes/"` | `reportes` — `:105` | `@rol_requerido(GERENTE)` — `:104` | `core/reportes.html` |
| core | `"reportes/mas-vendidos/"` | `reporte_mas_vendidos` — `:111` | `@rol_requerido(GERENTE)` — `:110` | `core/reporte_mas_vendidos.html` |
| core | `"reportes/stock/"` | `reporte_stock` — `:123` | `@rol_requerido(GERENTE)` — `:122` | `core/reporte_stock.html` |
| core | `"reportes/inventario/"` | `reporte_inventario` — `:134` | `@rol_requerido(GERENTE)` — `:133` | `core/reporte_inventario.html` |
| core | `"api/chat/"` | `chat_claude` — `:265` | `@staff_member_required` + `@require_http_methods(["POST"])` — `:263-264` (**sin** `@rol_requerido`; el filtro por rol ocurre *dentro*, en `core/chat_tools.py:herramientas_para`, líneas 123-129 y 141-147) | `JsonResponse` |
| catalogo | `""` | `precios` — `:21` | `@rol_requerido(GERENTE)` — `:20` | `catalogo/precios.html` |
| catalogo | `"<int:pk>/"` | `precio_producto` — `:46` | `@rol_requerido(GERENTE)` — `:45` | `catalogo/precio_producto.html` |
| inventario | `"ajuste/"` | `ajuste_inventario` — `:25` | `@rol_requerido(GERENTE)` — `:24` | `inventario/ajuste.html` |
| inventario | `"etiquetas/"` | `etiquetas` — `:55` | `@rol_requerido(CAJERO, GERENTE)` — `:54` | `inventario/etiquetas.html` |
| caja | `"abrir/"` | `abrir` — `:12` | `@rol_requerido(CAJERO, GERENTE)` — `:11` | `caja/abrir.html` |
| caja | `"cerrar/"` | `cerrar` — `:32` | `@rol_requerido(CAJERO, GERENTE)` — `:31` | `caja/cerrar.html` |
| ventas | `""` (POS) | `pos` — `:30` | `@rol_requerido(CAJERO, GERENTE)` — `:29` | `ventas/pos.html` |
| ventas | `"vender/"` | `vender` — `:73` | `@rol_requerido(CAJERO, GERENTE)` + `@require_POST` — `:71-72` | `JsonResponse` |
| ventas | `"tiquete/<id>/"` | `tiquete` — `:103` | `@rol_requerido(CAJERO, GERENTE)` — `:102` | `ventas/tiquete.html` |
| ventas | `"factura/<id>/"` | `factura` — `:113` | `@rol_requerido(CAJERO, GERENTE)` — `:112` | `ventas/factura.html` |
| ventas | `"factura/<id>/enviar/"` | `factura_enviar` — `:127` | `@rol_requerido(CAJERO, GERENTE)` + `@require_POST` — `:125-126` | `ventas/factura.html` (200/400/502 según resultado) |
| ventas | `"<id>/anular/"` | `anular` — `:174` | `@rol_requerido(GERENTE)` + `@require_POST` — `:172-173` | redirect `core:actividad` |
| ventas | `"<id>/devolver/"` | `devolver` — `:188` | `@rol_requerido(GERENTE)` — `:187` | `ventas/devolver.html` |
| ventas | `"cliente/<id>/estado-cuenta/"` | `estado_cuenta` — `:230` | `@rol_requerido(CAJERO, GERENTE)` — `:229` | `ventas/estado_cuenta.html` |
| ventas | `"cxc/<id>/abonar/"` | `abonar` — `:245` | `@rol_requerido(CAJERO, GERENTE)` + `@require_POST` — `:243-244` | redirect `ventas:estado_cuenta` |
| compras | `""` | `nueva` — `:104` | `@rol_requerido(GERENTE)` — `:103` | `compras/nueva.html` |
| compras | `"registrar/"` | `registrar` — `:141` | `@rol_requerido(GERENTE)` + `@require_POST` — `:139-140` | `JsonResponse` |
| compras | `"producto-nuevo/"` | `producto_nuevo` — `:202` | `@rol_requerido(GERENTE)` + `@require_POST` — `:200-201` | `JsonResponse` |
| compras | `"<id>/anular/"` | `anular` — `:189` | `@rol_requerido(GERENTE)` + `@require_POST` — `:187-188` | redirect `core:actividad` |
| contabilidad | `"libro-diario/"` | `libro_diario` — `:19` | `@rol_requerido(GERENTE, CONTADOR)` — `:18` | `contabilidad/libro_diario.html` |
| contabilidad | `"balance/"` | `balance_comprobacion` — `:30` | `@rol_requerido(GERENTE, CONTADOR)` — `:29` | `contabilidad/balance.html` |
| contabilidad | `"cierres/"` | `cierres` — `:52` | `@rol_requerido(GERENTE)` — `:51` | `contabilidad/cierres.html` (GET); redirect propio (POST) |
| contabilidad | `"estado-resultados/"` | `estado_resultados` — `:102` | `@rol_requerido(GERENTE, CONTADOR)` — `:101` | `contabilidad/estado_resultados.html` |
| contabilidad | `"iva-trimestral/"` | `iva_trimestral` — `:162` | `@rol_requerido(GERENTE, CONTADOR)` — `:161` | `contabilidad/iva_trimestral.html` |

**Únicas vistas sin `@rol_requerido`** (solo `@staff_member_required`, es
decir accesibles a cualquier usuario `is_staff` sin distinguir Gerente/
Cajero/Contador): `core:dashboard` y `core:chat_claude`. Todas las demás
rutas mapeadas (31 en total) tienen `@rol_requerido(...)` explícito.

**No cubierto en esta sesión**: `/admin/` de Django expone sus propias
vistas por modelo registrado (con su propio sistema de permisos, no
`rol_requerido`), protegidas en conjunto por `core.middleware.AdminSoloGerente`
(solo Gerente puede entrar a `/admin/`, salvo login/logout —
`core/middleware.py:68-84`). No se enumeró aquí qué `ModelAdmin` permiten
qué acciones exactas; se citaron los que aparecieron durante el mapeo por
app (`ventas/admin.py`, `contabilidad/admin.py`, `compras/admin.py`,
`inventario/admin.py`, `caja/admin.py` — ver notas en cada sub-sección de
modelos arriba). `core/admin.py` y `catalogo/admin.py` no se leyeron.

### Forms

| App | Archivo | Clases | Validación custom |
|---|---|---|---|
| inventario | `inventario/forms.py` | `AjusteInventarioForm` (`:8`) | `__init__(empresa=...)` filtra querysets por empresa (`:41-56`); `clean_cantidad` rechaza 0 (`:58-62`) |
| caja | `caja/forms.py` | `AbrirCajaForm` (`:6`), `CerrarCajaForm` (`:14`) | Sin `clean_*` (verificado por grep, sin coincidencias) |
| core, catalogo, ventas, contabilidad, compras | — | `[NO ENCONTRADO]` — ninguna de estas 5 apps tiene `forms.py` | Validación inline en las views (ver `compras/views.py:_validar_foto`, `:61-100`, y validaciones ad-hoc en `registrar`/`producto_nuevo`) |

### APIs

No hay Django REST Framework (no está en `requirements.txt` ni en
`INSTALLED_APPS`). Los endpoints "API" son vistas Django normales que
devuelven `JsonResponse` para consumo por `fetch`/AJAX desde el propio
frontend del ERP: `compras/views.py` (`registrar`, `producto_nuevo`),
`core/views.py` (`chat_claude`, entre otros usos de `JsonResponse` listados
en el mapeo original), `ventas/views.py` (`vender`). Autenticación: la
misma sesión de Django (cookie), protegida por `rol_requerido` salvo
`chat_claude` (solo `staff_member_required`, filtrado interno por rol).

### Middleware de seguridad de `core` (qué hace exactamente)

Orden en `MIDDLEWARE` (`config/settings.py:96-107`):
`SecurityMiddleware` → `SessionMiddleware` → `CommonMiddleware` →
`CsrfViewMiddleware` → `AuthenticationMiddleware` →
`core.middleware.CurrentUserMiddleware` → `core.middleware.AdminSoloGerente`
→ `core.seguridad.CabecerasDeSeguridad` → `MessageMiddleware` →
`XFrameOptionsMiddleware` (+ `axes.middleware.AxesMiddleware` al final, si
axes está activo).

- **`CurrentUserMiddleware`** (`core/middleware.py:53-65`): guarda
  usuario/IP de la petición en `threading.local()` para que las señales de
  auditoría los lean sin acoplar los modelos al `request`. `ip_de_la_peticion`
  (líneas 19-50) solo confía en `X-Forwarded-For` si `REMOTE_ADDR` está en
  `PROXIES_CONFIABLES` (vacío por defecto); si no, usa `REMOTE_ADDR` directo
  (no falsificable por el cliente).
- **`AdminSoloGerente`** (`core/middleware.py:68-84`): redirige a
  `core:dashboard` cualquier acceso a `/admin/*` (excepto `/admin/login`,
  `/admin/logout`) de un usuario autenticado que no sea Gerente
  (`core.roles.es_gerente`).
- **`CabecerasDeSeguridad`** (`core/seguridad.py:67-85`): agrega
  `Permissions-Policy` (bloquea cámara/micrófono/geolocalización/pago/etc.,
  líneas 49-53) y `Content-Security-Policy` en dos velocidades: un bloque
  siempre en modo bloqueo (`frame-ancestors 'none'; object-src 'none';
  base-uri 'self'; form-action 'self'`, línea 56) y el resto
  (`default-src`/`script-src`/`style-src`) en modo **solo reporte**
  (`Content-Security-Policy-Report-Only`) salvo que `DJANGO_CSP_ESTRICTA=1`
  (`settings.CSP_ESTRICTA`). El propio módulo documenta por qué (59 `onclick=`
  inline y 9 `<script>` en plantillas romperían el POS si se bloqueara ya,
  comentario líneas 7-42).

### Signals

Solo `core/signals.py` (185 líneas) en todo el proyecto — descrito en la
pregunta 0.A.3. `conectar()` se llama desde `CoreConfig.ready()` (no
verificado el `apps.py` exacto en esta sesión, pero referenciado por el
propio docstring de `signals.py:163-170`) y conecta receptores por `sender`
explícito (evita que cada `save()` del proyecto entero pase por el
auditor — optimización documentada como corrección de un hallazgo previo
BE-01/PERF-02).

### Management commands (quién puede ejecutarlos y qué validaciones saltan)

Todos son comandos de `manage.py` — se ejecutan desde una terminal con
acceso al servidor/entorno, **no** desde la interfaz web; no pasan por
`rol_requerido` ni por ningún control de Django porque no son vistas. Quien
tiene acceso a la shell del servidor (o al `.bat` de arranque) puede
correrlos sin autenticación de aplicación — es una superficie que la Fase 1
debe valorar (fraude interno: ¿quién tiene esas credenciales de sistema?).

| App | Comando | Qué hace | Validación previa propia del comando |
|---|---|---|---|
| core | `asignar_rol.py` (99 líneas) | Asigna/crea usuario con rol Gerente/Cajero/Contador; sincroniza permisos del grupo Gerente | Valida rol contra `choices`; exige `--crear`+`--password` si el usuario no existe |
| core | `reconciliar.py` (179 líneas) | Solo lectura: verifica que `stock_actual`, CxC, saldo cliente/proveedor cuadren contra kardex/libros; guarda en `ChequeoIntegridad` salvo `--sin-guardar` | Sin control de permisos de aplicación (es un comando de servidor) |
| core | `respaldar.py` (227 líneas) | Zip de BD (SQLite `connection.backup`/`pg_dump`) + `media/`; rota respaldos (conserva 30 por defecto) | Valida motor de BD soportado, existencia de BD, captura errores de `pg_dump`, advierte si el destino está en OneDrive/Dropbox |
| core | `restaurar.py` (195 líneas) | Restaura BD+`media/` desde zip; guarda copia previa | Exige `--confirmar` explícito (si no, solo simula); valida motor, integridad del zip |
| catalogo | `asignar_codigos_barras.py` (41 líneas) | Rellena `codigo_barras` vacío desde `sku`, desambigua colisiones; `@transaction.atomic` | Sin argumentos ni validación de permisos |
| catalogo | `exportar_catalogo_web.py` (259 líneas) | Exporta `productos.json`/`categorias.json` + imágenes hacia `allpetcr-web`, **excluye deliberadamente costo/margen/stock exacto**; por defecto solo activos con precio>0 y stock>0 | Valida que exista `Empresa` y carpeta destino |
| catalogo | `importar_imagenes.py` (147 líneas) | Extrae imágenes embebidas de un `.xlsx` (XML de `drawings`) y las asigna por fila/SKU; `@transaction.atomic` | Valida que el Excel abra como zip y que la hoja `--hoja` exista |
| catalogo | `importar_inventario.py` (122 líneas) | Carga inicial: crea `Empresa`/`Sucursal`/`Bodega` si faltan, crea productos, ingresa `MovimientoInventario` tipo `CARGA_INICIAL` vía `inventario.services.registrar_movimiento`; idempotente; `@transaction.atomic` | Valida apertura del archivo y hoja `"Inventario Real"` |
| catalogo | `sincronizar_inventario.py` (453 líneas) | Sincroniza productos/categorías/precios/stock con Excel vigente; delega precio a `catalogo.services.cambiar_precio` y stock a `inventario.services.registrar_movimiento`; soporta `--dry-run` (rollback real vía `transaction.set_rollback(True)`) | Valida `Empresa`, encabezados exactos de columnas (aborta si no coinciden), existencia del usuario pasado por `--usuario` |
| compras | `registrar_compra_inicial.py` (103 líneas) | Crea una `Compra` técnica (estado RECIBIDA) con el valor de la carga inicial, para reportes fiscales (RTS/D-105); **no mueve inventario ni genera asiento** (decisión explícita en el código) | Valida `Empresa`+sucursal, idempotencia por `numero`, formato de fecha, `monto>0` |

`ventas`, `inventario`, `caja`, `contabilidad` **no tienen** carpeta
`management/commands/`.

### `settings.py` (302 líneas) — secciones

- Interruptor único `PRODUCCION = DJANGO_PRODUCTION==1` (líneas 13-17);
  `SECRET_KEY` con fallback de desarrollo que **revienta** (`RuntimeError`)
  si se usa ese fallback en producción (líneas 19-27); `DEBUG` forzado
  `False` en producción (línea 31); `ALLOWED_HOSTS` desde env (línea 33).
- Bloque `if PRODUCCION` (líneas 36-51): `SECURE_SSL_REDIRECT`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_*` (1 año +
  subdominios + preload), `SECURE_CONTENT_TYPE_NOSNIFF`,
  `SESSION_COOKIE_HTTPONLY`, `X_FRAME_OPTIONS="DENY"`,
  `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS` desde env.
- `PROXIES_CONFIABLES` (líneas 53-60): whitelist vacía por defecto (ver
  0.A.4/middleware).
- `SESSION_COOKIE_AGE = 12h` (configurable), `SESSION_SAVE_EVERY_REQUEST=True`,
  `SESSION_COOKIE_SAMESITE="Lax"` (líneas 62-71) — comentario explícito: 12h
  para que cada turno de cajero se autentique de nuevo.
- `CSP_ESTRICTA` flag (línea 77).
- `INSTALLED_APPS` (7 apps propias, línea 79-94), `MIDDLEWARE` (línea 96-107,
  ver arriba), `ROOT_URLCONF="config.urls"`.
- `TEMPLATES`: `DIRS=[BASE_DIR/"templates"]`, `APP_DIRS=True`, builtin
  `core.templatetags.formato` disponible en todas las plantillas sin
  `{% load %}` (líneas 111-128).
- `DATABASES`: Postgres si `POSTGRES_HOST` está definido, si no SQLite con
  `DJANGO_DB_PATH` configurable (líneas 132-151).
- `CACHES`: `LocMemCache` (120s TIMEOUT), forzado a `DummyCache` durante
  `manage.py test` (líneas 169-184) — con justificación extensa en
  comentario de por qué NO Redis ni caché en BD (líneas 153-168).
- `AUTH_PASSWORD_VALIDATORS`: los 4 validadores estándar de Django
  (similitud con usuario, longitud mínima, contraseñas comunes, no
  numérica) — líneas 186-191.
- Locale `es`, `TIME_ZONE="America/Costa_Rica"`, `USE_TZ=True`.
- `LOGIN_URL="/admin/login/"` (línea 207) — no hay login propio del ERP,
  usa el login de Django admin.
- **django-axes** (líneas 209-255): activo por defecto (`DJANGO_ENABLE_AXES`
  != "0"), obligatorio en producción (`RuntimeError` si falta el paquete o
  si se intenta desactivar por env en producción), desactivado durante
  `manage.py test`. `AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_TIME=1` hora,
  bloqueo por `["username","ip_address"]`, reset al éxito.
- `LOGGING`: `RotatingFileHandler` (5MB×10 archivos) en producción,
  `StreamHandler` en local (líneas 257-283).
- Email: backend SMTP si `EMAIL_HOST_PASSWORD` está definido, si no backend
  de consola (líneas 285-303); `EMAIL_TIMEOUT=20s`.

### Dependencias (`requirements.txt`)

`Django>=5.2,<5.3`, `openpyxl>=3.1`, `python-barcode>=0.15`,
`psycopg2-binary>=2.9`, `gunicorn>=21.0`, `django-axes>=6.0`,
`anthropic>=0.120` (usado por `core/views.py` para el chat de ayuda). No hay
`pyproject.toml` ni `Pipfile`. `[NO VERIFICADO]`: CVEs específicos de estas
versiones — recomendado correr `pip-audit` (regla del prompt maestro:
sin poder verificar CVEs concretos, se marca así en vez de inventarlos).

### Migraciones

31 archivos totales: core 8, catalogo 4, inventario 5, caja 1, ventas 7,
contabilidad 3, compras 3. Solo 2 contienen `RunPython`/`RunSQL`:
`inventario/migrations/0005_bodega_principal_and_more.py` (marca/desmarca
bodega principal) y `core/migrations/0003_roles.py` (crea/borra grupos de
rol) — ninguna de las dos borra datos de negocio (`[NO VERIFICADO]` a fondo
línea por línea; se verificó por grep de `RunPython`/`RunSQL`, no por
lectura completa del contenido de cada migración).

### Tests

`def test_` detectadas por grep: **245**, en 19 archivos (core 10, ventas 3,
contabilidad 2, catalogo 1, inventario 1, compras 1; **`caja` no tiene
archivo de tests**). `CLAUDE.md` declara "235 pruebas"; `config/settings.py:224`
(comentario) dice "174 pruebas"; `requirements.txt:1` (comentario) dice
"150 pruebas". **Discrepancia real entre cuatro fuentes** (245 grep / 235
CLAUDE.md / 174 comentario en settings.py / 150 comentario en requirements.txt)
— no se resuelve en esta sesión (no se corrió el test runner completo para
obtener el número oficial de `OK`/tests ejecutados, para no salirse del
alcance de solo-lectura de esta fase). `[NO VERIFICADO]` cuál de las cuatro
cifras es la vigente hoy.

### Archivos sensibles y secretos

- `.env` y `.env.example` existen en la raíz; `.env` está en `.gitignore`
  (no trackeado). `git log --all --oneline -- .env` no devuelve ningún
  commit — `.env` real **nunca se subió al historial** `[HECHO]`.
- Búsqueda en el historial completo de git de archivos añadidos con nombre
  `.env`, `.p12`, `.pem`, `.key` o que contengan "secret": sin resultados.
- Grep de `SECRET_KEY|PASSWORD|.p12` en código fuente: todas las
  coincidencias son lecturas de `os.environ` (`config/settings.py`),
  referencias `${...}` en `docker-compose.yml`, o menciones textuales en
  `.env.example`/`PRODUCCION.txt`/`aplicar_mejoras.bat` — no se encontró
  ningún valor hardcodeado. No hay `.p12`/`.pem`/`.key` en el repo.
- **Límite de esta verificación** `[NO VERIFICADO]`: no se revisó el
  historial completo de commits en busca de secretos que hayan sido
  añadidos y luego eliminados en un commit posterior (`.env` nunca se
  añadió, pero un valor pegado directo en un `.py` y luego revertido no
  necesariamente aparecería en el `git log --name-only` filtrado que se
  corrió). Recomendado para Fase 1: `gitleaks`/`trufflehog` sobre todo el
  historial.

---

## 0.C — Procesos críticos, paso a paso

### Venta al contado

1. `ventas/views.py:pos` (línea 30) exige sesión de caja abierta
   (`caja.services.sesion_abierta_de`); si no hay, redirige a `caja:abrir`.
2. El navegador llama `POST /pos/vender/` → `ventas/views.py:vender`
   (líneas 73-99): parsea JSON, resuelve cliente opcional, llama
   `ventas.services.registrar_venta(...)` con `permitir_bajo_costo=es_gerente(request.user)`
   (línea 88).
3. `ventas/services.py:registrar_venta` (líneas 37-154, `@transaction.atomic`):
   - Bloquea la sesión de caja (`select_for_update`, línea 48) y valida que
     esté abierta.
   - Toma bodega principal de la sucursal (`Bodega.principal_de`, línea 62).
   - Toma consecutivo `FV` (`Consecutivo.tomar`, línea 66) y crea la
     `FacturaVenta`.
   - Ordena las líneas por `producto_id` (línea 77) para evitar deadlocks
     entre cajas concurrentes.
   - Por cada línea: valida cantidad > 0, calcula descuento, **bloquea venta
     bajo costo salvo que sea gerente** (líneas 104-113), calcula desglose
     fiscal (`_desglose_fiscal`), mueve el kardex primero
     (`inventario.services.registrar_movimiento`, línea 118 — si no hay
     stock, la venta ENTERA revienta) y crea la `LineaVenta`.
   - Guarda totales de la factura.
   - Si `medio_pago==EFECTIVO` y total>0: `caja.services.registrar_movimiento_caja`
     (línea 139).
   - Asienta contablemente (`ventas.contabilizar.asentar_venta`, línea 153) —
     dos asientos: venta (caja/bancos vs ventas+IVA) y costo de venta
     (costo de ventas vs inventario), vía `contabilidad.services.registrar_asiento`
     (que a su vez valida cuadre y período no cerrado).
4. Todo lo anterior ocurre en una sola transacción: si cualquier paso
   falla (sin stock, caja cerrada, período contable cerrado, asiento
   descuadrado), **nada** se confirma.
5. Respuesta JSON con número de factura y URL del tiquete
   (`ventas/views.py:94-99`); el navegador puede pedir
   `GET /pos/tiquete/<id>/` (`ventas/views.py:tiquete`, línea 103) o
   `GET /pos/factura/<id>/` (línea 113, versión imprimible/PDF con logo) o
   enviarla por correo (`factura_enviar`, línea 127).

### Venta a crédito (con `DocumentoCxC` y `Abono`)

1. Mismo flujo que el contado hasta el punto 3, pero `medio_pago=CREDITO`
   exige `cliente` (`ventas/services.py:55-56`).
2. En vez de mover caja, `ventas/services.py:146-148` llama
   `ventas.cxc.crear_cxc(factura=factura)`.
3. `ventas/cxc.py:crear_cxc` (líneas 32-43, `@transaction.atomic`): bloquea
   el `Cliente` (`select_for_update`), valida crédito
   (`validar_credito`, líneas 20-29: cliente debe tener `limite_credito>0` y
   el monto no debe superar `credito_disponible`), crea `DocumentoCxC` y
   sube `cliente.saldo`.
4. Cobro posterior: `POST /pos/cxc/<id>/abonar/` →
   `ventas/views.py:abonar` (línea 245) → `ventas.cxc.registrar_abono`
   (líneas 46-86, `@transaction.atomic`): bloquea el documento, valida
   estado PENDIENTE y que el monto no exceda el saldo, crea `Abono`, baja
   saldo del documento y del cliente; si el medio es efectivo y el usuario
   tiene caja abierta, mueve esa caja (línea 72-81); asienta el cobro
   (`contabilizar.asentar_abono`, línea 84-85: Debe caja/bancos, Haber CxC).

### Devolución (parcial, con la venta vigente)

1. `GET/POST /pos/<id>/devolver/` → `ventas/views.py:devolver` (línea 188,
   solo `GERENTE`). El formulario POST manda cantidades por línea
   (`cant_<linea.id>`).
2. `ventas/devoluciones.py:registrar_devolucion` (líneas 47-172,
   `@transaction.atomic`): valida que la factura siga `EMITIDA`, motivo
   obligatorio, por cada línea valida que la cantidad a devolver no exceda
   `cantidad_comprada - ya_devuelta` (líneas 82-89, contando devoluciones
   previas de esa misma línea vía `LineaDevolucion`), reintegra al kardex
   (`registrar_movimiento`, tipo `DEV`, línea 113-117).
3. Reparto del reembolso según medio de pago original (líneas 128-161):
   efectivo → sale de la **caja abierta de hoy** (no la de la venta
   original, que puede llevar días cerrada; exige tener caja abierta);
   crédito → reduce primero el saldo de la CxC, el excedente (si el cliente
   ya había abonado de más) se reembolsa en efectivo; tarjeta/SINPE → solo
   ajusta Bancos contablemente, no mueve caja física.
4. Asiento de reversa parcial (`contabilizar.asentar_devolucion`).

### Anulación de factura (reversa total, distinta de la devolución)

1. `POST /pos/<id>/anular/` → `ventas/views.py:anular` (línea 174, solo
   `GERENTE`, motivo obligatorio vía `request.POST`).
2. `ventas/services.py:anular_factura` (líneas 157-200,
   `@transaction.atomic`): bloquea la factura, exige que no esté ya anulada
   y motivo no vacío; reversa TODAS las líneas al kardex (`DEV`, costo
   `0`, líneas 168-174); si era efectivo, exige caja abierta y saca el
   dinero (`MovimientoCaja.Tipo.ANULACION`, monto negativo); si era
   crédito, `ventas.cxc.cancelar_cxc_por_anulacion` — **bloquea la
   anulación si la CxC ya tiene abonos** (líneas 97-101 de `cxc.py`: hay
   que gestionar el dinero cobrado aparte primero); marca la factura
   `ANULADA` con `motivo_anulacion`/`anulada_en`/`anulada_por`; asienta la
   reversa (`asentar_anulacion`).

### Apertura y cierre de caja

1. `GET/POST /caja/abrir/` → `caja/views.py:abrir` (línea 12): si ya hay
   sesión abierta del usuario, redirige al POS con aviso; si no,
   `caja.services.abrir_caja` (líneas 16-33, `@transaction.atomic`): valida
   monto ≥0, valida que no haya sesión abierta ya (doble chequeo dentro del
   servicio), crea `SesionCaja`, y si el monto de apertura es >0, registra
   `MovimientoCaja.Tipo.APERTURA` (con monto=0 no crea movimiento, porque
   violaría el `CheckConstraint` de monto distinto de cero).
2. `GET/POST /caja/cerrar/` → `caja/views.py:cerrar` (línea 32):
   `caja.services.cerrar_caja` (líneas 54-70, `@transaction.atomic`):
   bloquea la sesión, valida que siga abierta, calcula `monto_esperado`
   (suma de todos los `MovimientoCaja` de la sesión, línea 49-51), guarda
   `monto_contado` (dato del usuario) y `diferencia = contado - esperado`,
   marca `CERRADA`. La sesión queda inmutable — el servicio no tiene camino
   de post-cierre que reabra o edite montos.

### Compra y recepción

1. `GET /compras/` → `compras/views.py:nueva` (línea 104, solo `GERENTE`):
   lista TODOS los productos activos de la empresa **sin** filtrar por
   `productos_visibles` (que excluiría agotados) — decisión documentada
   explícitamente en el código (líneas 110-117) porque esta es la pantalla
   que hace que un producto agotado deje de estarlo, y está verificada por
   `core/test_arquitectura.py` según el comentario.
2. `POST /compras/registrar/` → `compras/views.py:registrar` (línea 141):
   parsea JSON, resuelve/crea proveedor, arma líneas, llama
   `compras.services.crear_compra` y luego, en el mismo request,
   `compras.services.recibir_compra` — es decir, en esta UI **crear y
   recibir ocurren en el mismo paso** (no hay estado `BORRADOR` visible en
   el flujo web normal; sí existe en el modelo y se usa desde el admin,
   según `compras/admin.py:accion_recibir`).
3. `compras/services.py:crear_compra` (líneas 26-51, `@transaction.atomic`):
   toma consecutivo `OC`, crea `Compra` en `BORRADOR`, crea `LineaCompra`
   por cada línea validando cantidad>0 y costo≥0.
4. `compras/services.py:recibir_compra` (líneas 54-93,
   `@transaction.atomic`): bloquea la compra, exige que siga en
   `BORRADOR`, por cada línea entra al kardex (`registrar_movimiento`, tipo
   `COM`, recalcula costo promedio), asienta (Debe Inventario, Haber
   Bancos o CxP según forma de pago), si es crédito sube el saldo del
   proveedor, marca `RECIBIDA`.
5. Alta rápida de producto nuevo desde esta misma pantalla:
   `POST /compras/producto-nuevo/` → `compras/views.py:producto_nuevo`
   (línea 202) — valida nombre y precio>0, genera SKU automático
   (`_generar_sku`, líneas 26-35), crea el `Producto`, y si viene foto en
   base64 la valida por **firma binaria real** (no por la extensión que
   declara el cliente: `_validar_foto`/`_extension_real`, líneas 61-100 —
   solo PNG/JPEG/WebP, tope 5MB) antes de guardarla en disco con nombre
   derivado del SKU (el cliente no controla el nombre de archivo).
6. Anulación: `POST /compras/<id>/anular/` → `compras/views.py:anular`
   (línea 189) → `compras.services.anular_compra` (líneas 96-146,
   `@transaction.atomic`): exige que la compra esté `RECIBIDA` y motivo;
   saca del kardex lo que había entrado (revienta con `ValidationError` si
   ya no hay stock suficiente — **no permite dejar el inventario negativo,
   ni siquiera para reversar una compra**); asiento inverso; si era
   crédito, baja saldo del proveedor; marca `ANULADA` (nunca se borra la
   compra).

### Ajuste de inventario

1. `GET/POST /inventario/ajuste/` → `inventario/views.py:ajuste_inventario`
   (línea 25, solo `GERENTE`) — comentario explícito en el código: "Único
   camino de ajuste manual: pasa por el servicio de dominio, exige motivo y
   queda auditado con usuario e IP" (líneas 26-27).
2. `AjusteInventarioForm` (`inventario/forms.py:8`) exige producto, bodega,
   cantidad (≠0, `clean_cantidad`), costo unitario opcional, motivo
   obligatorio (`Textarea`, máx 200).
3. Al validar, llama directamente `inventario.services.registrar_movimiento`
   con `tipo="AJU"` y una referencia autogenerada `AJ-<timestamp>`
   (`inventario/views.py:31-42`) — el mismo servicio único descrito en
   0.A.2, con el mismo bloqueo de fila y la misma prohibición de stock
   negativo.

### Cierre de periodo contable

1. `GET/POST /contabilidad/cierres/` → `contabilidad/views.py:cierres`
   (línea 52, solo `GERENTE`).
2. Acción `cerrar` (líneas 61-70): parsea `fecha_cierre` del POST,
   `contabilidad.services.cerrar_periodo` (líneas 42-53,
   `@transaction.atomic`) — rechaza si la nueva fecha no es posterior al
   cierre vigente (solo se puede cerrar "hacia adelante"), crea
   `CierrePeriodo`.
3. Acción `reabrir` (líneas 71-79): recupera el `CierrePeriodo` vía
   `documento_de_empresa` (acotado a la empresa del usuario, ver 0.A.4),
   `contabilidad.services.reabrir_periodo` (líneas 56-70) — exige motivo,
   bloquea la fila, marca `activo=False` con `reabierto_por`/`reabierto_en`/
   `motivo_reapertura`.
4. Efecto real del bloqueo: **no está en la vista ni en el modelo**, está
   en `contabilidad.services.registrar_asiento` (líneas 183-189, ver 0.A.5)
   — cualquier intento de crear un asiento con fecha ≤ la fecha de cierre
   vigente revienta con `ValidationError`, sin importar desde qué app se
   originó (venta, compra, cobro, anulación).

### Sincronización con `allpetcr-web`

Tres comandos independientes, ejecutados manualmente desde la terminal del
servidor (no hay disparador automático encontrado en esta sesión —
`[NO VERIFICADO]` si existe una tarea programada; `CLAUDE.md` sugiere que
hoy es manual):

1. **`sincronizar_inventario`** (`catalogo/management/commands/sincronizar_inventario.py`,
   453 líneas): lee el Excel vigente, valida encabezados exactos antes de
   tocar cualquier fila (aborta si no coinciden), y por cada producto
   crea/actualiza — el precio pasa por `catalogo.services.cambiar_precio`
   (que registra `CambioPrecio` y usa `select_for_update`) y el stock por
   `inventario.services.registrar_movimiento` (el mismo servicio único).
   Soporta `--dry-run` con rollback real (`transaction.set_rollback(True)`).
   Dirección del flujo: Excel → ERP (unidireccional; no se encontró ningún
   código que lea del sitio web hacia el ERP).
2. **`importar_imagenes`** (147 líneas): extrae imágenes embebidas del
   `.xlsx` (parseando el XML de `drawings` del propio archivo Office) y las
   asigna a productos por posición de fila/SKU.
3. **`exportar_catalogo_web`** (259 líneas): genera `productos.json`/
   `categorias.json` + copia imágenes hacia la carpeta del repo
   `allpetcr-web`. **Excluye deliberadamente** costo, margen y stock exacto
   del JSON exportado (verificado por el agente de exploración de
   `core`/`catalogo`, aunque no se leyó línea por línea el cuerpo completo
   del comando en esta sesión — `[NO VERIFICADO]` el detalle exacto de qué
   campos sí viajan, más allá de la constatación de que costo/margen/stock
   exacto no están). Por defecto solo publica productos activos con
   precio>0 y stock>0.

**No verificado en esta sesión** `[NO VERIFICADO]`: cómo se autentican
ambos sistemas entre sí (no aplica si el flujo es solo un command-line que
escribe archivos en un path local/compartido, pero no se confirmó si hay
alguna llamada de red entre ERP y `allpetcr-web`, o si todo pasa por
archivos JSON + imágenes copiadas a una carpeta que el sitio web lee
directamente). Tampoco se verificó qué pasa si `exportar_catalogo_web`
falla a la mitad (¿dry-run/atomicidad de la escritura de archivos?).

---

## Tabla de cobertura

| Componente | Estado | Nota |
|---|---|---|
| `core` — modelos, urls/views, management commands, middleware, roles, tenancy, signals | REVISADO | Lectura directa + agente de exploración |
| `core/admin.py` | NO REVISADO | No leído en esta sesión |
| `core/dashboard.py`, `core/reportes.py`, `core/chat_tools.py` | REVISADO (resumen) | Vía agente; no línea por línea completa |
| `catalogo` — modelos, urls/views, management commands | REVISADO | Lectura directa + agente |
| `catalogo/admin.py` | NO REVISADO | — |
| `catalogo/consultas.py`, `catalogo/services.py` | REVISADO | Vía agente, con citas |
| `inventario` — modelos, urls/views, forms, services | REVISADO | Lectura directa de `services.py`/`views.py`; resto vía agente |
| `inventario/admin.py` | PARCIAL | Solo lo reportado por el agente (sin add/change/delete) |
| `caja` — modelos, urls/views, forms, services | REVISADO | Lectura directa |
| `caja/admin.py` | PARCIAL | Solo lo reportado por el agente |
| `compras` — modelos, urls/views, services, management command | REVISADO | Lectura directa de `views.py`/`services.py`; modelos vía agente |
| `compras/admin.py` | PARCIAL | Solo el fragmento citado por el agente |
| `ventas` — modelos, urls/views, services, contabilizar, cxc, devoluciones | REVISADO | Lectura directa de todos los módulos de negocio |
| `ventas/admin.py` | PARCIAL | Solo lo reportado por el agente |
| `contabilidad` — modelos, urls/views (parcial), services, plan_cuentas | REVISADO | Lectura directa de `services.py`; `views.py` leído en la sección `cierres`, el resto (`libro_diario`, `balance_comprobacion`, `estado_resultados`, `iva_trimestral`) solo vía agente, no leído directamente |
| `contabilidad/admin.py` | PARCIAL | Solo lo reportado por el agente |
| `config/settings.py` | REVISADO | Lectura completa (302 líneas) |
| `config/urls.py` | REVISADO | Lectura completa |
| `requirements.txt` | REVISADO | Lectura completa |
| Migraciones (31 archivos) | PARCIAL | Grep de `RunPython`/`RunSQL`, no lectura línea por línea de cada una |
| Tests (19 archivos, 245 `def test_`) | PARCIAL | Conteo por grep; no se ejecutó el test runner ni se leyó el contenido de los tests |
| Secretos / historial de git | PARCIAL | `.env` confirmado fuera del historial; no se corrió una herramienta dedicada (gitleaks/trufflehog) sobre todo el historial |
| Facturación electrónica CR | REVISADO (resultado: no existe) | Grep dirigido + lectura de `Empresa.Regimen` |
| Templates (32 archivos .html) | NO REVISADO | Solo se contó cuántos hay y dónde viven; no se leyó contenido (corresponde a Fase 7, UX) |
| Integración con `allpetcr-web` (autenticación entre sistemas, atomicidad de la exportación) | PARCIAL | Ver notas al final de la sección "Sincronización con allpetcr-web" |
| Dependencias / CVEs | NO VERIFICADO | Se listaron versiones; no se corrió `pip-audit` |

**Cobertura global estimada**: **~75-80%** del código de aplicación
relevante para Fase 0 (7 apps: modelos, urls, views, forms, services,
management commands, middleware, settings). Quedan explícitamente
**NO REVISADOS**: los 7 archivos `admin.py` (solo vistos parcialmente vía
agente, no leídos directamente), el contenido completo de `contabilidad/views.py`
más allá de la sección `cierres`, el contenido de los 32 templates HTML, el
contenido línea por línea de las 31 migraciones y de los 19 archivos de
test, y cualquier verificación con herramientas externas (pip-audit,
gitleaks). Esta cifra es una estimación cualitativa `[INFERENCIA]`, no una
métrica medida (p. ej. % de líneas de código leídas), y se declara así para
cumplir la regla 5 del prompt maestro: ningún veredicto sin declarar
cobertura.
