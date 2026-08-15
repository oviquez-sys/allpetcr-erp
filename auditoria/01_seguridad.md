# Fase 1 — Seguridad

> Continúa `auditoria/00_mapa_sistema.md` (Fase 0). Etiquetas: `[HECHO]`
> verificado con cita `archivo:línea` · `[PROBLEMA]`/`[RIESGO]` hallazgo ·
> `[INFERENCIA]` deducción razonable sin prueba directa · `[NO VERIFICADO]`
> no se pudo comprobar con el método usado en esta sesión.
>
> **Contexto confirmado por el usuario, no re-evaluado en esta fase:**
> facturación electrónica **NO EXISTE** (Fase 0) y el régimen tributario real
> es **Régimen General** (confirmado con el RUT del contribuyente) — la FE es
> **obligatoria**, sin exención por RTS. Esta fase es de seguridad; la
> implicación fiscal de ese hecho se trata en Fase 4. Sí se deja constancia
> más abajo de un lugar del código (`contabilidad/views.py:iva_trimestral`)
> que sigue asumiendo RTS, porque apareció durante la revisión de esta fase.

---

## Threat model

**Activos** (qué hay que proteger, en orden de lo que más duele perder):
dinero en caja y en cuentas por cobrar · inventario físico y su costo
promedio · precios y márgenes (información competitiva) · datos de clientes
(nombre, cédula, teléfono, historial de crédito) · credenciales de las
cuentas Gerente/superusuario · datos fiscales (identificación, régimen,
factor RTS) · la integridad del propio libro contable (`Asiento`).

**Actores hostiles considerados:**

| Actor | Qué puede intentar | Superficie principal |
|---|---|---|
| Atacante externo | Fuerza bruta de login, IDOR vía URL, XSS/CSRF, explotar dependencias desactualizadas | `/admin/login/`, cualquier URL con `<id>`, formularios, `requirements.txt` |
| **Cajero deshonesto** | Descuentos no autorizados, anular ventas para quedarse el efectivo, devoluciones ficticias | POS (`/pos/vender/`), su propia sesión de caja |
| Supervisor (Gerente) deshonesto | Anular/devolver sin motivo real, ajustar inventario para tapar un faltante, borrar/alterar documentos desde `/admin/` | Todo lo que `@rol_requerido(GERENTE)` habilita + `/admin/` |
| Ex-empleado con credenciales vivas | Reusar sesión o contraseña no revocada | Login, sesiones concurrentes |
| Malware en la máquina del POS | Captura de sesión/teclado, acceso a terminal para correr `manage.py` con privilegios | El sistema operativo de la máquina donde corre el `.bat` (fuera del control de Django) |

**Superficies auditadas en esta sesión:** login (admin de Django, único punto
de entrada — `LOGIN_URL="/admin/login/"`, `config/settings.py:207`),
formularios (`inventario/forms.py`, `caja/forms.py`; el resto valida inline
en las views), endpoints JSON (`vender`, `registrar`, `producto_nuevo`,
`chat_claude`), URLs directas con `<id>` (grep exhaustivo, ver más abajo),
sesiones, dependencias (`requirements.txt`), los 10 management commands, la
integración con `allpetcr-web` (ya cubierta en Fase 0, no se repite aquí),
y el repositorio git (historial de secretos, ya cubierto en Fase 0).

**Sobre atacantes automatizados:** la única barrera de fuerza bruta real es
`django-axes` sobre el login (`AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_TIME=1`
hora, bloqueo por `username`+`ip_address` — `config/settings.py:252-255`).
Ningún endpoint autenticado (POS, compras, etc.) tiene límite de tasa propio,
**salvo `chat_claude`** (40/día + 6/minuto por usuario, `core/views.py:274-294`,
explícitamente corregido tras un hallazgo previo, SEG-07). Un atacante que ya
tiene una sesión válida (robada o de un empleado) puede automatizar acciones
dentro de su rol sin que nada en el código lo frene — la única defensa ahí es
la propia restricción de `rol_requerido`, no un límite de velocidad.

---

## Autenticación

- **Hashing de contraseñas:** el `PBKDF2` por defecto de Django (no
  sobreescrito en `config/settings.py` — no hay `PASSWORD_HASHERS` custom).
  `[HECHO]` por ausencia de configuración que lo cambie.
- **Política de contraseñas:** los 4 validadores estándar de Django
  (similitud con el usuario, longitud mínima 8, contra lista de comunes, no
  100% numérica) — `config/settings.py:186-191`. No hay requisito de
  mayúscula/símbolo/rotación periódica (Django no lo trae de fábrica y este
  proyecto no lo agrega).
- **Bloqueo por intentos fallidos / rate limiting del login:** `django-axes`
  activo por defecto y obligatorio en producción (`config/settings.py:209-255`,
  detallado en Fase 0).
- **Expiración de sesión:** `SESSION_COOKIE_AGE` = 12h configurable,
  `SESSION_SAVE_EVERY_REQUEST=True` (la ventana se renueva con cada acción,
  no se cuenta desde el login) — `config/settings.py:68-69`.
- **Invalidación de sesión al cambiar contraseña:** `[HECHO]` — comportamiento
  de framework, no de este código: Django valida en cada request que el hash
  de sesión (`get_session_auth_hash()`) coincida con la contraseña actual del
  usuario; si la contraseña cambió, las sesiones abiertas en otros
  dispositivos dejan de autenticar automáticamente. No requiere código propio,
  pero **si nadie sabe que hay que cambiar la contraseña de alguien que se
  fue, esa invalidación nunca se dispara** (ver SEC-004).
- **Sesiones concurrentes:** `[HECHO]` sin restricción — no hay
  `SESSION_ENGINE` especial ni lógica de "una sola sesión por usuario" en
  ningún archivo revisado. Un mismo usuario puede estar autenticado en varios
  dispositivos a la vez indefinidamente.
