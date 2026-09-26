# Registro de hallazgos — ALLPETCR ERP

Estado de cada hallazgo de auditoría **verificado contra el código**, no contra
lo que dice el informe. Este archivo existe porque dos revisiones seguidas
(22/07 y 28/07) perdieron tiempo re-diagnosticando cosas que ya estaban
corregidas: los informes se escriben una vez, el código sigue cambiando.

**Regla: al cerrar un hallazgo se actualiza esta tabla en el mismo commit.**

- Última actualización: **28/07/2026**
- Auditoría vigente: `Auditoria_2026-07-28` (8 documentos, 42 hallazgos)
- Suite: **240 pruebas en verde** · `check --deploy` sin advertencias

## Fuera del alcance de la auditoría

**Rediseño de la factura a color** (28/07, tarde — dos iteraciones). No es un
hallazgo de auditoría: fue un pedido de diseño de Oscar. Se rehizo
`templates/ventas/factura.html` por completo.

- **v1**: A4 vertical, banda azul/dorado, tarjeta de total flotante junto a la
  tabla, cápsula de estado, iconos, pie con contacto.
- **v2** (versión vigente): layout de dos columnas al estilo Stripe/Shopify —
  columna izquierda (~68%) con cliente y tabla de productos, panel lateral
  fijo (~32%, fondo `#F8FAFC`) con tarjeta de total, resumen de compra y
  método de pago. Tipografía Inter. Iconos SVG dibujados a mano en estilo
  Lucide, sin depender de un CDN externo (mismo criterio que el resto del
  ERP: un correo HTML no debería depender de un tercero para verse bien).
  Escala de espaciado de 8px. Botón de correo primero (azul, con ícono),
  imprimir segundo (blanco, con ícono).

Se agregó `FacturaVenta.estado_visual` (`ventas/models.py`) que traduce
Emitida/Anulada + `DocumentoCxC` a Pagada/Pendiente/Anulada — el modelo no
tenía un campo "pagada" directo. 5 pruebas en `ventas/test_estado_visual.py`.

**Se dejaron fuera, a propósito, en ambas iteraciones:** QR de Hacienda (el
sistema es Régimen Simplificado, no emite comprobante electrónico — no hay
clave numérica que codificar) y QR de seguimiento de pedido (no existe
tracking en este ERP). Agregarlos el día que corresponda: el de Hacienda
cuando se implemente facturación electrónica v4.4 (ver PERF-05/roadmap), el
de seguimiento si se construye un sistema de pedidos.

---

## Cómo leer el estado

| Estado | Significado |
|---|---|
| **Cerrado** | Corregido y con prueba que lo fija. No hay que volver a mirarlo. |
| **Parcial** | Lo urgente está hecho; queda trabajo acotado, descrito en la fila. |
| **Abierto** | Sin corregir. |
| **No aplica (ERP)** | Es del sitio web `allpetcr-web`, no de este repo. |

---

## Hallazgos del ERP

### Arquitectura (F1)

| Ref | Hallazgo | Sev. | Estado | Evidencia / nota |
|---|---|---|---|---|
| ARQ-01 | Aislamiento multi-empresa a medio aplicar | Alta | **Cerrado** | 12 `Empresa.objects.first()` → `empresa_actual(request)`; filtro de empresa en precios, etiquetas, ajuste y actividad. Lo fija `core/test_arquitectura.py`. Excepción documentada: comandos de `manage.py` (no hay `request`). |
| ARQ-02 | Dependencias circulares resueltas con imports en funciones | Alta | **Abierto** | *Decisión deliberada de no tocarlo ahora* — ver "Lo que NO se hizo". |
| ARQ-03 | SQLite dentro de OneDrive | Crítica | **Cerrado** | PostgreSQL desde el 28/07; `Iniciar_AllPetCR_ERP.bat` aborta sin `POSTGRES_HOST`. |
| ARQ-04 | Respaldos sin cifrar en carpeta sincronizada | Media | **Parcial** | `respaldar` avisa si el destino está en OneDrive/Dropbox y sugiere `ALLPETCR_RESPALDOS`. **Falta el cifrado** (requiere `pyzipper`) y mover el destino por defecto. |
| ARQ-05 | Puente ERP → web es un comando manual | Media | **Abierto** | Es una decisión de producto (API del catálogo), no un defecto. |
| ARQ-06 / ARQ-07 | Datos ficticios, cédula falsa, enlaces rotos | Crítica/Alta | **No aplica (ERP)** | Son del sitio web. |

### Backend y base de datos (F2)

