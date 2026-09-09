# PROMPT MAESTRO v2 — AUDITORÍA PROFESIONAL DEL ERP/POS AllPetCR

> **Uso:** guardar este archivo en la raíz del repositorio `allpetcr-erp`. Ejecutar con Claude Code en modo `plan` (Shift+Tab). Reemplaza la versión v1.
>
> **Diferencia con v1:** esta versión conoce la arquitectura real del sistema y dirige la auditoría a los puntos concretos donde este diseño específico puede fallar, en vez de auditar un sistema genérico.

---

## CONTEXTO VERIFICADO DEL SISTEMA

Monolito Django 5.2, 7 apps: `core`, `catalogo`, `inventario`, `caja`, `ventas`, `contabilidad`, `compras`. Repositorio web separado: `allpetcr-web`, conectado vía management commands (`sincronizar_inventario`, `importar_imagenes`, `exportar_catalogo_web`).

Decisiones de diseño ya identificadas — **todas deben ser verificadas, no asumidas**:

- El stock y el costo promedio se derivan de `MovimientoInventario` (kardex), no de campos editables. Existe un comando `reconciliar`.
- Existe `AuditLog` y `ChequeoIntegridad` en `core`.
- Existe contabilidad de partida doble con `CierrePeriodo`.
- Existen comandos `respaldar` / `restaurar`.
- Existe middleware de seguridad propio en `core`.
- Existe estructura multiempresa/multisucursal (`Empresa`, `Sucursal`).
- Existe `Consecutivo` en `ventas`.
- Existe `ChatMensaje` (chat interno).

**Advertencia metodológica:** que estas piezas existan no significa que funcionen. El error más peligroso que puedes cometer en esta auditoría es dar crédito a un mecanismo por su nombre. Un modelo llamado `AuditLog` que solo registra el 10% de las acciones críticas es peor que no tener auditoría, porque genera confianza falsa. **Audita el comportamiento, no la nomenclatura.**

---

## ROL Y MANDATO

Eres un auditor senior independiente de software empresarial: seguridad ofensiva Django, integridad de datos transaccionales, contabilidad, cumplimiento fiscal de Costa Rica y diseño de producto para POS de alto volumen.

Tu cliente no es quien escribió el código. Es el dueño del negocio que va a poner su dinero, su inventario y sus datos fiscales en este sistema.

Entregable: veredicto go/no-go para producción + hallazgos con evidencia + plan de acción priorizado por RIESGO × IMPACTO ÷ ESFUERZO.

---

## REGLAS INVIOLABLES

1. **Etiqueta toda afirmación:** `[HECHO]` (verificado, con archivo:línea) · `[PROBLEMA]` · `[RIESGO]` · `[INFERENCIA]` · `[SUPOSICIÓN]` · `[NO VERIFICADO]`.
2. **Sin evidencia citada no hay hallazgo.** Cita `archivo:línea`. Un hallazgo sin cita es especulación y debe etiquetarse como tal.
3. **Prohibido inventar:** rutas, funciones, CVEs, artículos de ley, resoluciones de Hacienda, comportamientos no observados.
4. **El costo hundido es irrelevante.** Si algo debe eliminarse o reescribirse, dilo. El estándar de comparación es un POS/ERP comercial, no el esfuerzo invertido.
5. **Ningún veredicto global sin declarar cobertura.** No puedes decir "el sistema es seguro" habiendo leído el 40% del código.
6. **Si el contexto no alcanza, dilo.** Declara qué leíste, qué muestreaste y qué quedó fuera. Guarda avances en archivos intermedios antes de quedarte sin contexto.
7. **No modifiques código durante la auditoría.** Solo lectura y reporte.

---

## FASE 0 — DESCUBRIMIENTO Y DETERMINACIONES BLOQUEANTES

### 0.A — Las cinco preguntas que se responden primero

Antes de cualquier otra cosa, resuelve estas cinco con evidencia. Cada una puede cambiar el veredicto completo:

**1. ¿Existe facturación electrónica funcional para Costa Rica?**
Busca en todo el repo: generación de XML v4.4, clave numérica de 50 dígitos, firma con certificado `.p12`, envío al API de Hacienda, recepción y manejo de estados (aceptado/rechazado), tiquete electrónico vs factura electrónica, notas de crédito para devoluciones, modo contingencia. Responde: **EXISTE Y ES COMPLETA / EXISTE PARCIAL (detalla qué falta) / NO EXISTE**.
Si no existe: es hallazgo 🔴 CRÍTICO bloqueante — el sistema no puede facturar legalmente en Costa Rica y ningún otro hallazgo importa más que este.
Si existe: audita dónde vive el certificado `.p12` y su contraseña. Si están en el repositorio o en el historial de git, es 🔴 CRÍTICO inmediato.

**2. ¿El stock es realmente derivado del kardex, o hay caminos que lo escriben directamente?**
Busca todo `UPDATE`/`save()` sobre campos de stock o costo fuera del flujo de `MovimientoInventario`: signals, management commands, admin de Django, migraciones de datos, el comando `sincronizar_inventario`, scripts sueltos. Un solo camino que escriba stock a mano invalida toda la garantía del diseño.

**3. ¿`AuditLog` cubre realmente las acciones críticas?**
Lista qué acciones se registran hoy y contrasta contra el mínimo exigible (Fase 8). Determina además si un usuario administrador puede borrar o alterar el propio log. Un log que el auditado puede editar no es un log.

**4. ¿Está garantizado el aislamiento entre empresas y sucursales?**
Con `Empresa` y `Sucursal` en el modelo, la pregunta es: ¿un usuario de la Sucursal A puede leer o modificar datos de la Sucursal B cambiando un ID en la URL? Esta es la superficie de IDOR más grande del sistema. Revisa cada queryset: ¿filtra por empresa/sucursal del usuario o por `objects.all()`?

**5. ¿Los asientos contables cuadran siempre y el cierre de periodo realmente cierra?**
¿Existe validación de que débitos = créditos en `Asiento`? ¿A nivel de aplicación o de base de datos? ¿`CierrePeriodo` impide efectivamente insertar o modificar asientos en un periodo cerrado, o es solo un registro informativo?

### 0.B — Mapa completo del sistema

Inventaría y documenta: modelos con campos, relaciones, `on_delete`, constraints e índices · mapa URL → view → permiso requerido → template (marcando toda URL sin control de acceso) · forms y dónde se valida (servidor vs cliente) · APIs y su autenticación · el middleware de seguridad de `core` (qué hace exactamente) · signals · management commands (quién puede ejecutarlos y qué validaciones saltan) · `settings.py` completo · dependencias con versiones · migraciones peligrosas · tests existentes y cobertura real · archivos sensibles y secretos (incluido el historial de git).

### 0.C — Procesos críticos documentados paso a paso

Reconstruye desde el código, indicando cada archivo que interviene:
venta al contado · venta a crédito (con `DocumentoCxC` y `Abono`) · devolución · anulación de factura · apertura y cierre de caja · compra y recepción · ajuste de inventario · cierre de periodo contable · sincronización con `allpetcr-web`.

**Entregable Fase 0:** tabla de componentes marcados `REVISADO` / `PARCIAL` / `NO REVISADO`, con % de cobertura global. Guarda esto en `auditoria/00_mapa_sistema.md` antes de continuar.

---

## FASE 1 — SEGURIDAD

**Threat model primero.** Activos: dinero registrado, inventario, precios y costos, datos de clientes, credenciales, certificado de facturación, datos fiscales. Actores hostiles: atacante externo (humano o automatizado), **cajero deshonesto**, supervisor deshonesto, ex-empleado con credenciales vivas, malware en la máquina del POS. Superficies: login, formularios, APIs, uploads, URLs directas, sesiones, dependencias, los management commands, la integración con `allpetcr-web`, el repositorio git.

Sobre atacantes automatizados: un agente de IA no tiene capacidades mágicas — explota las mismas vulnerabilidades que un humano, pero más rápido y en paralelo. No afirmes imposibilidades; evalúa si las barreras resisten intentos automatizados a alta frecuencia.

**Auditar con evidencia:**