- **Recuperación de contraseña:** `[HECHO]` NO EXISTE — `config/urls.py` no
  incluye ninguna de las rutas `password_reset*` de Django, y no se encontró
  vista propia equivalente. Un usuario que olvida su contraseña depende de
  que un superusuario se la cambie manualmente.
- **2FA para roles administrativos:** `[HECHO]` NO EXISTE — sin paquete
  `django-otp`/similar en `requirements.txt`, sin campo ni vista relacionada.
  El Gerente y el superusuario (el "dueño") entran con usuario+contraseña
  solamente.
- **Login único:** todos los roles (Cajero, Contador, Gerente) inician
  sesión por el mismo formulario de admin de Django (`LOGIN_URL`), aunque
  `AdminSoloGerente` (`core/middleware.py:68-84`) los saque de `/admin/*`
  después si no son Gerente. El formulario de login en sí es público
  (necesario) y queda protegido únicamente por `axes`.

## Autorización

- **Verificación en cada view:** confirmado en Fase 0 — de las 31 rutas
  mapeadas, 29 tienen `@rol_requerido(...)` explícito; solo `core:dashboard`
  y `core:chat_claude` tienen únicamente `@staff_member_required` (cualquier
  staff, sin distinguir rol).
  - `core:dashboard` — **investigado en esta sesión, riesgo descartado**:
    aunque la vista calcula margen/utilidad/CxC para cualquier staff
    (`core/dashboard.py:_calcular_indicadores`), el template
    `templates/core/dashboard.html` envuelve TODOS los indicadores
    financieros y los accesos a Recibir/Reportes/Admin/Reversas dentro de
    `{% if es_gerente %}` (líneas 208-213, 226-252, 265-270, 274 en
    adelante) — un Cajero autenticado recibe HTML sin esas cifras. Verificado
    leyendo el template completo, no inferido. Queda como nota de diseño
    frágil (el dato SÍ viaja al contexto de render en el servidor aunque no
    se imprima), no como hallazgo activo.
  - `core:chat_claude` — **también investigado, con doble capa de control ya
    documentada en el propio código** (`core/chat_tools.py:1-17`,
    hallazgo SEG-01 de una auditoría previa): `herramientas_para()`
    (líneas 123-129) le oculta al modelo de IA las herramientas financieras
    si el usuario no es Gerente/Contador, y `ejecutar_herramienta()`
    (líneas 141-147) las bloquea de nuevo aunque alguien intente forzarlas.
    Es un control sólido, vale la pena preservarlo intacto en cualquier
    refactor futuro.
- **IDOR — grep exhaustivo de `get_object_or_404` en las 7 apps** (pedido
  explícito de esta sesión): solo **2 usos** en todo el repositorio fuera de
  `.venv`:
  1. `core/tenancy.py:56` — es la implementación INTERNA de
     `documento_de_empresa`, el mecanismo correcto; no es un bypass.
  2. `catalogo/admin.py:86` (dentro de `ProductoAdmin.entrada_view`, una URL
     custom de admin) — **este SÍ abre un `Producto` por `pk` sin pasar por
     `documento_de_empresa`** → hallazgo **SEC-003** (abajo).
  Ninguna vista de negocio en `ventas/views.py`, `compras/views.py`,
  `contabilidad/views.py`, `inventario/views.py`, `caja/views.py` usa
  `get_object_or_404` directo — todas las que abren un documento por ID
  pasan por `documento_de_empresa` (confirmado con las citas de Fase 0:
  `ventas/views.py:104,117,131,176,193,231,247`, `contabilidad/views.py:72`,
  `compras/views.py:191`). **Conclusión: el patrón de aislamiento por
  empresa se respeta en el 100% del código de aplicación revisado, con
  una única excepción en una vista de administración.**
- **Endpoints "API" (JsonResponse) vs. su equivalente web:** mismos
  decoradores `@rol_requerido` que las vistas HTML correspondientes
  (`vender`, `registrar`, `producto_nuevo` — ver tabla de Fase 0). No se
  encontró ningún endpoint JSON con permisos más laxos que su versión HTML.
- **`/admin/` de Django — qué permite hacer y a quién:**
  - Cajero y Contador: **NO pueden entrar**, `AdminSoloGerente`
    (`core/middleware.py:68-84`) los redirige a `core:dashboard` en cualquier
    ruta bajo `/admin/*` que no sea login/logout. Verificado por lectura
    directa del middleware.
  - Gerente (no superusuario): SÍ entra, pero sus permisos de Django están
    limitados a exactamente 5 pares (app, modelo) —
    `core/management/commands/asignar_rol.py:PERMISOS_GERENTE`, líneas
    25-31: `catalogo.producto` (add/change/view), `catalogo.categoria`
    (add/change/view), `catalogo.cambioprecio` (view), `ventas.cliente`
    (add/change/view), `compras.proveedor` (add/change/view). **Ningún
    permiso de `delete` en absoluto**, y ningún permiso sobre `Compra`,
    `FacturaVenta`, `Asiento`, `MovimientoCaja`, `MovimientoInventario`,
    `CierrePeriodo`, `CuentaContable`, `AuditLog`, `ChatMensaje`, `Empresa`,
    `Sucursal`, `DevolucionVenta`, `DocumentoCxC`, `Bodega` — Django oculta
    del índice de admin cualquier modelo sin permiso asignado, así que un
    Gerente normal ni siquiera los ve ahí.
  - Superusuario (el "dueño", marcado con `--dueno` en `asignar_rol.py`, o
    cualquier cuenta que ya lo era y se re-asigna como Gerente —
    `asignar_rol.py:85-88`, que preserva `is_superuser` en vez de degradarlo):
    acceso total a todos los modelos, sin excepción, porque Django concede
    todos los permisos implícitamente a `is_superuser=True`
    independientemente de `Permission` asignados. **Este es el actor
    relevante para SEC-002.**
  - **Qué se puede hacer sin dejar rastro en `AuditLog`:** las **lecturas**
    (listar/ver) en `/admin/` nunca se auditan (las señales solo cubren
    `pre_save`/`post_save`/`post_delete`, `core/signals.py:177-185`) — un
    Gerente o el dueño pueden navegar y ver cualquier dato al que tengan
    permiso sin dejar huella. Esto es estándar en casi cualquier sistema
    (auditar cada lectura sería impracticable) pero vale declararlo:
    **hoy no hay forma de saber quién MIRÓ qué**, solo quién lo cambió.
