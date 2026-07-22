# Auditoría técnica — ALLPETCR ERP

**Fecha:** 22 de julio de 2026
**Alcance:** revisión de código real (modelos, servicios, vistas, configuración, migraciones). No es una revisión imaginada: cada hallazgo cita el archivo donde vive.
**Base analizada:** ~2.300 líneas de lógica propia (7 modelos, 7 apps de dominio), 152 pruebas automatizadas en verde.

> **Nota de método (según tus principios):** separo lo que es **hecho verificado** (leído en el código), **inferencia** (deducción razonada), y **estimación** (juicio con incertidumbre). Donde el dato es débil, lo digo. No inventé cifras de benchmarks ni de otros ERP.

---

## 0. Veredicto ejecutivo

Para el contexto real —una tienda de mascotas (una empresa, régimen simplificado, pocas terminales)— este sistema está **notablemente bien construido**. La lógica de dominio (inventario, contabilidad de partida doble, caja, CxC) sigue prácticas que muchos ERP comerciales pequeños **no** respetan: libros inmutables con reversa, transacciones atómicas, bloqueo de filas para concurrencia, y restricciones a nivel de base de datos.

La distancia grande **no** está en la calidad del código actual, sino en el salto de "sistema de una tienda" a "producto ERP multi-empresa/multi-sucursal escalable". Ese salto es de arquitectura, no de limpieza.

**Calificación de arquitectura profesional: 7.5 / 10** (detalle y justificación en §8).
**Nivel de confianza de esta auditoría: Alto** para lo estático (código); **Moderado** para escalabilidad (no hice pruebas de carga reales, son inferencias sobre el patrón de consultas).

---

## 1. Auditoría arquitectónica

### 1.1 Decisiones BIEN tomadas (hechos verificados)

**Libros inmutables con reversa.** El kardex (`inventario/models.py:MovimientoInventario`), los asientos (`contabilidad/models.py:Asiento`), los abonos y las devoluciones no se editan ni se borran: los errores se corrigen con un movimiento inverso. Esto es exactamente cómo funciona la contabilidad seria y como opera SAP/NetSuite. Es la decisión más valiosa del sistema.

**Transacciones atómicas de verdad.** `registrar_venta` (`ventas/services.py:37`) confirma factura + kardex + caja + asiento contable **juntos o nada**, con `@transaction.atomic`. Si el asiento no cuadra, la venta entera se revierte. No hay estados "a medias".

**Concurrencia manejada con bloqueo de fila.** `Consecutivo.tomar` usa `select_for_update` (`ventas/models.py:54`); `registrar_movimiento` bloquea el producto (`inventario/services.py:41`); la venta rebloquea la sesión de caja (`ventas/services.py:48`). Dos cajas nunca reciben el mismo número de factura ni corrompen el stock del mismo producto. Esto es correcto y poco común en sistemas caseros.

**Integridad forzada por la base de datos, no solo por Python.** `CheckConstraint` de stock no negativo, débito-o-crédito exclusivo, cantidades positivas (`contabilidad/models.py:124`, `catalogo/models.py:60`, etc.). Aunque un bug se saltara la validación de la app, la base rechaza el dato inválido.

**Dinero en `Decimal`, nunca `float`.** Todos los montos son `DecimalField`. No hay errores de redondeo de punto flotante en plata. (El POS convierte a `float` solo para mandar al navegador — `ventas/views.py:34` — lo cual es correcto: ahí es solo presentación.)

**Motor fiscal desacoplado.** El régimen (RTS vs tradicional) decide el desglose de impuestos en un solo lugar (`_desglose_fiscal`, `ventas/services.py:28`). No hay tarifas de 13% incrustadas por todo el código. Está preparado para el cambio a facturación electrónica.

**Separación de capas.** `services.py` (lógica de dominio) está separado de `views.py` (HTTP). La lógica de negocio no vive en las vistas. Esto hace el sistema testeable — y de hecho está testeado (152 pruebas).

### 1.2 Qué refactorizaría (por impacto)