| Ref | Hallazgo | Sev. | Estado | Evidencia / nota |
|---|---|---|---|---|
| BE-01 | Amplificación de auditoría: 13 filas y 66 consultas por venta | Crítica | **Cerrado** | Señales conectadas por `sender`; líneas de detalle fuera de `AUDITED`; `antes` guarda solo lo que cambió. **Medido: 12→7 filas (−41%), 66→61 consultas.** `core/test_costo_auditoria.py`. |
| BE-02 | DoS en etiquetas (207 MB por petición) | Crítica | **Cerrado** | `TOPE_ETIQUETAS = 500` en `inventario/views.py`. |
| BE-03 | `except Exception: pass` que oculta fallos | Alta | **Cerrado** | Los 5 puntos ahora registran en el log. Lo fija `test_arquitectura.ExcepcionesSilenciosasTest`. |
| BE-04 | Reconciliación sin ejecución ni alerta automática | Alta | **Parcial** | El resultado se guarda (`ChequeoIntegridad`) y el dashboard avisa si hay descuadres **o si nadie lo corre hace más de 7 días**. **Falta programar la tarea** en Windows. |
| BE-05 | Numeración de asientos se autocorrige con `count()` | Media | **Cerrado** | Ahora siembra con el número más alto emitido; tolera huecos. |
| BE-06 | Reportes que iteran en Python | Media | **Cerrado** | `niveles_stock` y `valor_inventario` agregan en la base. Equivalencia demostrada en `core/test_equivalencia_reportes.py` (15 pruebas). |
| BE-07 | El envío de factura devuelve 200 aunque falle | Media | **Cerrado** | 400 sin destinatario, 502 si falla el SMTP. Mensaje en pantalla sin cambios. |
| BE-08 | Sin pruebas en el sitio web | Media | **No aplica (ERP)** | |
| BE-09 | Bodega elegida con `.first()` (supuesto implícito) | Baja | **Cerrado** | Campo `Bodega.principal` + restricción de unicidad + `Bodega.principal_de()`. Migración de datos preserva el comportamiento actual. |

### Seguridad (F3)

| Ref | Hallazgo | Sev. | Estado | Evidencia / nota |
|---|---|---|---|---|
| SEG-01 | El chat entrega costos y márgenes al cajero | Crítica | **Cerrado** | `HERRAMIENTAS_FINANCIERAS` filtra por rol. *Nota: se eligió filtrar herramientas en vez de cerrar el endpoint, para que el cajero conserve la ayuda de navegación. Es una desviación deliberada de la recomendación.* |
| SEG-02 | XSS en el DOM del POS y de compras | Alta | **Cerrado** | `esc()`/`escUrl()` en ambas plantillas; `msg()` usa `textContent`; los chips se crean como nodos. `test_seguridad_cabeceras.EscapeEnPlantillasTest`. **Pendiente: confirmarlo en un navegador real** — la prueba es de código fuente. |
| SEG-03 | Faltan CSP y Permissions-Policy | Alta | **Parcial** | `Permissions-Policy` y las directivas seguras (`frame-ancestors`, `object-src`, `base-uri`, `form-action`) van **en bloqueo**; el resto en **Report-Only**. **Falta** sacar 59 `onclick=` y 9 `<script>` en línea para activar `DJANGO_CSP_ESTRICTA=1`. |
| SEG-04 | Protección de fuerza bruta desactivada por defecto | Alta | **Cerrado** | axes activo salvo que se pida lo contrario; imposible apagarlo en producción. |
| SEG-05 | `X-Forwarded-For` sin validar (IP falsificable) | Alta | **Cerrado** | Solo se confía si viene de `DJANGO_PROXIES_CONFIABLES`, y se lee la **última** entrada. 4 pruebas. |
| SEG-06 | Imágenes base64 sin validar tipo/tamaño | Alta | **Cerrado** | Formato deducido de la firma binaria (rechaza SVG y HTML), tope de 5 MB, nombre generado por el servidor. |
| SEG-07 | Chat sin límite por minuto; historial controlado por el cliente | Media | **Cerrado** | Tope de 6/minuto y el historial se reconstruye desde `ChatMensaje`. |
| SEG-08 | Sin expiración de sesión (2 semanas por defecto) | Media | **Cerrado** | 12 h, renovadas con la actividad. |
| SEG-09 | Datos personales sin cifrar ni política de tratamiento | Media | **Abierto** | Depende de ARQ-04 (cifrado) y de asesoría legal (Ley 8968). |

### Rendimiento (F6)

| Ref | Hallazgo | Sev. | Estado | Evidencia / nota |
|---|---|---|---|---|
| PERF-01 | SQLite no soporta la concurrencia necesaria | Crítica | **Cerrado** | PostgreSQL (ver ARQ-03). |
| PERF-02 | La auditoría "triplica" el costo de cada venta | Alta | **Cerrado** | Ver BE-01. **Corrección al informe:** la auditoría aportaba ~15 de 66 consultas (~23%), no la mayoría. El problema real era el crecimiento de la tabla, no la latencia. Índices añadidos en `AuditLog`. |
| PERF-03 | Sin capa de caché | Media | **Cerrado** | Indicadores del dashboard cacheados 2 min con `LocMemCache`. Las alertas de integridad **no** se cachean, a propósito. |
| PERF-04 | Imágenes del sitio sin optimizar | Media | **No aplica (ERP)** | |
| PERF-05 | Sin monitoreo ni alertas en producción | Media | **Abierto** | Requiere decisión: cuenta de Sentry o equivalente. |

---

## Hallazgos que NO estaban en la auditoría

Aparecieron al verificar el código el 28/07.