- **¿Puede un Gerente borrar o alterar `AuditLog` desde `/admin/`?** (pregunta
  prioritaria de esta sesión) **NO.** `core/admin.py:17-33`,
  `AuditLogAdmin`: `has_add_permission`, `has_change_permission` y
  `has_delete_permission` devuelven `False` sin condición — ni un Gerente ni
  el superusuario pueden crear, editar o borrar una fila de `AuditLog` desde
  el admin de Django. Es el único camino de escritura sobre ese modelo
  encontrado en todo el código (las filas nacen exclusivamente por las
  señales de `core/signals.py`). **Verificado por lectura directa, no por
  inferencia.**

## Inyecciones

- **SQL:** `[HECHO]` sin riesgo encontrado — cero coincidencias de `.raw(`,
  `.extra(` o interpolación de f-strings en construcción de queries en todo
  el repositorio (grep sobre `*.py`, excluido `.venv`). Todo el acceso a
  datos usa el ORM de Django con parámetros.
- **XSS:**
  - `[HECHO]` sin uso del filtro de template `|safe` en ningún archivo
    `.html` del proyecto (grep exacto de `\|safe`, cero resultados — una
    búsqueda anterior con un patrón más laxo había sugerido 41 coincidencias
    en 11 archivos; se verificó que era un falso positivo del patrón de
    búsqueda, no del código).
  - `mark_safe()` se usa en **un solo lugar**: `inventario/views.py:118`,
    `mark_safe(svg_barcode(p.codigo_barras))`, para embeber el SVG del
    código de barras en la página de etiquetas. `codigo_barras` es editable
    por un Gerente (no está en `readonly_fields` de `catalogo/admin.py:63`).
    **Se probó activamente**: se generó un código de barras con el valor
    `<script>alert(1)</script>` usando la misma librería y opciones del
    proyecto (`python-barcode`, `SVGWriter`) — el texto queda escapado como
    `&lt;script&gt;alert(1)&lt;/script&gt;` dentro del `<text>` del SVG
    resultante. **Riesgo descartado**: la librería escapa el texto por
    diseño; `mark_safe` aquí es seguro porque el contenido que envuelve ya
    viene sanitizado por una capa anterior, no por el propio `mark_safe`.
  - JavaScript que inserta HTML vía `.innerHTML`: 11 ocurrencias
    (`ventas/pos.html`, `compras/nueva.html`, `core/includes/chat_widget.html`).
    Las de `pos.html`/`nueva.html` renderizan datos de `Producto` que ya
    pasaron por el `json_script` del backend (auto-escapado); las de
    `chat_widget.html` pasan explícitamente por `escapeHtml()`
    (líneas 235-239, usa el truco `textContent`→`innerHTML` del propio DOM,
    que escapa correctamente) **antes** de `renderMarkdown()`
    (línea 244: `const escaped = escapeHtml(text)` es lo primero que hace) —
    verificado leyendo las funciones completas, no solo su nombre. Sin
    hallazgo.
  - **59 atributos `onclick=` inline** mencionados en el propio comentario de
    `core/seguridad.py:10` — confirmados (13+ por archivo en varios
    templates). Es la razón documentada por la que la CSP de `script-src`
    sigue en modo solo-reporte (`core/seguridad.py:30-42`, ver Fase 0). No es
    un hallazgo nuevo, es la misma exposición de defensa-en-profundidad
    incompleta ya reconocida en el propio código — se deja constancia aquí
    porque Fase 1 la pide explícitamente.
- **CSRF:** `[HECHO]` sin exenciones — cero coincidencias de `@csrf_exempt`
  en todo el repositorio. Los 3 templates que hacen `fetch()` con POST
  (`ventas/pos.html`, `compras/nueva.html`, `core/includes/chat_widget.html`)
  envían el token vía cookie/cabecera (patrón `getCookie('csrftoken')`
  encontrado en los tres). `CsrfViewMiddleware` está activo
  (`config/settings.py:100`) y no se desactiva en ningún punto.
- **Inyección en generación de XML fiscal:** no aplica — no existe
  generación de XML fiscal (Fase 0, pregunta 0.A.1).
- **Mass assignment:** `[HECHO]` sin riesgo estructural — ninguna de las 7
  apps usa `ModelForm` con `fields = "__all__"` (de hecho, 5 de las 7 apps no
  tienen `forms.py` en absoluto); los payloads JSON se parsean campo por
  campo explícitamente en las views (`compras/views.py:registrar`,
  `producto_nuevo`; `ventas/views.py:vender`), no hay ningún `Model(**request.POST)`
  ni deserialización genérica encontrada.
- **Path traversal en `importar_imagenes`:** **investigado, riesgo
  descartado en la práctica.** `catalogo/management/commands/importar_imagenes.py:80`
  sanea el `target` del XML de relaciones con `.replace("../", "")` antes de
  usarlo para leer del zip; el nombre de archivo final
  (`nombre_archivo = f"{prod.sku}{ext}"`, línea 119) usa `Path(media).suffix`
  (que solo extrae la extensión, nunca una ruta) y el `sku` viene de
  productos ya existentes en la base, no de un campo que un usuario web
  controle. Es además un comando de terminal ejecutado manualmente por quien
  ya tiene acceso al servidor con un archivo local — no es una superficie
  alcanzable desde la aplicación web. Sin hallazgo.

## Uploads

Dos caminos de subida de imágenes encontrados, ambos ya evaluados en Fase 0
y re-confirmados aquí:

- `compras/views.py:producto_nuevo` (foto de producto nuevo, base64 desde el
  navegador): `_validar_foto`/`_extension_real` (`compras/views.py:61-100`)
  deducen el tipo real por firma binaria (PNG/JPEG/WebP), no por lo que
  declara el cliente; tope de 5 MB; nombre de archivo derivado del `sku`
  generado por el servidor, nunca del input del cliente; verificación
  adicional con Pillow si está disponible. **Bien mitigado** — corrige
  explícitamente un hallazgo previo (SEG-06) que permitía subir SVG/HTML
  ejecutable con nombre arbitrario.
- `catalogo/management/commands/importar_imagenes.py` (extracción desde
  Excel): no es una superficie web, ver punto anterior.
- No se encontró ningún otro endpoint de subida de archivos en las 7 apps
  (ni en `ventas`, `inventario`, `caja`, `contabilidad`).

## Configuración

Ya documentada en detalle en Fase 0 (`00_mapa_sistema.md`, sección
`settings.py`). Resumen desde el ángulo de seguridad, sin repetir lo ya
citado: `DEBUG` no puede quedar encendido en producción (`RuntimeError` si
`SECRET_KEY` de desarrollo se usa con `DJANGO_PRODUCTION=1`); `ALLOWED_HOSTS`
configurable, sin comodín por defecto; HTTPS/HSTS/cookies `Secure` solo se
activan si `PRODUCCION=True` — **en local (`PRODUCCION=False`) las cookies
NO llevan `Secure`** (esto es correcto para desarrollo sobre HTTP, pero
depende de que `DJANGO_PRODUCTION=1` esté realmente puesto en el VPS;
`[NO VERIFICADO]` si esa variable está seteada en el entorno de producción
real hoy — es una variable de despliegue, no algo que el código pueda
garantizar por sí solo). `SESSION_COOKIE_HTTPONLY=True` está activo siempre,
dentro y fuera de producción (`config/settings.py:70`). Sin CORS configurado
(`django-cors-headers` no está instalado, sin `CORS_*` en settings) — el
comportamiento por defecto del navegador (mismo origen) aplica sin
relajarse, lo cual es la postura segura por omisión. Mensajes de error: en
producción `DEBUG=False` implica páginas de error genéricas de Django (sin
traceback); `[NO VERIFICADO]` el contenido exacto de `templates/404.html`/
`500.html` (no se leyeron en esta sesión). Logs: `LOGGING` no imprime
contraseñas ni tokens en el formato configurado
(`config/settings.py:275-283`), pero **no se auditó si algún `logger.exception`
específico podría volcar un `request.body` con datos sensibles** — no se
encontró ningún caso así en los módulos leídos, pero no se hizo un grep
exhaustivo de todas las llamadas a `logger.*` del proyecto. `[NO VERIFICADO]`.

## Dependencias

Mismas 7 declaradas en `requirements.txt` (Fase 0). Se intentó ejecutar
`pip-audit` en esta sesión para contrastar contra CVEs conocidos:
**no está instalado en el entorno** y no se instaló (evitar acciones fuera
del alcance de solo-lectura/diagnóstico sin permiso explícito). Se marca
`[NO VERIFICADO]`, tal como exige la regla del prompt maestro para no
inventar CVEs. **Recomendado como siguiente paso concreto**: `pip install
pip-audit && pip-audit -r requirements.txt` en un entorno de prueba.

---

## Fraude interno

Prioridad alta declarada por el propio prompt maestro para retail. Cada
pregunta respondida con evidencia directa:

| # | Pregunta | Respuesta | Evidencia |
|---|---|---|---|
| 1 | ¿Puede un cajero anular una venta sin autorización de supervisor? | **NO** | `ventas/views.py:172-174`, `anular` exige `@rol_requerido(GERENTE)` — Cajero no calificado |
| 2 | ¿Puede modificar el precio de un producto durante la venta? | **NO** | `ventas/services.py:96`, `precio = producto.precio_venta` — el precio se lee del servidor, el payload de venta solo manda `producto_id`/`cantidad`/`descuento_pct`/`es_regalia` (`ventas/views.py:78-84`) |
| 3 | ¿Puede aplicar descuentos sin límite? | **SÍ, parcialmente** — ver **SEC-001** | `ventas/services.py:98-100` acepta `descuento_pct` de 0 a 100 sin exigir un segundo permiso; el único freno es no vender bajo costo (`services.py:104-113`), que no aplica si el margen del producto alcanza para absorber el descuento |
| 4 | ¿Puede eliminar movimientos de caja? | **NO** | `caja/admin.py:6-14`, `SoloLectura` aplicado a `MovimientoCajaAdmin`; `caja/services.py` no tiene ninguna función de borrado |
| 5 | ¿Puede registrar una devolución de mercadería que nunca volvió? | **Requiere GERENTE; el sistema no verifica el regreso físico** — ver **AUD-001** | `ventas/views.py:187-188` exige `@rol_requerido(GERENTE)`; `ventas/devoluciones.py:registrar_devolucion` confía en los datos que ingresa quien procesa, sin segunda verificación; el documento no queda en `AuditLog` (aunque sí en kardex/caja y en el propio registro inmutable) |
| 6 | ¿Puede hacer un ajuste de inventario que oculte un faltante? | **El ajuste en sí NO se puede ocultar** (motivo obligatorio + auditado por partida doble: kardex y `AuditLog`), **pero el sistema no verifica que el motivo declarado sea verdadero** | `inventario/views.py:24-51`, `@rol_requerido(GERENTE)`; `AjusteInventarioForm.clean_cantidad` exige motivo (`inventario/forms.py:35-39`); `inventario.movimientoinventario` está en `AUDITED` (`core/signals.py:51`) |
| 7 | ¿Puede abrir caja con un monto inicial falso? | **El dato se acepta sin verificación al momento de abrir**; la discrepancia se revela recién al cierre, no se previene | `caja/services.py:abrir_caja` (líneas 16-33) no compara contra nada físico; `cerrar_caja` (líneas 54-70) calcula `diferencia = contado - esperado`, que arrastra cualquier apertura falsa como parte del "esperado" |
| 8 | ¿Puede ejecutar management commands? | **Sin autorización de aplicación en absoluto** — ver **SEC-005** | `core/management/commands/reconciliar.py` (docstring propio: "Sin control de permisos de aplicación (es un comando de servidor)"); ninguno de los 10 comandos valida rol/usuario de Django, solo argumentos de la propia terminal |
| 9 | ¿Puede acceder al admin de Django? | **Cajero/Contador: NO. Gerente no-dueño: acceso muy limitado (5 modelos, sin `delete`). Superusuario: acceso total** — ver **SEC-002** | `core/middleware.py:68-84` (bloqueo por rol); `core/management/commands/asignar_rol.py:25-31` (permisos concretos del Gerente) |