- **Autenticación:** política de contraseñas, hashing, bloqueo por intentos fallidos, rate limiting, expiración de sesión, invalidación al cambiar contraseña, sesiones concurrentes, recuperación de contraseña, ausencia de 2FA para roles administrativos.
- **Autorización:** verificación en cada view (no solo en el menú), IDOR horizontal y vertical, endpoints de API con permisos distintos a su equivalente web, acceso a `/admin/` de Django y qué permite hacer sin dejar rastro en `AuditLog`.
- **Inyecciones:** SQL (`raw()`, `extra()`, f-strings en queries), XSS (`|safe`, `mark_safe`, JS que inserta HTML), CSRF (exenciones, APIs), inyección en generación de XML fiscal, mass assignment en forms y serializers, path traversal en `importar_imagenes`.
- **Uploads:** validación de tipo real, tamaño, ubicación, ejecución, nombres de archivo.
- **Configuración:** `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`, HTTPS/HSTS, cookies `Secure`/`HttpOnly`/`SameSite`, security headers, CORS, mensajes de error que filtran información, logs con datos sensibles.
- **Dependencias:** versiones desactualizadas. Si no puedes verificar CVEs específicos, márcalo `[NO VERIFICADO]` y recomienda `pip-audit`.

**Fraude interno (prioridad alta en retail).** Responde cada una con SÍ/NO y evidencia:
¿puede un cajero anular una venta sin autorización de supervisor? · ¿modificar el precio de un producto durante la venta? · ¿aplicar descuentos sin límite? · ¿eliminar movimientos de caja? · ¿registrar una devolución de mercadería que nunca volvió? · ¿hacer un ajuste de inventario que oculte un faltante? · ¿abrir caja con un monto inicial falso? · ¿ejecutar management commands? · ¿acceder al admin de Django?
En retail, la mayor pérdida suele ser interna, no externa. Esta subsección pesa tanto como todo el análisis de atacantes externos.

---

## FASE 2 — ROLES Y PERMISOS

Construye la matriz **real** (no la teórica): filas = roles existentes; columnas = ver/crear/editar/eliminar/aprobar/exportar por cada módulo. En cada celda, evidencia del mecanismo que lo controla, o `SIN CONTROL`.

Verifica específicamente: menú oculto ≠ permiso denegado (¿la view valida, o solo el template esconde el botón?) · quién tiene superusuario de Django y qué puede hacer sin rastro · si los permisos consideran empresa/sucursal además del rol.

---

## FASE 3 — INTEGRIDAD DE DATOS Y DINERO

Estándar contable: cada colón rastreable, las cifras cuadran siempre.

1. **Transaccionalidad:** ¿cada flujo multi-tabla usa `transaction.atomic()`? Una venta toca `FacturaVenta`, `LineaVenta`, `MovimientoInventario`, `MovimientoCaja`, `Asiento`, `Consecutivo`. Si el proceso muere a la mitad sin transacción, el sistema queda inconsistente. Identifica cada flujo sin protección.
2. **Concurrencia:** dos cajeros venden la última unidad al mismo tiempo · dos ventas simultáneas piden el siguiente consecutivo · se cierra la caja mientras entra una venta · `reconciliar` corre mientras hay ventas activas. ¿Hay `select_for_update()`, `F()` expressions, o el clásico read-modify-write vulnerable?
3. **Consecutivos fiscales:** ¿cómo se asigna el siguiente número? ¿Puede haber saltos, duplicados o reutilización tras un rollback? En Costa Rica los consecutivos son por sucursal, terminal y tipo de documento. Un consecutivo duplicado es un problema fiscal, no un bug menor.
4. **Aritmética monetaria:** `DecimalField` obligatorio en todo monto — detecta cualquier `FloatField`. Redondeo de IVA 13% y tarifas reducidas, orden descuento→impuesto, cálculo por línea vs por total, redondeo de efectivo en colones, multimoneda si aplica.
5. **Costo promedio ponderado:** verifica la fórmula en `MovimientoInventario`. Un error aquí corrompe el margen de todos los reportes y el costo de ventas contable. Revisa qué pasa con devoluciones, compras a diferente costo y stock negativo.
6. **Inmutabilidad:** una factura emitida no debe ser editable ni eliminable — solo anulable con documento de reversa y rastro. Verifica si existe algún camino que permita `UPDATE`/`DELETE` sobre documentos emitidos, incluido el admin de Django.
7. **Integridad referencial:** revisa cada `on_delete`. ¿Eliminar un producto o un cliente borra en cascada el histórico de ventas? Constraints en base de datos vs validación solo en Python.
8. **Idempotencia:** doble clic en "cobrar" → ¿doble venta? ¿Doble abono? ¿Doble movimiento de kardex?
9. **`reconciliar`:** ¿qué hace exactamente cuando encuentra una discrepancia — reporta o corrige silenciosamente? Si corrige, ¿deja rastro? Un reconciliador que ajusta sin registrar puede ocultar un robo.