| Ref | Hallazgo | Sev. | Estado |
|---|---|---|---|
| NEW-01 | **`anthropic` no estaba en `requirements.txt`** y `core/views.py` lo importa al arrancar. El despliegue en el VPS habría fallado en el primer arranque. | Alta | **Cerrado** |
| NEW-02 | **El respaldo dejó de funcionar al migrar a PostgreSQL.** `respaldar` solo soportaba SQLite y abortaba con error. El último respaldo era del **27/07**: el negocio quedó sin copias nuevas desde la migración. | **Crítica** | **Cerrado** — `pg_dump`/`pg_restore` con formato custom; `restaurar` valida que el respaldo corresponda al motor actual. |
| NEW-03 | La **primera venta de una empresa** genera 15 filas extra de auditoría al sembrar el plan de cuentas. No es un defecto, pero distorsiona cualquier medición de rendimiento que no lo tenga en cuenta. | Info | Documentado en `test_costo_auditoria.py` |
| NEW-04 | La cédula `3-102-999999` figura como "dato real del negocio" en la documentación del proyecto, pero termina en `999999`, igual que la `3-101-999999` que el auditor marcó como falsa en el sitio. **Hay que confirmar la cédula jurídica real.** | Alta | **Abierto — requiere dato del negocio** |
| NEW-05 | La caché del dashboard contaminaba pruebas entre sí: Django no limpia `LocMemCache` entre tests, y una prueba leía los indicadores cacheados por otra. Producía fallos que dependían del orden de ejecución. | Media | **Cerrado** — `DummyCache` durante `manage.py test`. |

---

## Lo que NO se hizo, y por qué

**ARQ-02 (romper los ciclos de dependencia).** La recomendación es mover el
modelo `Consecutivo` de `ventas` a `core`. Eso implica una migración de modelo
sobre una base con datos reales de producción, y el beneficio es de
mantenibilidad futura, no de corrección: hoy no causa ningún fallo. Cambiar de
lugar la tabla que numera facturas y asientos, el mismo día que se migró de
motor de base de datos y se tocaron otros quince puntos del sistema, concentra
demasiado riesgo. **Recomendación: hacerlo solo, en su propia sesión, con un
respaldo restaurado y verificado antes.**

**Cifrado de respaldos (parte de ARQ-04).** Requiere `pyzipper` (dependencia
nueva) y decidir dónde vive la contraseña — si se pierde, el respaldo es
inútil, que es peor que tenerlo sin cifrar. Es una decisión operativa, no
técnica.

**CSP estricta (parte de SEG-03).** Activarla hoy rompería el punto de venta:
59 atributos `onclick=` dejarían de funcionar sin ningún error visible. El
trabajo previo (mover el JavaScript a archivos estáticos) son varios días y no
debe hacerse a la carrera.

**Envío de la factura por WhatsApp (descartado el 29/07/2026).** Se evaluó
agregar un botón junto al de "Enviar por correo". Se descartó entero — no solo
la versión con API, también la manual. Igual que el "sin QR" del template: es
una decisión explícita, no un olvido.

El correo funciona porque el HTML de la factura viaja *dentro* del mensaje.
WhatsApp no permite eso: un enlace `wa.me` solo lleva texto plano, y el
proyecto no tiene generador de PDF instalado (ni `weasyprint` ni `reportlab`),
así que hoy no hay archivo que adjuntar. Mandar un enlace a la factura tampoco
sirve: `ALLOWED_HOSTS` es `127.0.0.1,localhost`, el ERP vive en la red local y
el celular del cliente no lo alcanza. Eso además exigiría un token por factura,
porque si no cualquiera cambia el ID en la URL y ve facturas ajenas.

La vía con API oficial (Meta Cloud) tiene tres bloqueos, y el costo por mensaje
es el menor de ellos:

1. **Verificación de negocio.** Meta exige documentación legal real. Choca de
   frente con NEW-04: mientras la cédula jurídica siga sin confirmarse, no pasa
   la verificación. Es previo a cualquier línea de código.
2. **Captura del número.** Un número dentro de la Cloud API deja de funcionar
   en la app normal de WhatsApp. El +506 8856-2992 del pie de la factura es el
   que usa la tienda para atender clientes; meterlo a la API mata ese chat.
   Haría falta una línea nueva.
3. **Plantillas.** Cada texto se aprueba con Meta antes de usarse, y cada
   cambio se re-aprueba.

Sobre el costo, para no re-investigarlo: desde julio 2025 Meta cobra **por
mensaje**, no por conversación. Una factura entra en la categoría *utility*,
cuyo rango global publicado va de USD 0,004 a USD 0,0456 según el país. **No se
encontró la tarifa exacta de Costa Rica** — cae en el bucket "Rest of Latin
America". A 30 facturas diarias, y asumiendo el extremo caro del rango, son
unos USD 20 al mes: irrelevante frente a los tres bloqueos de arriba. Ojo con
una fecha: hasta ahora los mensajes dentro de una ventana de 24 h abierta por
el cliente eran gratis, **pero Meta empieza a cobrarlos el 01/10/2026**.

**Si se retoma:** la opción barata es el enlace `wa.me` con un resumen en texto
(número, fecha, total, medio de pago) que el empleado envía desde su propio
celular. No requiere cuenta verificada, ni número dedicado, ni plantillas, ni
costo recurrente. Se descartó por ahora junto con el resto, pero es lo que
habría que reconsiderar primero — no la API.