**Lectura de conjunto:** el diseño de fraude interno es, en su mayoría,
sólido y deliberado — el comentario de `core/roles.py:8-13` describe
explícitamente que el límite del Cajero (no anular, no devolver, no recibir
mercadería, no ver contabilidad) es "la defensa anti-fraude" contra el robo
típico de anular-y-quedarse-el-efectivo, y el código lo cumple. Las dos
grietas reales encontradas son más sutiles: (a) el descuento de línea no
tiene techo propio, solo el piso de costo (**SEC-001**), y (b) la devolución
—la otra mitad clásica del mismo fraude ("anular" y "devolver" son
funcionalmente primos)— no queda en la bitácora central aunque el documento
en sí sea inmutable (**AUD-001**).

---

## Hallazgos

| ID | Severidad | Problema | Evidencia | Riesgo | Impacto (dueño del negocio) | Solución | Esfuerzo | Dependencias |
|---|---|---|---|---|---|---|---|---|
| **SEC-001** ✅ *cerrado — commit `a4d3008`* | 🟠 alto | Un Cajero puede aplicar hasta 100% de descuento por línea sin autorización de un Gerente; el único freno es no vender bajo el costo promedio | `ventas/services.py:98-113` | Cajero deshonesto regala/subvalora mercadería a cómplices dentro del margen del producto, sin aprobación ni alerta | Fuga de margen que solo se nota después, al revisar reportes de rentabilidad — no en el momento de la venta | Umbral configurable de descuento máximo sin aprobación (p. ej. 15-20%); por encima, exigir que la venta la registre un Gerente o pedir un código de autorización | S–M | Ninguna |
| **AUD-001** ✅ *cerrado — commit `b768b39`* | 🟠 alto | `ventas.devolucionventa` no está en el set `AUDITED` de `core/signals.py` — las devoluciones no generan fila en `AuditLog`, a diferencia de todos los demás documentos de negocio | `core/signals.py:47-63` (ausencia); contraste con `ventas/devoluciones.py:65-67` | Una devolución fraudulenta (mercadería que nunca volvió) no aparece al buscar "qué hizo tal usuario" en la bitácora central | Si falta mercadería, reconstruir "quién procesó qué devolución y cuándo" exige revisar documento por documento en vez de una búsqueda centralizada | Agregar `"ventas.devolucionventa"` a `AUDITED` (`core/signals.py:47`) | S | Ninguna |
| **SEC-002** ✅ *cerrado — commit `b768b39`* | 🟠 alto | `compras/admin.py:CompraAdmin` es el único `ModelAdmin` de documento (de 8) que no bloquea `has_change_permission`/`has_delete_permission`; su inline `LineaCompraInline` tampoco fija `can_delete=False` | `compras/admin.py` completo, contrastado con `ventas/admin.py:42-49`, `contabilidad/admin.py:46-53`, `inventario/admin.py:23-30`, etc. | El superusuario (o cualquier cuenta que el sistema deje llegar a superusuario, ver `asignar_rol.py:85-88`) puede borrar una compra ya `RECIBIDA` desde `/admin/`: `LineaCompra` se borra en cascada (FK `CASCADE`), pero `MovimientoInventario` y `Asiento`/`LineaAsiento` NO tienen FK a `Compra` (solo un `referencia`/string con el número) y quedan intactos, huérfanos de su documento origen; `Proveedor.saldo` (si era crédito) queda inflado porque nada ejecuta la lógica de reversa de `anular_compra` — ver análisis detallado abajo de la tabla | Cuentas por pagar a proveedor quedan infladas si la compra era a crédito (`reconciliar` lo detecta en la próxima corrida); si era de contado, ningún chequeo automático lo detecta — solo un cruce manual por número de documento | Agregar `has_add_permission`/`has_change_permission`/`has_delete_permission = False` a `CompraAdmin` (igual que sus 8 pares) y `can_delete = False` a `LineaCompraInline`; para corregir una compra, usar siempre `anular_compra` | S | Ninguna |
| **SEC-003** | 🟢 bajo | `catalogo/admin.py:86` (`ProductoAdmin.entrada_view`) abre `Producto` con `get_object_or_404` sin pasar por `core.tenancy.documento_de_empresa` — el único punto de los 7 apps (fuera de la propia `tenancy.py`) que se salta el patrón | `catalogo/admin.py:86` | Hoy no explotable (una sola empresa); el día que haya una segunda, este punto queda descubierto para IDOR | Ninguno hoy; riesgo latente si el negocio se expande a multi-empresa | Usar `documento_de_empresa` también en las vistas custom de `ModelAdmin` | S | Ninguna |
| **SEC-004** | 🟢 bajo | Sin 2FA para Gerente/superusuario, sin límite de sesiones concurrentes, sin flujo propio de recuperación de contraseña | `requirements.txt` (sin paquete 2FA), `config/settings.py` (sin límite de sesión), `config/urls.py` (sin rutas `password_reset*`) | Un ex-empleado con sesión activa en un dispositivo sigue autenticado hasta que alguien cambie su contraseña explícitamente (Django invalida sesiones automáticamente al cambiar contraseña, pero nadie lo hace si no sabe que hace falta) | Acceso residual de personal que ya no debería tenerlo, sin fecha de caducidad automática | Checklist operativo de baja de personal (cambiar contraseña / desactivar usuario el mismo día); evaluar 2FA para el rol Gerente | S (proceso) / M (2FA) | Ninguna |
| **SEC-005** | 🔴 crítico *(recalibrado — ver análisis abajo de la tabla)* | Los 10 management commands no tienen ninguna autorización de aplicación — quien tenga terminal en la máquina donde corre el ERP puede autopromoverse a superusuario, borrar `AuditLog` directo por ORM (bypassea el candado de `/admin/`), o restaurar la base desde un zip arbitrario para borrar evidencia | `core/management/commands/asignar_rol.py` (sin chequeo de quién lo ejecuta); `restaurar.py` (requiere solo `--confirmar`, no una sesión ni un rol) | La máquina que corre el ERP es el propio POS del mostrador, usado sin supervisión por el Cajero durante todo su turno (confirmado por el usuario) — el actor que este control necesita frenar es exactamente el actor prioritario del threat model, no un atacante remoto hipotético | Compromiso total: dinero, inventario, datos de clientes, y la posibilidad de borrar el propio rastro de auditoría (`restaurar`) después de un fraude — sin dejar ninguna de las protecciones de esta fase con efecto | Cuenta de Windows restringida para el personal en la máquina del POS (sin terminal/PowerShell, sin acceso de exploración a la carpeta del proyecto) — verificar YA si existe; si no existe, es la acción más urgente de todo este informe, por delante de cualquier otro hallazgo | S (si es solo configurar la cuenta de Windows) / M (si hay que migrar a otro esquema) | Decisión de infraestructura, fuera del alcance de este repositorio — pero de prioridad máxima |
| **SEC-006** | 🟠 alto | Marcar una línea de venta como `es_regalia` (precio 0, sale del inventario a costo) no tiene ninguna validación de rol — cualquier Cajero puede hacerlo, sin motivo obligatorio, sin tope de monto y **sin pasar por el piso de costo** que sí limita a los descuentos (SEC-001) | `ventas/services.py:87-113` (la rama `if es_regalia:` está fuera del bloque `if not permitir_bajo_costo and ...`, líneas 104-113 — el chequeo de piso de costo simplemente no se ejecuta para regalías); `ventas/views.py:71-99` (`vender`, `@rol_requerido(CAJERO, GERENTE)`, sin distinción adicional); `templates/ventas/pos.html` (botón "🎁 Regalo", sin `{% if es_gerente %}` ni equivalente) | Un cajero deshonesto entrega mercadería de cualquier valor sin cobrar nada, a un cómplice, sin aprobación de un Gerente y sin el único freno que sí aplica al descuento | Pérdida de mercadería a valor completo (no solo de margen, como en SEC-001) camuflada como "regalía/promoción" — el rastro existe pero está repartido en tres lugares (kardex `tipo=REG`, cuenta contable "Gasto por regalías", ranking de más vendidos que mezcla unidades regaladas con vendidas) y no hay un solo reporte donde el dueño lo vea agrupado | Exigir `@rol_requerido(GERENTE)` para marcar `es_regalia`, o motivo obligatorio + tope de monto por regalía, igual que se decida para SEC-001; agregar un reporte que agrupe regalías por periodo/cajero/producto | S–M | Decisión de negocio pendiente (igual que SEC-001) — implementación diferida a otra sesión |