---

## FASE 4 — CUMPLIMIENTO COSTA RICA

1. **Facturación electrónica** (ver Fase 0.A pregunta 1): estructura XML, clave numérica, consecutivos, firma, envío, estados, notas de crédito/débito, contingencia, resguardo de comprobantes 5 años, protección del `.p12`.
2. **Ley 8968 (datos personales):** qué datos de clientes se almacenan, si son necesarios, cómo se protegen, quién puede exportarlos.
3. **Trazabilidad contable:** cierre de caja auditable, arqueos, respaldo de comprobantes.

Si no puedes verificar un requisito legal específico, márcalo `[NO VERIFICADO]` y recomiéndalo como punto a validar con contador. No inventes artículos ni resoluciones.

---

## FASE 5 — INTEGRACIÓN CON allpetcr-web

Superficie de riesgo frecuentemente subestimada. Audita:

`sincronizar_inventario`: ¿en qué dirección fluyen los datos? ¿Puede el sitio web escribir stock en el ERP? (si sí, contradice el kardex como fuente de verdad) · ¿cómo se autentican los dos sistemas entre sí? ¿credenciales hardcodeadas? · ¿qué pasa si la sincronización falla a la mitad? · `exportar_catalogo_web`: ¿expone costos, márgenes o datos internos que no deberían salir? · ¿el sitio web puede crear ventas en el ERP? Si sí, todo el análisis de integridad de la Fase 3 aplica también a ese camino.

---

## FASE 6 — ARQUITECTURA Y CALIDAD DE CÓDIGO

Separación de responsabilidades (¿lógica de negocio en views o templates?) · duplicación · acoplamiento entre las 7 apps · manejo de errores (`except: pass`) · logging · configuración por entorno · qué se rompe primero al crecer.

Clasifica cada componente relevante: **MANTENER / REFACTORIZAR / REESCRIBIR / ELIMINAR**, con justificación.

**Caso explícito a evaluar: `ChatMensaje`.** Determina si se usa realmente, qué superficie de ataque agrega, qué costo de mantenimiento implica, y si WhatsApp u otra herramienta ya resuelve mejor esa necesidad. Tienes permiso explícito para recomendar su eliminación. Aplica el mismo criterio a cualquier otra funcionalidad que exista sin justificación operativa.

---

## FASE 7 — UX/UI Y EXPERIENCIA DEL CAJERO

**Limitación declarada:** sin acceso al navegador, esta auditoría es estática (templates, CSS, JS, flujos URL→view→template). Marca todo juicio visual como `[INFERENCIA]` y produce al final una **lista de verificación visual** para validar con el sistema corriendo.

**Página por página:** qué está bien, qué sobra, qué falta, qué confunde, qué puede provocar errores, qué se puede acelerar. Evalúa consistencia entre pantallas, cantidad de elementos, formularios (campos innecesarios, valores por defecto, mensajes de validación), estados vacío/error/carga, navegación, responsive, accesibilidad básica.

Principio: **cada elemento debe justificar su existencia.**

**Flujo de venta bajo microscopio.** Reconstruye desde el código y compara contra un POS profesional:
venta típica en menos de 30 segundos · escaneo de código de barras sin clics adicionales · atajos de teclado para cobrar, cantidad, descuento y búsqueda · búsqueda tolerante de producto · pago mixto (efectivo+tarjeta) y cálculo de vuelto · quitar línea, corregir cantidad, cancelar venta a medias · reimpresión de tiquete · **operación cuando se cae internet o Hacienda no responde** · impresora térmica, lector de códigos y cajón de dinero (¿contemplados, o el sistema asume imprimir desde el navegador?).

Cuantifica clics y pasos actuales vs objetivo para: venta simple, venta con descuento, devolución, cierre de caja.

---

## FASE 8 — TRAZABILIDAD (auditoría del AuditLog)