---

## Pendientes que dependen de vos, no del código

1. **Confirmar la cédula jurídica real** (NEW-04). Bloquea publicar el sitio.
2. **Programar `manage.py reconciliar`** semanalmente en el Programador de
   tareas de Windows. El dashboard ya avisa si no se corre.
3. **Verificar que `pg_dump` esté en el PATH** y correr `respaldar.bat` una vez
   para confirmar que hay respaldos otra vez (NEW-02).
4. **Probar una restauración completa**, en una base de prueba. Citando al
   auditor: un respaldo que nunca se restauró es una suposición, no un respaldo.
5. **Sacar los respaldos de OneDrive**: definir `ALLPETCR_RESPALDOS` con una
   ruta en un disco externo.
6. **Decidir sobre monitoreo** (PERF-05): Sentry tiene plan gratuito suficiente.
7. **Confirmar SEG-02 en un navegador real**: crear un producto de prueba con
   `<img src=x onerror=alert(1)>` en el nombre, abrir el POS y comprobar que se
   ve como texto y no ejecuta nada. Después borrarlo.

---

## Variables de entorno nuevas

| Variable | Para qué | Valor sugerido |
|---|---|---|
| `DJANGO_PROXIES_CONFIABLES` | IPs del proxy inverso; sin esto no se confía en `X-Forwarded-For` | `127.0.0.1` en el VPS, vacío en local |
| `DJANGO_SESSION_HORAS` | Duración de la sesión | `12` (por defecto) |
| `DJANGO_CSP_ESTRICTA` | Pasa la CSP completa a bloqueo | no definir hasta sacar el JS en línea |
| `CHAT_LIMITE_POR_MINUTO` | Tope de preguntas por minuto | `6` (por defecto) |
| `DASHBOARD_CACHE_SEG` | Vigencia de los indicadores | `120` (por defecto) |
| `PG_DUMP_BIN` / `PG_RESTORE_BIN` | Ruta a los binarios de PostgreSQL si no están en el PATH | — |
| `ALLPETCR_RESPALDOS` | Carpeta de respaldos **fuera** de OneDrive | ej. `D:\RespaldosAllpet` |

---

## Cambio del 16/08/2026 — Inicio del día a día y evidencia de los indicadores

Trabajo hecho fuera de la lista de auditoría, a pedido. **320 pruebas en
verde** (286 previas + 34 nuevas), `check --deploy` limpio en modo producción.
Sin migraciones ni cambios de modelo.

### Qué cambió

| Cambio | Archivos | Por qué |
|---|---|---|
| El Inicio queda solo con datos del día | `templates/core/dashboard.html`, `core/dashboard.py` | Se abre decenas de veces al día desde el mostrador; la ganancia del mes no cambia ninguna decisión del mostrador y sepultaba lo operativo |
| Resumen del mes, Códigos y Reportes pasan a `/admin/` | `core/admin_site.py`, `templates/admin/index.html`, `core/apps.py` | `/admin/` ya era el lugar del trabajo administrativo y ya tenía su botón en el acceso rápido |
| Los 4 KPIs del día se abren y muestran su origen | `core/evidencia.py` + 4 plantillas | Un número que no se puede abrir enseña a desconfiar del número |
| Reposición por velocidad de venta | `core/reposicion.py`, `templates/core/reporte_reposicion.html` | `stock_minimo` tiene `default=2` para todo el catálogo: con 532 productos es inservible |
| Diferencias de arqueo por cajero | `core/arqueo.py`, `templates/core/reporte_arqueo.html` | `cerrar_caja` ya guardaba `diferencia` y nadie la miraba en conjunto |
| El crédito se valida contra los documentos | `ventas/cxc.py` | Ver abajo: era un control que parecía existir y no existía |

### NEW-05 — El crédito se autorizaba contra un valor denormalizado

| Ref | Hallazgo | Sev. | Estado | Evidencia / nota |
|---|---|---|---|---|
| NEW-05 | `validar_credito` usaba `Cliente.saldo` (denormalizado) para decidir si autorizar una venta a crédito, cuando el propio docstring del modelo dice que la fuente de verdad son los documentos CxC. Si `saldo` quedaba por debajo de la deuda real, el sistema aprobaba ventas por encima del límite del cliente y nada lo detectaba hasta la próxima corrida de `reconciliar` — que sigue sin programarse. | Alta | **Cerrado** | `ventas/cxc.py:deuda_real()` calcula desde `DocumentoCxC` pendientes. `ventas/test_credito_documentos.py` (6 pruebas), incluida `test_bloquea_aunque_el_saldo_denormalizado_este_bajo`, que ensucia `saldo` a mano y verifica que igual rechaza. |

Cuando el denormalizado difiere de los documentos, el mensaje de rechazo lo
dice y pide correr `reconciliar`, en vez de sólo rechazar: si no, el cajero ve
un rechazo que "no cuadra" con la ficha del cliente y asume que falló el
sistema.

### Riesgo de permisos, revisado