### SEC-002 — por qué queda en 🟠 alto y no en 🔴 crítico

Análisis puntual pedido en esta sesión: qué pasa exactamente al borrar una
`Compra` `RECIBIDA` desde `/admin/`, campo por campo, verificado leyendo
`compras/models.py` (relaciones), `core/signals.py` (auditoría) y
`core/management/commands/reconciliar.py` (red de seguridad) — no inferido.

**1. Qué le pasa a cada modelo relacionado:**

| Modelo | Relación con `Compra` | Efecto del borrado |
|---|---|---|
| `LineaCompra` | FK `compra→Compra`, `on_delete=CASCADE` | **Se borra en cascada.** Las líneas (qué productos, cantidades, costos) desaparecen de la base. |
| `MovimientoInventario` | Sin FK a `Compra` — solo `referencia` (`CharField`) con el número | **Queda intacto.** El movimiento de kardex (tipo `COM`) sigue existiendo con producto, cantidad, costo, usuario y fecha; su `referencia` pasa a apuntar a un número de compra que ya no existe en la tabla. `Producto.stock_actual` no se toca — sigue reflejando la entrada, porque nada en un `Model.delete()` de Django ejecuta la lógica de negocio de `anular_compra`. |
| `Asiento` / `LineaAsiento` | Sin FK a `Compra` — solo `referencia` (string) | **Queda intacto**, igual que el kardex. El asiento sigue cuadrado (`debe == haber`) porque nunca dependió de que `Compra` existiera como fila. |
| `Proveedor.saldo` | Campo denormalizado, se incrementa solo dentro de `recibir_compra` (`compras/services.py:87-88`) | **Queda inflado indefinidamente** si la compra era a crédito — nada en el borrado ejecuta el decremento que sí hace `anular_compra` (`compras/services.py:136-139`). |

No hay cascada de corrupción hacia el kardex ni hacia la contabilidad: esos
dos libros son independientes de `Compra` por diseño (se vinculan por un
número de texto, no por FK) y sobreviven intactos. Lo que se pierde es la
cascada hacia `LineaCompra` y la sincronía de `Proveedor.saldo`.

**2. ¿Queda alguna fila en `AuditLog`?** **Sí.** `compras.compra` está en
`AUDITED` (`core/signals.py:47-63`), así que el `post_delete` dispara
`_auditar_borrado` (`core/signals.py:149-160`) y crea una fila con
`accion="borrar"`, un snapshot completo de los campos de la `Compra`
(`numero`, `proveedor_id`, `total`, `estado`, `forma_pago`, fechas —
vía `model_to_dict`), el usuario que la borró y su IP (el middleware de
auditoría está activo también dentro de `/admin/`). **Límite real:**
`compras.lineacompra` está en `NO_AUDITADOS_A_PROPOSITO` (exclusión
documentada, `core/signals.py:69-73`) — el detalle de qué productos y
cantidades tenía la compra NO queda en `AuditLog`; solo los campos propios
de la `Compra` (el snapshot no incluye a sus hijos).