| # | Hallazgo | Archivo | Severidad |
|---|----------|---------|-----------|
| A | **`Empresa.objects.first()` incrustado en todos los reportes.** El multi-empresa existe en los modelos (hay FK `empresa`), pero en la práctica el código siempre toma "la primera empresa". Hoy funciona porque hay una sola. | `contabilidad/views.py:19,33,55,...`; `core/dashboard.py` | Media (bloquea multi-empresa real) |
| B | **Stock global por producto, no por bodega/sucursal.** `Producto.stock_actual` es un solo número. El kardex sí registra la bodega, pero el saldo vivo es único. Con 2+ sucursales, no sabés cuánto hay en cada una. | `catalogo/models.py:52` | Media-Alta (bloquea multi-sucursal real) |
| C | **Dashboard con consultas que iteran toda la tabla en Python** (detalle en §4). | `core/dashboard.py:45,67,68` | Alta a escala |
| D | **Propiedades `total_debe`/`total_haber` suman en Python** recorriendo `lineas.all()`. En un listado de muchos asientos, es N+1. | `contabilidad/models.py:65` | Baja-Media |

### 1.3 Riesgos para crecer a cientos de miles de registros

1. **Falta de índices para reportes por fecha (hecho verificado).** El único índice explícito en todo el proyecto es `codigo_barras` (`catalogo/migrations/0001:48`). Django indexa automáticamente las llaves foráneas y los campos `unique`, pero **no** los campos de fecha (`FacturaVenta.creado_en`, `Compra.recibida_en`, `Asiento.fecha`, `MovimientoInventario.fecha`), que son exactamente por donde filtran todos los reportes. A miles de filas no se nota; a millones, cada reporte hace un barrido completo de tabla.

2. **El kardex será la tabla más grande y no tiene índice compuesto `(producto, fecha)`.** Es el patrón exacto de "ver el historial de este producto". Inferencia: a 5M movimientos, la consulta de kardex por producto se vuelve lenta sin ese índice.

3. **Campos denormalizados sin tarea de reconciliación.** `Producto.stock_actual`, `Cliente.saldo`, `Proveedor.saldo` son "cachés" cuya fuente de verdad son los libros. El código los mantiene bien dentro de transacciones, pero no vi un comando que **verifique** periódicamente que el denormalizado siga cuadrando con el libro. A largo plazo, cualquier bug futuro podría desincronizarlos en silencio. (Inferencia — no encontré tal comando; podría existir y no haberlo visto.)

---

## 2. Escalabilidad (respuesta directa a cada escenario)

> Confianza: **Moderada**. Son inferencias sobre el patrón de consultas y las propiedades conocidas de SQLite/PostgreSQL, no pruebas de carga.

| Escenario | ¿Soporta? | Qué habría que hacer |
|-----------|-----------|----------------------|
| **100 usuarios simultáneos** | Sí, con PostgreSQL (no con SQLite) | Ya está listo el switch a PostgreSQL (`config/settings.py:103`). SQLite local no sirve para esto. |
| **1.000 usuarios simultáneos** | No tal cual | Una tienda de mascotas no genera 1.000 concurrentes, pero si fuera producto SaaS: caché (Redis), read-replicas, y quitar el `select_for_update` sobre el producto como cuello de botella (hoy serializa ventas del **mismo** producto; productos distintos no chocan). |
| **10 sucursales** | Parcial | El modelo tiene `Sucursal` y el kardex registra bodega, pero **el stock vivo es global por producto** (hallazgo B). Habría que mover el saldo de stock a nivel bodega (tabla `StockBodega` con índice `(producto, bodega)`). Refactor mediano. |
| **1 millón de productos** | No con el dashboard actual | El dashboard **carga todos los productos a memoria** para calcular stock bajo y valor de inventario (`core/dashboard.py:67-68`). A 1M productos, esa página se cae o tarda muchísimo. Arreglo: mover esos cálculos a la base con `filter(stock_actual__lte=F('stock_minimo'))` y `aggregate`. Esfuerzo bajo, impacto alto. |
| **5 millones de movimientos de inventario** | Con reservas | Funcionaría en PostgreSQL, pero necesita el índice compuesto `(producto, fecha)` y paginación en las vistas de kardex. Sin eso, se degrada. |
| **20 millones de facturas** | Con reservas | PostgreSQL lo aguanta; requiere índices por fecha y particionamiento por año (estrategia estándar) para reportes rápidos. El diseño inmutable ayuda: nunca se hace `UPDATE` masivo. |