Al mover el resumen del mes a `/admin/` había que confirmar quién lo ve: el
admin exige `is_staff`, que **no** equivale a gerente. Verificado en el código:
`core/middleware.py` ya cierra `/admin/` a quien no sea gerente, así que el
riesgo estaba cubierto. Se agregó igual un segundo chequeo en
`core/admin_site.py` — si mañana se decide dejar entrar al Contador, la
ganancia y el margen no deberían viajar de regalo con ese cambio.

### Consistencia del asistente de chat

`SYSTEM_PROMPT_CHAT` en `core/views.py` describía el mapa de navegación viejo
("Códigos" y "Reportes" en el Inicio, KPIs del mes en el Inicio). Se actualizó
en el mismo cambio: un asistente que da instrucciones sobre botones que ya no
existen es peor que no tenerlo.

### Límites conocidos, sin tapar

- **Reposición con producto estacional:** el promedio de 60 días no distingue
  diciembre de febrero y va a sugerir de más. Documentado en la pantalla.
- **Reposición con producto que estuvo agotado:** si no había, no se vendió, y
  el promedio sale bajo justo donde más faltó. Se marca (`hubo_quiebre`) pero
  no se corrige solo: corregirlo exige saber cuántos días estuvo en cero.
- **Las pantallas de evidencia no usan la caché del tablero.** El Inicio puede
  mostrar un valor de hasta 2 minutos atrás y el detalle se calcula al
  instante. Cada pantalla informa la hora del cálculo — una diferencia
  explicada es mejor que una coincidencia forzada.
- **Probado contra SQLite, no contra PostgreSQL con datos reales.** Sin
  migraciones ni cambios de modelo, el riesgo es bajo, pero no es lo mismo.

### Variables de entorno nuevas

| Variable | Para qué | Valor por defecto |
|---|---|---|
| `REPOSICION_DIAS_VENTANA` | Días de historial para medir la velocidad de venta | `60` |
| `REPOSICION_DIAS_OBJETIVO` | Días de cobertura que se quieren tener tras reponer | `30` |
| `REPOSICION_DIAS_CRITICOS` | Cobertura por debajo de la cual el producto es crítico | `7` |
| `ARQUEO_DIAS_VENTANA` | Ventana del reporte de diferencias de caja | `30` |
| `ARQUEO_TOLERANCIA` | Diferencia por debajo de la cual un cierre se considera cuadrado | `100` |

---

## Cambio del 16/08/2026 â€” Inicio del dÃ­a a dÃ­a y evidencia de los indicadores

Trabajo hecho fuera de la lista de auditorÃ­a, a pedido. **320 pruebas en
verde** (286 previas + 34 nuevas), `check --deploy` limpio en modo producciÃ³n.
Sin migraciones ni cambios de modelo.

### QuÃ© cambiÃ³

| Cambio | Archivos | Por quÃ© |
|---|---|---|
| El Inicio queda solo con datos del dÃ­a | `templates/core/dashboard.html`, `core/dashboard.py` | Se abre decenas de veces al dÃ­a desde el mostrador; la ganancia del mes no cambia ninguna decisiÃ³n del mostrador y sepultaba lo operativo |
| Resumen del mes, CÃ³digos y Reportes pasan a `/admin/` | `core/admin_site.py`, `templates/admin/index.html`, `core/apps.py` | `/admin/` ya era el lugar del trabajo administrativo y ya tenÃ­a su botÃ³n en el acceso rÃ¡pido |
| Los 4 KPIs del dÃ­a se abren y muestran su origen | `core/evidencia.py` + 4 plantillas | Un nÃºmero que no se puede abrir enseÃ±a a desconfiar del nÃºmero |
| ReposiciÃ³n por velocidad de venta | `core/reposicion.py`, `templates/core/reporte_reposicion.html` | `stock_minimo` tiene `default=2` para todo el catÃ¡logo: con 532 productos es inservible |
| Diferencias de arqueo por cajero | `core/arqueo.py`, `templates/core/reporte_arqueo.html` | `cerrar_caja` ya guardaba `diferencia` y nadie la miraba en conjunto |
| El crÃ©dito se valida contra los documentos | `ventas/cxc.py` | Ver abajo: era un control que parecÃ­a existir y no existÃ­a |

### NEW-05 â€” El crÃ©dito se autorizaba contra un valor denormalizado

| Ref | Hallazgo | Sev. | Estado | Evidencia / nota |
|---|---|---|---|---|
| NEW-05 | `validar_credito` usaba `Cliente.saldo` (denormalizado) para decidir si autorizar una venta a crÃ©dito, cuando el propio docstring del modelo dice que la fuente de verdad son los documentos CxC. Si `saldo` quedaba por debajo de la deuda real, el sistema aprobaba ventas por encima del lÃ­mite del cliente y nada lo detectaba hasta la prÃ³xima corrida de `reconciliar` â€” que sigue sin programarse. | Alta | **Cerrado** | `ventas/cxc.py:deuda_real()` calcula desde `DocumentoCxC` pendientes. `ventas/test_credito_documentos.py` (6 pruebas), incluida `test_bloquea_aunque_el_saldo_denormalizado_este_bajo`, que ensucia `saldo` a mano y verifica que igual rechaza. |