**3. ¿Se puede reconstruir después del hecho?** **Depende de qué se
pregunte, y de la forma de pago:**

- **Qué compra era y quién la borró:** sí, completo, desde el snapshot de
  `AuditLog.antes`.
- **Qué productos y cantidades entraron:** sí, cruzando manualmente el
  kardex (`MovimientoInventario` tipo `COM`) por `referencia == numero`
  (el `numero` se recupera del snapshot) — el kardex nunca se borró.
- **El efecto contable:** sí, igual, cruzando `Asiento`/`LineaAsiento` por
  `referencia == numero` — el asiento nunca se borró.
- **`Proveedor.saldo` (si era crédito):** se lee `reconciliar.py:159-179`
  (`_revisar_proveedores`): recalcula el "esperado" sumando
  `Proveedor.compras.filter(forma_pago=CREDITO, estado=RECIBIDA)` — como la
  fila de `Compra` ya no existe, ese recálculo la excluye y da un total
  **menor** que el `saldo` guardado (que nunca bajó). **`reconciliar` SÍ
  reporta esa diferencia en su próxima corrida**, con el proveedor y el
  monto exacto — no corrige, pero avisa.
- **Si la compra era de contado:** `reconciliar` no tiene ningún chequeo
  que la toque — de sus 4 verificaciones (stock, CxC, cliente, proveedor),
  ninguna se ve afectada por una compra de contado borrada. Este caso
  **no genera ninguna alerta automática**; solo se descubre si alguien cruza
  manualmente el kardex o el libro diario contra los números de compra
  esperados.
- **`stock_actual`:** `reconciliar._revisar_stock` (líneas 91-112) compara
  `Producto.stock_actual` contra la suma del kardex — y como ninguno de los
  dos "sabe" que la `Compra` que originó el movimiento ya no existe, **los
  dos lados siguen coincidiendo y el chequeo pasa en verde.** El stock no
  queda mal — el problema es exclusivamente documental (se perdió el
  expediente de por qué ese stock entró), no numérico.

**Conclusión — por qué alto y no crítico:** no hay corrupción numérica
silenciosa e irrecuperable. El actor está limitado al superusuario (la
cuenta de más confianza del sistema, no un Gerente ni un Cajero); el
borrado en sí queda plenamente atribuido en `AuditLog`; los dos libros que
de verdad sostienen la integridad financiera (kardex y contabilidad) nunca
se tocan y permiten reconstrucción completa cruzando por número de
documento; y el caso de crédito tiene una red de seguridad real
(`reconciliar` lo señala). La grieta genuina —y la razón de que sea alto y
no medio/bajo— es doble: (a) el caso de **contado** no tiene ninguna alarma
automática, y (b) `Proveedor.saldo` no se autocorrige nunca, solo se
señala; alguien tiene que leer el reporte de `reconciliar` y arreglarlo a
mano. Es una laguna real de una capa de defensa (el `ModelAdmin`), no una
falla de las dos capas que sostienen la verdad del negocio (kardex y libro
contable).

### SEC-005 — recalificación de 🟡 medio a 🔴 crítico

Evaluado originalmente como medio porque se asumía que "acceso a terminal en
la máquina del ERP" era una barrera adicional, distinta y más difícil de
alcanzar que los actores ya considerados. El usuario confirmó el dato de
despliegue que faltaba: esa máquina **es el propio POS del mostrador**,
usado por el Cajero sin supervisión durante todo su turno — no un servidor
aparte con acceso restringido. Eso colapsa "atacante con acceso al sistema
operativo" y "cajero deshonesto" en el **mismo actor, en el mismo momento**,
que es exactamente el actor que el threat model de esta fase ya marca como
prioritario en retail.

Con ese actor confirmado, la cadena de explotación no requiere ningún bug:

1. Abrir una terminal en una sesión de Windows sin restricciones (`Win+R` →
   `cmd`, o un acceso directo) — sin exploit, sin conocimiento técnico
   avanzado.
2. Ejecutar `python manage.py asignar_rol <su_usuario> Gerente --dueno`
   (`core/management/commands/asignar_rol.py`, comando documentado y
   soportado, no una falla) — superusuario instantáneo.
3. Desde ahí, **cada control descrito en esta fase deja de aplicar**,
   incluido uno que se verificó explícitamente como sólido: la
   inmutabilidad de `AuditLog` es un candado de `ModelAdmin`
   (`core/admin.py:26-33`, `has_add/change/delete_permission = False`) —
   protege la interfaz `/admin/`, no el ORM ni la base. `manage.py shell` →
   `AuditLog.objects.all().delete()` no pasa por ese candado en absoluto.
4. `restaurar.py --confirmar` permite además restaurar la base a un punto
   anterior, borrando el rastro de cualquier fraude cometido antes de
   ejecutarlo — ataca la premisa completa de trazabilidad de la Fase 8.

**Por qué crítico y no alto:** a diferencia de SEC-001/SEC-002/AUD-001
(que requieren margen de decisión, motivo, o exposición en `reconciliar`/
`AuditLog`), esta ruta no dependa de la voluntad del sistema en absoluto —
opera completamente por fuera de él. No hay auditoría, no hay motivo
obligatorio, no hay segunda capa: es la diferencia entre "el sistema tiene
una grieta" y "el sistema, para este actor, no existe".

**Lo único que puede seguir mitigando esto**, y que esta sesión no puede
verificar desde el código: si la cuenta de Windows que usan los cajeros en
esa máquina está restringida (sin terminal/PowerShell, sin navegación a la
carpeta del proyecto) — `[NO VERIFICADO]`. Es, con la información
disponible hoy, la variable más importante de todo este informe: mientras
no se confirme que existe esa restricción, hay que asumir que no existe.