**Conclusión de escalabilidad:** el diseño **conceptual** escala (libros inmutables, transacciones limpias). Los **frenos concretos** son tres y todos solucionables: (1) `Empresa.first()`, (2) stock global en vez de por bodega, (3) el dashboard que itera tablas completas. Ninguno es un rediseño de fondo.

---

## 3. Base de datos (ordenado por impacto)

1. **[Alto] Índices de fecha faltantes.** Agregar `db_index=True` o `Meta.indexes` a: `FacturaVenta.creado_en`, `MovimientoInventario.fecha`, `Asiento.fecha`, `Compra.recibida_en`. Impacto directo en todos los reportes. Esfuerzo: una migración pequeña.

2. **[Alto] Índice compuesto en el kardex.** `models.Index(fields=["producto", "fecha"])` en `MovimientoInventario`. Es la consulta más frecuente a futuro.

3. **[Alto] Consultas N+1 y de tabla completa en el dashboard** (ver §4).

4. **[Medio] `total_debe`/`total_haber` como N+1.** Si alguna vista lista muchos asientos y llama esas propiedades, dispara una consulta por asiento. Solución: `annotate` con `Sum` cuando se listen.

5. **[Medio] Índice parcial por estado.** Los reportes filtran `estado="EMI"` / `estado="REC"` constantemente. En PostgreSQL, un índice parcial (`WHERE estado='EMI'`) acelera mucho.

6. **[Bajo] Normalización: está bien.** No vi sobre-normalización ni tablas mal partidas. Los denormalizados (`saldo`, `stock_actual`) son deliberados y están documentados como tales. Correcto.

7. **[Bajo] FKs innecesarias: no encontré.** Las relaciones son todas legítimas. El uso de `PROTECT` en casi todas es la elección correcta para datos contables (evita borrados que dejarían huérfanos los libros).

**Oportunidades de `select_related`/`prefetch_related`:** el código **ya las usa bien** donde importa — `libro_diario` (`prefetch_related("lineas__cuenta")`), `tiquete`, `devolver`, `estado_cuenta`. Esto es señal de un desarrollador que sabe lo que hace. Los faltantes están en el dashboard, no en las vistas transaccionales.

---

## 4. Rendimiento — el dashboard es el punto débil #1

`core/dashboard.py` es la página de inicio y concentra los problemas de rendimiento. Hechos verificados:

- **Línea 45:** `costo_mes = sum((l.costo_unitario * l.cantidad for l in lineas_mes), ...)` — trae **todas** las líneas de venta del mes a memoria y las suma en Python. Debería ser `aggregate(Sum(F('costo_unitario')*F('cantidad')))` en la base.
- **Líneas 50-54:** el gráfico de 7 días hace **8 consultas** separadas (una por día). Debería ser **una** consulta con `TruncDate` + `annotate`.
- **Línea 67:** `stock_bajo = [p for p in productos if p.stock_actual <= p.stock_minimo]` — carga **todos** los productos y filtra en Python. Debería ser `.filter(stock_actual__lte=F('stock_minimo'))`.
- **Línea 68:** `valor_inventario = sum(...)` — de nuevo, itera **todos** los productos en Python. Debería ser un `aggregate` en la base.

**A escala actual (cientos/miles de productos): imperceptible.** A 1M de productos: la home se vuelve el cuello de botella crítico. Es el arreglo de **mayor relación impacto/esfuerzo** de todo el sistema — pocas horas de trabajo, gran diferencia a futuro.

---

## 5. Seguridad (con severidad)

> Confianza: **Alta** para lo que se puede ver estáticamente.

**Lo que está BIEN (hechos verificados):**