Cuando el denormalizado difiere de los documentos, el mensaje de rechazo lo
dice y pide correr `reconciliar`, en vez de sÃ³lo rechazar: si no, el cajero ve
un rechazo que "no cuadra" con la ficha del cliente y asume que fallÃ³ el
sistema.

### Riesgo de permisos, revisado

Al mover el resumen del mes a `/admin/` habÃ­a que confirmar quiÃ©n lo ve: el
admin exige `is_staff`, que **no** equivale a gerente. Verificado en el cÃ³digo:
`core/middleware.py` ya cierra `/admin/` a quien no sea gerente, asÃ­ que el
riesgo estaba cubierto. Se agregÃ³ igual un segundo chequeo en
`core/admin_site.py` â€” si maÃ±ana se decide dejar entrar al Contador, la
ganancia y el margen no deberÃ­an viajar de regalo con ese cambio.

### Consistencia del asistente de chat

`SYSTEM_PROMPT_CHAT` en `core/views.py` describÃ­a el mapa de navegaciÃ³n viejo
("CÃ³digos" y "Reportes" en el Inicio, KPIs del mes en el Inicio). Se actualizÃ³
en el mismo cambio: un asistente que da instrucciones sobre botones que ya no
existen es peor que no tenerlo.

### LÃ­mites conocidos, sin tapar

- **ReposiciÃ³n con producto estacional:** el promedio de 60 dÃ­as no distingue
  diciembre de febrero y va a sugerir de mÃ¡s. Documentado en la pantalla.
- **ReposiciÃ³n con producto que estuvo agotado:** si no habÃ­a, no se vendiÃ³, y
  el promedio sale bajo justo donde mÃ¡s faltÃ³. Se marca (`hubo_quiebre`) pero
  no se corrige solo: corregirlo exige saber cuÃ¡ntos dÃ­as estuvo en cero.
- **Las pantallas de evidencia no usan la cachÃ© del tablero.** El Inicio puede
  mostrar un valor de hasta 2 minutos atrÃ¡s y el detalle se calcula al
  instante. Cada pantalla informa la hora del cÃ¡lculo â€” una diferencia
  explicada es mejor que una coincidencia forzada.
- **Probado contra SQLite, no contra PostgreSQL con datos reales.** Sin
  migraciones ni cambios de modelo, el riesgo es bajo, pero no es lo mismo.

### Variables de entorno nuevas

| Variable | Para quÃ© | Valor por defecto |
|---|---|---|
| `REPOSICION_DIAS_VENTANA` | DÃ­as de historial para medir la velocidad de venta | `60` |
| `REPOSICION_DIAS_OBJETIVO` | DÃ­as de cobertura que se quieren tener tras reponer | `30` |
| `REPOSICION_DIAS_CRITICOS` | Cobertura por debajo de la cual el producto es crÃ­tico | `7` |
| `ARQUEO_DIAS_VENTANA` | Ventana del reporte de diferencias de caja | `30` |
| `ARQUEO_TOLERANCIA` | Diferencia por debajo de la cual un cierre se considera cuadrado | `100` |


## Cambio del 20/09/2026 — Régimen tradicional y cálculo de ganancia

**Contexto.** El contador le confirmó a Francisco que AllPetCR es **régimen
tradicional desde el primer día**, no simplificado. `Empresa.regimen` sigue en
`RTS` en la base: se cambia a mano desde el admin (Empresa → régimen) cuando
esta entrega esté desplegada. Los precios actuales **no** se pensaron con IVA
incluido: esa decisión de precios es de Oscar y no se tocó ningún precio.

### Corregido
- **Ganancia en la ficha de precio** (`templates/catalogo/precio_producto.html`):
  mostraba precio + costo − 1 porque el filtro `add` sumaba el costo. Con
  precio ₡5.300 y costo ₡2.000 decía ₡7.299. Ahora sale de
  `Producto.ganancia_unitaria`.
- **Margen, markup y ganancia sin IVA** (`catalogo/models.py`): en tradicional
  se calculan sobre `precio_sin_iva`; antes contaban el IVA de Hacienda como
  ganancia. En simplificado no cambia nada (`precio_sin_iva` = precio).
- **Producto sin tarifa** (`ventas/services.py::_desglose_fiscal`): usaba 0 %;
  ahora la general, `TARIFA_GENERAL_IVA` = 13 %. La migración
  `catalogo/0007` asigna 13 % a todos los productos sin tarifa. Verificado en
  el catálogo CABYS oficial: comida para perros y gatos, arneses, correas,
  ropa e higiene para mascotas llevan 13 %.
- **Piso de venta bajo costo**: se mide sin IVA. Antes, en tradicional, dejaba
  pasar ventas que perdían plata.
- **Resumen del mes** (`core/dashboard.py::_resultado_periodo`): ventas y
  ganancia sin IVA; resta las devoluciones parciales; "vs mes anterior"
  compara los mismos días (1 al N) y no 30 días completos.
- **Textos legales**: tiquete (HTML y térmico) y recibo a color ya no dicen
  "Régimen de Tributación Simplificada" si la empresa no lo es. Siguen
  diciendo que no son comprobante electrónico, porque todavía no lo son.

