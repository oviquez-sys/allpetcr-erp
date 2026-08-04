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