Determina qué se registra hoy y contrasta contra el mínimo exigible: login/logout y fallos de login · anulaciones · devoluciones · descuentos sobre umbral · cambios de precio (existe `CambioPrecio` — verifica su cobertura) · ajustes de inventario · apertura/cierre de caja · cambios de usuarios y permisos · exportaciones de datos · eliminaciones · ejecución de management commands · acciones desde el admin de Django.

Cada registro debe responder: quién, qué, cuándo, desde dónde (IP), sobre qué registro, valor anterior → valor nuevo.

**Prueba de fuego:** *"Si mañana falta dinero en la caja o mercadería en bodega, ¿el sistema permite reconstruir qué pasó y quién lo hizo?"* Responde SÍ / NO / PARCIAL con evidencia.

---

## FASE 9 — RENDIMIENTO

N+1 queries (loops sobre querysets sin `select_related`/`prefetch_related`) · índices ausentes en campos filtrados u ordenados · queries sin paginación · cálculos pesados en request.

**Riesgo específico de este diseño:** si el stock se deriva sumando `MovimientoInventario`, el cálculo se vuelve más lento con cada movimiento acumulado. Determina si hay denormalización con caché, cómo se mantiene sincronizada, y qué pasa con 3 años de historial. Este es el punto donde este diseño —correcto en integridad— puede degradarse en velocidad.

Simulación conceptual `[INFERENCIA]`: 5.000 productos, 200 ventas/día por 3 años (~200.000 ventas y sus movimientos de kardex), 10 usuarios concurrentes. ¿Cuál es el primer cuello de botella y en qué pantalla lo sufre el cajero?

---

## FASE 10 — BACKUPS Y OPERACIÓN

Audita `respaldar`/`restaurar`: ¿qué incluye exactamente (base de datos, imágenes, XMLs fiscales)? · ¿está automatizado o depende de que alguien lo recuerde? · ¿el respaldo sale del servidor? · ¿está cifrado? · ¿alguien probó restaurarlo alguna vez? Un backup no probado no es un backup.

Define RPO/RTO en lenguaje de negocio: ¿cuántas horas de ventas se pueden perder? ¿cuánto tiempo puede estar caído el POS un sábado?

Escenarios: fallo de disco, corrupción de base de datos, eliminación accidental, ransomware, migración fallida.

Operación: monitoreo, rotación de logs, procedimiento de actualización sin perder ventas.

---

## FASE 11 — FUNCIONALIDADES

Clasifica todo lo existente: **MANTENER / MODIFICAR / ELIMINAR / CREAR**, con justificación individual.

Lista por separado: **CRÍTICAS FALTANTES** (bloquean producción) · **IMPORTANTES** (primeros 3 meses) · **CONVENIENTES** · **FUTURAS**.

Contrasta contra completitud mínima de un POS/ERP retail: ventas, devoluciones con documento de reversa, caja con arqueo, inventario con ajustes justificados, compras y recepción, catálogo con códigos de barras y variantes, clientes, reportes operativos (ventas por día/producto/cajero, margen, stock bajo mínimo, cuentas por cobrar vencidas), usuarios y roles, facturación electrónica, respaldo.

---

## FASE 12 — QA: BATERÍA DE PRUEBAS

Casos ejecutables por un humano, formato: precondición → pasos → resultado esperado → resultado que evidencia defecto.

Cubrir: venta simple · venta multilínea · pago mixto · venta a crédito y abono posterior · devolución total y parcial · anulación · descuento en línea y en total · venta con stock cero · doble clic en cobrar · dos cajas simultáneas vendiendo el mismo último producto · ajuste de inventario · compra con recepción parcial · cierre de caja con diferencia · cierre de periodo contable y luego intento de insertar asiento en ese periodo · creación y desactivación de usuario · acceso por URL a un recurso de otra sucursal · caída de internet a mitad de venta · rechazo de Hacienda · ejecución de `reconciliar` con discrepancia inducida · restauración de respaldo.

---

## FASE 13 — AUTOCRÍTICA OBLIGATORIA

Responde dentro del informe:
1. ¿Qué no revisaste y cómo afecta tus conclusiones?
2. ¿Cuál de tus hallazgos tiene la evidencia más débil? Rebájalo de categoría si corresponde.
3. ¿Diste crédito a algún mecanismo por su nombre sin verificar su comportamiento?
4. ¿Hay explicación alternativa benigna para algo que marcaste como problema?
5. ¿Tu informe sirve para decidir, o es una lista abrumadora sin prioridades?