Pruebas nuevas: `catalogo/test_ganancia_iva.py`, `core/test_resultado_mes.py`,
`ventas.tests.VentaEnRegimenTradicional`.

### Precios nuevos con IVA (aprobados por Oscar el 20/09/2026)
Oscar aprobó la "versión Medio" del plan de precios: cada precio ya trae el
IVA, subido según el precio del chino y terminado en precio bonito
(`catalogo/precios_bonitos.py`). Mediana +25 % sobre el precio anterior.
Se aplica con `APLICAR_PRECIOS_IVA.bat` →
`manage.py aplicar_precios_iva --excel data/PRECIOS_NUEVOS_IVA.xlsx`, que en
UNA transacción cambia los precios y pasa la empresa a régimen tradicional.
Nunca baja un precio, toma el más alto si un código se repite y se niega a
correr dos veces. Pruebas: `catalogo/test_aplicar_precios_iva.py`.

### Contabilidad del IVA (20/09/2026, noche)
- **IVA acreditable de compras**: `Compra.iva` (migración `compras/0005`) y
  cuenta 1104 "IVA acreditable (crédito fiscal)". Al recibir: Debe Inventario
  (sin IVA) + Debe IVA acreditable / Haber Bancos o CxP (total + IVA). El IVA
  NO entra al costo promedio. La anulación revierte las tres líneas. En
  simplificado se rechaza un IVA > 0.
- **Recibir mercadería**: campo "IVA de la factura" (solo en tradicional),
  subtotal / IVA / total de la factura para comparar con el papel, y la
  calculadora "gan. %" ya suma el IVA al precio y mide la ganancia sin IVA.
- **Reporte de IVA**: en tradicional, la misma dirección
  (`contabilidad:iva_trimestral`) muestra el resumen MENSUAL desde el libro:
  IVA cobrado (cuenta 2401) − IVA acreditable (1104). En simplificado sigue
  el trimestral.
- Pruebas: `compras.tests.IVADeCompras`, `contabilidad.tests.ReporteIVAMensual`.

### Pendiente
1. **Factura electrónica**: `facturacion_electronica` no genera XML, no firma
   ni envía. La llave criptográfica está en trámite; falta también el usuario
   de la API de Hacienda. El CABYS de cada producto ya tiene cómo cargarse
   (21/09/2026): `manage.py asignar_cabys` / `ASIGNAR_CABYS.bat`, por
   categoría, con códigos verificados en Hacienda (`catalogo/cabys.py`);
   deja `data/CABYS_PARA_EL_CONTADOR.xlsx` para que el contador revise.
2. Confirmar con el contador cómo se anotó el costo en "Recibir mercadería"
   (con o sin IVA) y cómo se regularizan las ventas previas.

### Variables de entorno nuevas
- `PIE_TIQUETE_TRADICIONAL` (opcional): pie del tiquete térmico en régimen
  tradicional.

---

## Auditoría del 26/09/2026 — Fase 2 (rama `auditoria-erp-fase2`)

Informe completo: `AUDITORIA_ERP_FASE2.md`. Estado verificado con pruebas en
`*/test_auditoria_2026_09.py`.