- **SQL Injection: sin superficie.** Todo es ORM. El único `execute()` en código propio está en un test y usa consulta parametrizada (`?`). No hay `.raw()`, `.extra()`, ni concatenación de SQL. **Riesgo: nulo.**
- **CSRF: cubierto.** Middleware de CSRF activo (`settings.py:72`); `CSRF_TRUSTED_ORIGINS` configurable en producción.
- **Config de producción endurecida:** en producción se fuerza HTTPS, HSTS (1 año), cookies seguras, `X_FRAME_OPTIONS=DENY`, `nosniff` (`settings.py:34-49`). Y si falta la llave secreta, **el sistema no arranca** (`settings.py:21`) — excelente decisión defensiva.
- **DEBUG imposible de dejar prendido en producción** (`settings.py:29`).
- **Fuerza bruta:** django-axes (5 intentos, bloqueo 1h).
- **Control de acceso por rol:** decorador `rol_requerido` + `staff_member_required` (`core/roles.py:57`), y middleware que cierra `/admin` a no-gerentes (`core/middleware.py:34`). El diseño anti-fraude (el cajero no puede anular/devolver) es una decisión de negocio acertada.
- **Contraseñas:** validadores de Django activos.

**Hallazgos a revisar:**

| Severidad | Hallazgo | Detalle |
|-----------|----------|---------|
| **Media** | **IDOR potencial en documentos por empresa/sucursal.** Vistas como `tiquete`, `anular`, `devolver`, `estado_cuenta`, `abonar` (`ventas/views.py`) hacen `get_object_or_404(pk=...)` sin filtrar por la empresa/sucursal del usuario. Hoy no es explotable (una sola empresa, y todo usuario staff pertenece a ella). Pero **el día que sea multi-empresa**, un usuario de la empresa A podría ver/anular un documento de la empresa B cambiando el ID en la URL. Debe resolverse **antes** de volverse multi-tenant. |
| **Baja** | **`mark_safe` sobre el SVG del código de barras** (`inventario/views.py:79`). El contenido lo genera la librería `python-barcode` a partir de un campo controlado (`codigo_barras`, derivado del SKU). Riesgo real bajo, pero es el tipo de línea que hay que vigilar si algún día el código de barras acepta entrada libre del usuario. |
| **Baja** | **`{{ ventas_ultimos_7|safe }}` en el dashboard** (`dashboard.html:521`). Son números calculados en el servidor, no entrada del usuario. Riesgo bajo. Mejor práctica: usar `json_script` (como ya hacés en el POS, `ventas/views.py:47`). |
| **Baja** | **IP de auditoría confía en `X-Forwarded-For`** (`core/middleware.py:26`). Detrás de nginx bien configurado es correcto; si el proxy no sanea la cabecera, un cliente podría falsear la IP del log de auditoría. Solo afecta el registro, no el control de acceso. |
| **Informativo** | **No hay 2FA.** El propio `PRODUCCION.txt` ya lo reconoce como "siguiente capa recomendada" para cuentas con poder. De acuerdo. |

**No encontré:** credenciales incrustadas en el código, secretos en git (hay `.gitignore` para `.env`), XSS explotable en plantillas de usuario, ni path traversal (las imágenes usan rutas relativas controladas, y en producción las sirve nginx, no Django).

---

## 6. Calidad del código

**Fortalezas:** nombres claros y en español consistente; docstrings que explican **por qué**, no solo qué; funciones cortas; separación services/views; sin código muerto evidente; sin duplicación grave (la lógica de reversa se comparte, no se copia). Para un proyecto de este tamaño, la calidad es alta.

**Mejoras menores:**

- **`from X import Y` dentro de funciones** (imports diferidos) en varios services y en el dashboard. A veces es necesario para evitar imports circulares, pero hay varios que podrían subir al tope del archivo. Cosmético.
- **`_desglose_fiscal` y el manejo de regalías** dentro de `registrar_venta` hacen la función larga (~85 líneas). Es legible, pero se podría extraer el cálculo de una línea a su propia función.
- **Números mágicos fiscales** (`"51"` para costo de ventas, `"2101"` para CxP, `186` salarios) están documentados pero dispersos. A futuro convendría un módulo `constantes_fiscales.py`.
- **Duplicación leve** entre `anular_factura`, `anular_compra` y las devoluciones (todas hacen "movimiento inverso + asiento inverso"). Es aceptable — cada una tiene reglas distintas — pero es candidata a un patrón común si crece.

Ninguno de estos es crítico. No hay archivos gigantes (el más grande es `ventas/models.py` con 216 líneas) ni clases infladas.

---

## 7. Comparación con ERP comerciales (SAP Business One, Odoo, Dynamics 365 BC, NetSuite)

> Confianza: **Moderada**. Describo categorías de módulos que estos ERP tienen de forma estándar; no cito cifras ni features específicas de versión para no inventar.