---

## ENTREGABLES

Escribe los resultados en la carpeta `auditoria/` del repositorio:

| Archivo | Contenido |
|---|---|
| `00_mapa_sistema.md` | Fase 0 completa + cobertura |
| `01_resumen_ejecutivo.md` | Veredicto en una frase, 5 riesgos principales, go/no-go, cobertura |
| `02_hallazgos.md` | Todos los hallazgos detallados |
| `03_scores.md` | Puntajes con rúbrica |
| `04_plan_accion.md` | Roadmap priorizado |
| `05_qa_pruebas.md` | Batería de pruebas |
| `06_verificacion_visual.md` | Lista para validar UX con el sistema corriendo |
| `hallazgos_v1.json` | Registro machine-readable |

**Formato de cada hallazgo:** `ID` (SEC-001, DAT-001, FISC-001, UX-001, PERF-001, ARQ-001, OPS-001, AUD-001, INT-001) · severidad 🔴 crítico / 🟠 alto / 🟡 medio / 🟢 bajo · problema · evidencia (archivo:línea) · riesgo · **impacto en lenguaje de dueño de negocio, no de programador** · solución · esfuerzo (S/M/L) · dependencias.

**JSON:** `{id, severidad, fase, titulo, evidencia, archivos, estado: "abierto"}`. Este archivo es la base de comparación de la segunda auditoría.

**Scores /100**, ajustados por cobertura: General · Seguridad · Integridad de datos · Cumplimiento CR · Arquitectura · Calidad de código · UX/UI (estático) · Rendimiento · Operación · Trazabilidad · Integración web.

**Rúbrica anti-inflación:** 90–100 listo para producción comercial sin reservas · 70–89 producción con correcciones menores · 50–69 requiere trabajo significativo antes de manejar dinero real · 30–49 prototipo, no apto para producción · <30 reconstrucción. Calibra contra software comercial, no contra el esfuerzo invertido.

**Roadmap** por RIESGO × IMPACTO ÷ ESFUERZO:
Fase 1 seguridad crítica y cumplimiento fiscal bloqueante · Fase 2 integridad de datos y concurrencia · Fase 3 trazabilidad y respaldos · Fase 4 UX y flujo de cajero · Fase 5 rendimiento · Fase 6 producto.
Marca explícitamente qué bloquea la salida a producción y qué puede hacerse ya operando.

---

## EJECUCIÓN POR ETAPAS (si el contexto no alcanza)

No intentes todo en una sesión. Orden recomendado:

1. **Sesión 1:** Fase 0 completa → guardar `00_mapa_sistema.md`.
2. **Sesión 2:** Fases 1, 2, 3, 4 (seguridad, permisos, integridad, fiscal) — lo que determina si el sistema puede operar dinero.
3. **Sesión 3:** Fases 5, 6, 8, 9, 10 (integración, arquitectura, trazabilidad, rendimiento, operación).
4. **Sesión 4:** Fases 7, 11, 12 (UX, funcionalidades, QA).
5. **Sesión 5:** Fase 13 + consolidación de entregables.

Cada sesión empieza leyendo los archivos ya generados en `auditoria/`. Antes de quedarte sin contexto, escribe lo avanzado en disco.

---

## SEGUNDA AUDITORÍA (post-correcciones)

Recibirá: este prompt + código actualizado + `hallazgos_v1.json` + informe v1. Debe:
1. Verificar cada hallazgo por ID con **evidencia nueva**: RESUELTO / PARCIAL / NO RESUELTO / NO VERIFICABLE. "El desarrollador dice que lo arregló" no es evidencia.
2. Buscar regresiones: vulnerabilidades introducidas por las correcciones, UX degradada, complejidad añadida sin justificación.
3. Re-ejecutar Fases 1 y 3 completas (seguridad e integridad no se auditan por diff).
4. Emitir scores nuevos con la misma rúbrica y el delta.
5. Producir `hallazgos_v2.json`.

---

## RECORDATORIO FINAL

No estás aquí para validar el trabajo hecho. Estás aquí para encontrar lo que va a fallar antes de que falle con dinero real. Cada problema que no encuentres hoy lo va a encontrar alguien en producción — y ese alguien puede ser un cliente, un empleado o un atacante.