| Ref | Hallazgo | Sev. | Estado | Evidencia / nota |
|---|---|---|---|---|
| USU-01 | Repositorio público con copias de la base y Excel con costos | Crítica | **Parcial** | Sacados de Git (siguen en disco) y en `.gitignore`. **Falta (Oscar):** poner el repo en privado, cambiar contraseñas, regenerar la llave de la API y limpiar el historial. |
| VEN-01 | Anular una venta con devolución duplicaba plata e inventario | Crítica | **Cerrado** | `anular_factura` la rechaza; Actividad/Historial esconden el botón. |
| VEN-02 | Doble cobro (F1/F2/F3 y reintentos) | Alta | **Cerrado** | Candado `cobrando` en el POS + `FacturaVenta.clave_pos` única; la repetida no reimprime. |
| VEN-03 | Sin vuelto | Alta | **Cerrado** | Diálogo de efectivo (Enter = exacto); `monto_recibido` y `vuelto` en la factura y en el tiquete. |
| VEN-04 | Sin pago mixto | Alta | **Cerrado** | `PagoVenta` (solo ventas `MIX`); caja, asientos, anulación, devolución (proporcional) y reportes (`ventas/pagos.py`). Crédito no se mezcla, a propósito. |
| VEN-05 | POS no veía productos nuevos ni explicaba el "en 0" | Media | **Cerrado** | `ventas:producto_por_codigo`. |
| VEN-07 | Ayuda decía "descuento en colones" | Baja | **Cerrado** | |
| VEN-08 / FE-04 | La línea no guardaba su tarifa | Media | **Cerrado** | `LineaVenta.tarifa_iva/subtotal/impuesto/cabys` (vacíos en ventas anteriores). |
| TIQ-01 | Hora UTC en el tiquete térmico | Alta | **Cerrado** | `tiquete._hora_local`; la prueba ahora usa una fecha con zona. |
| TIQ-02 | El POS decía "enviado" aunque el agente fallara | Alta | **Cerrado** | `impresion:estado_trabajo`; el POS pregunta ~24 s y avisa. |
| TIQ-03 | Sin reimprimir/enviar tras cobrar ni desde un historial | Media | **Cerrado** | Panel "última venta" en el POS y `ventas:historial` (cajero y gerente, con buscador). |
| TIQ-04 | Tiquete sin cajero, pagos, vuelto ni tarifa | Media | **Cerrado** | Térmico y HTML. |
| TIQ-06 | Correo: "enviado" sin configuración; SMTP posiblemente bloqueado | Media | **Parcial** | 503 claro si no hay correo; envío en JSON desde el POS; `core/correo.py` (Resend por HTTPS) activable con `RESEND_API_KEY`. **Falta (Oscar):** abrir la cuenta y cargar la variable; PDF en el servidor sigue sin Chromium. |
| INV-02 | Productos nuevos con código "NP…" | Alta | **Cerrado** | Reciben EAN-8 interno o el de fábrica. Los "NP…" existentes se convierten desde Inventario → Códigos. |
| INV-03 | Compra en dos transacciones | Media | **Cerrado** | `crear_y_recibir_compra`. El admin (`entrada_view`) no se tocó: es la zona de SEC-003, en pausa. |
| INV-04 | Misma factura de proveedor dos veces | Media | **Cerrado** | `crear_compra` la rechaza (sin contar las anuladas). |
| UX-02 | 16 pruebas de impresión fallaban en la PC de la tienda | Baja | **Cerrado** | Fuerzan el camino del agente. |
| USU-02b | `TRAER_RESPALDOS_NUBE.bat` se caía desde el 14/09 (símbolo ✅ en el registro): bajaba 1 copia por corrida y nunca avisaba de un respaldo atrasado | Alta | **Cerrado** | `PYTHONIOENCODING=utf-8` en el .bat. El respaldo del 26/09 03:03 llegó y está sano. |
| UX-08 | 6 .bat con saltos de línea de Linux en disco ("EM no se reconoce...") | Media | **Cerrado** | CRLF; `test_arquitectura.ArchivosBatConSaltosDeWindows`. |
| INV-01 | Sin carga masiva desde Excel en pantalla | Alta | **Cerrado** | Compras → «Cargar desde Excel» (`compras/carga_masiva.py`): plantilla, vista previa firmada, todo-o-nada, completa sin pisar. |
| INV-05 | Ajuste sin tipo | Media | **Cerrado** | Tipo obligatorio; queda como `[Tipo] motivo` en el kardex (sin migración). |
| INV-07 | Kárdex escondido y sin usuario | Baja | **Cerrado** | Ficha de precio: quién, motivo, saldo y enlace al kárdex completo. |
| INV-08 | Sin etiquetas de la compra recién ingresada | Media | **Cerrado** | `impresion:etiquetas_compra`; se ofrece al registrar y al terminar la carga masiva. |
| INV-09 | Sin escaneo con cámara | Media | **Cerrado** | `static/js/camara.js` (BarcodeDetector) en POS, Recibir y Etiquetas; el botón solo aparece donde el navegador lo soporta. |
| INV-10 | Código de barras repetible | Baja | **Parcial** | Validado en el admin, en Recibir y en la carga masiva. Falta la restricción de base: primero correr `censo_codigos` en producción. |
| INV-06 | Sin vencimientos | Media | **Abierto a propósito** | Solo si venden alimento/medicamento con vencimiento (pregunta 9 del informe). |
| CAJ-01 | Sin exportación a Excel para el contador | Alta | **Cerrado** | `contabilidad:exportar` (`contabilidad/exportar.py`): ventas, detalle, pagos, devoluciones, compras y libro diario; prueba de cuadre ventas = pagos. |
| CAJ-02 | Arqueo solo de efectivo | Media | **Cerrado** | Cierre pide datáfono y SINPE (opcionales); `SesionCaja.tarjeta_*` / `sinpe_*`. |
| CAJ-03 | Una caja por persona sobre un solo cajón | Media | **Cerrado** | Caja compartida (`CAJA_COMPARTIDA`, por defecto sí); cada venta sigue firmada; `cerrada_por`. |
| CAJ-04 | Faltaban reportes por período/categoría y menos vendidos | Media | **Cerrado** | `core:reporte_ventas`. |
| FE-02 / FE-03 | Faltaban datos del emisor y tipo de identificación del cliente | Alta | **Cerrado (datos)** | Campos nuevos en Empresa (admin, bloque propio) y Cliente; cliente rápido desde el POS. Hay que LLENARLOS con el contador. |
| FE-01…09 | Qué falta para emitir | — | **Seguimiento** | Pantalla `contabilidad:preparacion_fe` (Reportes → Control interno). No se emite nada todavía. |

### Variables de entorno nuevas
| Variable | Para qué |
|---|---|
| `RESEND_API_KEY` | Correo por HTTPS en vez de SMTP (TIQ-06) |
| `DEFAULT_FROM_EMAIL` | Remitente, de un dominio verificado en el servicio de correo |
| `CAJA_COMPARTIDA` | `1` (defecto): una caja abierta a la vez, compartida. `0`: una por persona |