### 7.1 Qué YA tenés (y a buen nivel)
Ventas/POS, caja con arqueo, compras con costo promedio ponderado, inventario con kardex auditable, contabilidad de partida doble automática, CxC con límite de crédito, cierres de período, reportes fiscales (RTS/IVA trimestral), roles y auditoría. Esto cubre el núcleo transaccional que un ERP para PYME **debe** tener.

### 7.2 Qué te FALTA respecto a esos ERP (lo importante)
- **Cuentas por pagar completas** (el módulo de proveedores existe pero es más delgado que CxC).
- **Multi-bodega/multi-sucursal real** con transferencias y stock por ubicación (hoy es global).
- **Facturación electrónica v4.4** (Hacienda CR) — ya está previsto en el diseño, pero no implementado.
- **Órdenes de compra con aprobación y recepción parcial.**
- **Gestión de clientes/CRM** (seguimiento, no solo saldo).
- **Reportes gerenciales configurables / tablero analítico.**
- **Multi-moneda** (existe el campo, no la lógica de conversión).
- **Nómina / planilla** (área grande, típicamente módulo aparte).
- **API pública / integraciones** (e-commerce, pasarelas de pago).

### 7.3 Qué módulos desarrollar primero (orden recomendado)
1. **Facturación electrónica v4.4** — no es opcional en CR cuando salgás del RTS; es lo que más te acerca a "vendible".
2. **Multi-bodega real** — desbloquea el crecimiento a más de un local.
3. **CxP completo** — cierra el círculo financiero con proveedores.
4. **Reportes/tablero analítico** — lo que un dueño mira todos los días.

### 7.4 Qué esperan los clientes de un ERP moderno en 2026
Acceso web/móvil, facturación electrónica nativa, respaldos en la nube, reportes en tiempo real, permisos finos, y cada vez más: asistentes que respondan preguntas en lenguaje natural sobre el negocio.

### 7.5 Dónde tendría sentido meter IA (con criterio, no por moda)
- **Predicción de reorden de inventario** (cuándo y cuánto comprar, según rotación). Alto valor, datos ya los tenés en el kardex.
- **Detección de anomalías** (ventas/anulaciones fuera de patrón — anti-fraude). Encaja con tu diseño anti-fraude actual.
- **Consulta en lenguaje natural** ("¿cuánto vendí de X el mes pasado?") sobre tus propios datos.
- **Clasificación/limpieza de categorías** (ya tenés `categoria_original` "pendiente de depurar" — caso perfecto).

No recomendaría IA generativa en el núcleo transaccional (facturar, contabilizar): ahí querés determinismo, no probabilidad.

### 7.6 Automatizaciones de mayor valor
Respaldo diario automático (ya casi lo tenés), alertas de stock bajo por WhatsApp/correo, cierre de caja asistido, recordatorios de cobro de CxC, y el monitor de RTS que ya avisa antes de salirte del régimen.

---

## 8. Calificaciones (1-10) y justificación

| Dimensión | Nota | Por qué |
|-----------|------|---------|
| Arquitectura profesional | **7.5** | Patrones de dominio de nivel comercial; frenan solo `Empresa.first()`, stock global y dashboard. |
| Calidad del código | **8.5** | Limpio, documentado, testeado, sin deuda grave. |
| Escalabilidad | **6** | Conceptualmente escala; tres frenos concretos y solucionables. |
| Rendimiento | **6.5** | Vistas transaccionales bien optimizadas; dashboard itera tablas completas. |
| Seguridad | **8** | Config de producción endurecida y RBAC serio; pendiente IDOR multi-tenant y 2FA. |
| Base de datos | **6.5** | Modelado y constraints excelentes; faltan índices de fecha/compuestos. |
| Mantenibilidad | **8.5** | Cualquier desarrollador Django entra rápido; alta cohesión. |
| Pruebas automatizadas | **8** | 152 pruebas de lógica en verde; falta cobertura de UI/carga. |
| **Global** | **7.5** | Producto sólido de una tienda, a un refactor de distancia de "producto ERP". |

---

## 9. Lista priorizada de mejoras