### SEC-006 — hallazgo nuevo, descubierto investigando SEC-001

Surgió de tres preguntas puntuales antes de implementar SEC-001: quién
puede marcar una línea como regalía, si queda auditado, y si el piso de
costo también la protege. Las tres respuestas, verificadas leyendo
`ventas/services.py`, `ventas/views.py`, `core/signals.py`, `core/reportes.py`
y `templates/ventas/pos.html` — no inferidas:

1. **¿Quién puede marcarla?** Cualquier Cajero, sin validación de rol
   propia. `es_regalia = bool(linea.get("es_regalia", False))`
   (`ventas/services.py:85`) se lee directo del JSON del navegador; `vender`
   (`ventas/views.py:71-72`) exige `@rol_requerido(CAJERO, GERENTE)`, sin
   distinguir entre ambos para esta rama (a diferencia de
   `permitir_bajo_costo=es_gerente(request.user)`, línea 88, que sí lo hace).
   El botón "🎁 Regalo" en `pos.html` no tiene ningún `{% if es_gerente %}`
   — verificado con grep sobre el archivo completo.
2. **¿Queda auditado?** Parcialmente y de forma dispersa. `ventas.lineaventa`
   está en `NO_AUDITADOS_A_PROPOSITO` (`core/signals.py:69-73`), así que la
   fila con `es_regalia=True` no genera `AuditLog` directo, y el snapshot de
   la `FacturaVenta` padre no incluye sus líneas. Sí queda un movimiento de
   kardex `tipo="REG"` (auditado, porque `inventario.movimientoinventario`
   sí está en `AUDITED`) y un asiento contable a la cuenta "Gasto por
   regalías" (`ventas/contabilizar.py:_costos_por_tipo`, líneas 36-41),
   visible en `contabilidad:estado_resultados`. Pero `core/reportes.py:mas_vendidos`
   (línea 37-38, comentario propio del código) mezcla las unidades regaladas
   con las vendidas en el mismo ranking, sin desglosarlas — no existe un
   reporte que agrupe "cuánto se regaló, a quién, qué cajero".
3. **¿El piso de costo la protege?** No. El chequeo de "no vender bajo
   costo" (`ventas/services.py:104-113`) vive dentro del `else` de
   `if es_regalia: ... else: (piso de costo) ...` — para una regalía esa
   rama ni se ejecuta. El descuento de SEC-001 al menos choca contra ese
   piso; la regalía no choca contra nada.

**Por qué alto:** es una variante del mismo problema de fondo que SEC-001
(entrega de valor sin aprobación de supervisor) pero sin ninguno de sus dos
frenos — ni el piso de costo, ni visibilidad centralizada. No se calibra
como crítico porque, igual que SEC-001, sigue dentro de las herramientas
normales del sistema (dos capas del expediente —kardex y contabilidad—
sobreviven y son cruzables), no es un bypass total como SEC-005.

**Implementación diferida.** El umbral de descuento de SEC-001 y el
tratamiento de `es_regalia` de SEC-006 son decisiones de negocio (¿cuánto
sin aprobar? ¿lo mismo para ambos, o reglas distintas?) que quedan
pendientes de definir en otra sesión — este hallazgo se documenta, no se
corrige, por instrucción explícita.

**Nota fuera de alcance de esta fase, dejada por transparencia:**
`contabilidad/views.py:iva_trimestral` (líneas 162-220) calcula el impuesto
estimado asumiendo Régimen de Tributación Simplificada
(`factor_rts × compras del trimestre`) y `es_rts` se deriva de
`empresa.regimen == empresa.Regimen.SIMPLIFICADO` (línea 219). Dado el
contexto confirmado por el usuario (régimen real: General, no RTS), esta
vista quedaría calculando un impuesto que no corresponde al régimen real de
la empresa — pero esto es una discrepancia de cumplimiento fiscal (Fase 4),
no de seguridad; se deja registrada aquí solo porque apareció durante la
lectura de `contabilidad/views.py` en esta fase.

---

## Cobertura y límites de esta fase

**Revisado en esta sesión, con lectura directa y cita:** los 7 archivos
`admin.py` completos (prioridad #1 del usuario), grep exhaustivo de
`get_object_or_404` en todo el repositorio (prioridad #2), verificación
directa de permisos de `AuditLog` en el admin (prioridad #3),
`core/chat_tools.py` completo, `core/views.py:chat_claude` completo,
`core/dashboard.py` completo, `templates/core/dashboard.html` (sección de
KPIs), `templates/core/includes/chat_widget.html` (funciones de escape),
`inventario/etiquetas.py` con prueba empírica de escapado,
`catalogo/management/commands/importar_imagenes.py` completo,
`core/management/commands/asignar_rol.py` completo, grep de
`csrf_exempt`/`.raw(`/`.extra(`/`|safe`/`onclick=`/`.innerHTML` en todo el
proyecto.

**No verificado / fuera de alcance de esta sesión:** contenido de
`templates/404.html`/`500.html`; grep exhaustivo de todas las llamadas a
`logger.*` del proyecto en busca de datos sensibles en logs; CVEs de
dependencias (`pip-audit` no disponible en este entorno); si
`DJANGO_PRODUCTION=1` está realmente configurado en el VPS de producción
hoy (variable de despliegue, no verificable desde el código); **si la
cuenta de Windows que usan los cajeros en la máquina del POS está
restringida (sin terminal/PowerShell) — confirmado por el usuario que esa
máquina es el mostrador mismo, usado sin supervisión durante el turno, lo
que llevó a recalificar SEC-005 a 🔴 crítico; queda pendiente confirmar si
existe esa restricción de sistema operativo, la variable que hoy más pesa
en todo este informe.**

**Cobertura global estimada de Fase 1: ~70%** del código relevante para
seguridad (seguridad de autenticación/autorización/inyección/uploads casi
completa; configuración de despliegue real y dependencias con huecos
declarados). `[INFERENCIA]`, no una métrica medida — se declara así para
cumplir la regla de no dar veredicto sin declarar cobertura.