### CRÍTICAS (antes de producción real / antes de multi-empresa)
| Mejora | Impacto | Esfuerzo | Riesgo si no se hace | Prioridad |
|--------|---------|----------|----------------------|-----------|
| Filtrar por empresa/sucursal del usuario en las vistas con `get_object_or_404` (cerrar IDOR) | Alto | Bajo | Fuga de datos entre empresas al volverse multi-tenant | 1 |
| Sacar SQLite de producción → PostgreSQL (ya previsto) | Alto | Bajo | Corrupción/bloqueos con concurrencia real | 2 |
| `python manage.py check --deploy` sin advertencias en el VPS | Alto | Bajo | Config insegura en vivo | 3 |

### IMPORTANTES (primeras semanas en producción)
| Mejora | Impacto | Esfuerzo | Prioridad |
|--------|---------|----------|-----------|
| Optimizar el dashboard (filtros/aggregate en la base) | Alto a escala | Bajo | 4 |
| Índices de fecha + compuesto en kardex | Alto a escala | Bajo | 5 |
| Comando de reconciliación de denormalizados (stock/saldo vs libros) | Medio | Medio | 6 |
| Control de versiones (git) antes de trabajar con tu socio | Alto (proceso) | Bajo | 7 |

### RECOMENDADAS
Stock por bodega real; 2FA para gerentes; `json_script` en vez de `|safe`; extraer constantes fiscales; paginación en vistas de kardex/actividad.

### FUTURAS (camino a ERP comercial)
Facturación electrónica v4.4; CxP completo; multi-moneda; API/integraciones; módulos de IA de §7.5; tablero analítico.

---

## 10. Mirada de inversionista — ¿cuánto falta para un ERP comercial competitivo?

> Esto es **estimación**, no hecho. Confianza: **Baja-Moderada** (depende de decisiones de producto y de un equipo que no conozco).

**Qué estás comprando si sos inversionista:** un núcleo transaccional correcto, auditable y bien probado, hecho por alguien con criterio de ingeniería por encima del promedio del segmento PYME. El valor no es "una tienda funcionando" — es que **los cimientos aguantan** que le construyás encima sin rehacerlo.

**Qué falta para "producto vendible a terceros" (no solo para tu tienda):**
- **Multi-tenant real** (cerrar IDOR + quitar `Empresa.first()`): semanas, no meses.
- **Facturación electrónica CR**: es el mayor bloque de trabajo regulatorio; sin esto no se vende a comercios en régimen tradicional.
- **Multi-bodega + onboarding de clientes nuevos** (crear empresa/sucursales/plan contable por autoservicio).
- **Capa de soporte/operación** (respaldos gestionados, monitoreo, actualizaciones).

**Estimación gruesa de esfuerzo hasta un MVP comercial multi-tenant con FE:** del orden de **varios meses de un desarrollador competente** (rango con alta incertidumbre — podría ser 3-4 meses o el doble según el alcance de facturación electrónica y de multi-bodega). Lo digo con **baja confianza** a propósito: sin definir el alcance exacto, cualquier número más preciso sería inventado.

**La buena noticia:** ninguno de los faltantes exige tirar y rehacer. Es construcción incremental sobre una base sana. Eso, desde la óptica de inversión, es lo que separa un activo de un pasivo técnico.

---

## 11. Roadmap MVP → Enterprise

**Fase 0 — Producción (tu tienda, ahora):** PostgreSQL + `check --deploy` + git + dashboard optimizado + índices. *Ya casi estás aquí.*

**Fase 1 — Endurecimiento (multi-tenant seguro):** cerrar IDOR, quitar `Empresa.first()`, reconciliación de denormalizados, 2FA.

**Fase 2 — Expansión funcional:** facturación electrónica v4.4, multi-bodega real, CxP completo.

**Fase 3 — Producto:** onboarding autoservicio, tablero analítico, API/integraciones.

**Fase 4 — Enterprise:** IA (reorden, anomalías, consulta natural), multi-moneda, particionamiento de tablas grandes, read-replicas.

---

*Auditoría basada en lectura directa del código al 22/07/2026. Los hallazgos citan archivo y línea; las inferencias y estimaciones están marcadas como tales. No se ejecutaron pruebas de carga ni de penetración — esas requieren un entorno dedicado y quedan recomendadas para antes del lanzamiento comercial.*
