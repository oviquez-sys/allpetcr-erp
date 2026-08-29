# Reporte de la noche — 2026-08-28

Se actualiza al cerrar cada bloque, no solo al final. Si esto se corta a
media noche, lo último escrito abajo es hasta dónde llegué.

---

## 1. Alertas — leer esto primero

### 🔴 El repositorio `allpetcr-web` tiene el historial de git corrupto

`git status` y `git log` fallan con `error: bad tree object HEAD`. Con
`git fsck --full` se confirma: los últimos commits locales (`33e988b`,
`78d0c22`, y uno más — `78a1af8a` — que ni siquiera aparece en `git log`)
tienen **árboles y blobs faltantes** en `.git/objects`. No es algo que causé
esta noche: lo encontré al hacer el reconocimiento inicial, antes de tocar
nada.

**Qué NO hice:** no corrí ningún `git reset`, `checkout` ni `commit` en ese
repo. Cualquiera de esos comandos podía perder contenido que solo existe hoy
en el disco (los archivos de trabajo parecen íntegros; lo corrupto es la
base de datos de git, no necesariamente los archivos).

**Qué SÍ hice, para que no se pierda nada más:**
1. Copia completa del repo (con `.git` corrupto y todo) a
   `respaldos/allpetcr-web-copia-completa-2026-08-28/` (fuera del repo,
   834 MB, incluye `node_modules`).
2. `git fetch origin`: confirmé que `origin/main` está sano y su commit más
   reciente (`ca6b320`, "Hero: foto completa en escritorio, sin recorte")
   coincide exactamente con el último commit local bueno. **No se perdió
   nada que ya estuviera empujado a GitHub.**

**Lo que sí está en riesgo:** el contenido de 3-4 commits locales nunca
empujados — según el reflog, dos versiones sucesivas de "foto de gato" y un
ajuste del hero. Si los archivos en el disco reflejan el último intento
("Foto de gato: usar el archivo tal cual lo subió Oscar"), no se perdió el
contenido, solo el historial granular de cómo se llegó ahí.

**Qué necesito de vos antes de tocar este repo:** decidir cómo recuperarlo.
Dos caminos, ninguno lo ejecuté:
- **(A) Aceptar la pérdida de esos 3-4 commits de historial** y crear un
  commit nuevo sobre `origin/main` con el estado actual del disco (rápido,
  bajo riesgo, pierde solo el detalle de "cómo" se hicieron esos cambios de
  foto, no el resultado final si los archivos están bien).
- **(B) Intentar recuperación de objetos** con herramientas más finas
  (`git cat-file`, buscar los blobs faltantes en el `.git` de la copia de
  respaldo, o en algún respaldo de OneDrive si el repo estuvo ahí). Más
  lento, no garantizado.

Por esto, **el Bloque 5 (web) no se tocó esta noche**: la regla del
encargo es trabajar siempre en una rama nueva con un tag de reversa, y no
puedo garantizar ninguna de las dos cosas en un repositorio con la base de
objetos rota.

### 🟡 Discrepancia de cédula jurídica entre ERP y sitio web

`allpetcr-web/lib/negocio.ts` tiene `cedulaJuridica: "3-102-969361"` con un
comentario que dice que proviene de `Empresa.identificacion` en el ERP. En
la base real del ERP, `Empresa.identificacion` está **vacía**. No inventé ni
corregí ningún valor en ninguno de los dos lados — hace falta que confirmes
cuál es la cédula real y la pongas en el ERP (que el propio código señala
como la fuente de verdad).

### 🟡 Régimen fiscal: la empresa real está en RTS, no en régimen tradicional

`core.Empresa.regimen = 'RTS'` en la base real (Régimen de Tributación
Simplificada). El Bloque 4 (factura electrónica v4.4, CABYS, IVA
desglosado) solo tiene sentido si el negocio va a pasar a régimen
tradicional. **No es un descubrimiento inventado por mí**: el propio ERP ya tenía este cambio
previsto en el modelo (`Empresa.Regimen.TRADICIONAL` con el comentario "IVA
+ FE v4.4"), así que no es una tarea inventada — es la pieza que faltaba de
un diseño que ya existía. Lo construyo apagado por defecto, sin tocar el
flujo de venta RTS actual. Confirmame si el plan sigue siendo cambiar de
régimen — si no, lo del Bloque 4 queda listo pero sin usarse.

### Nada más encontrado por ahora en la categoría "parar todo"

`.gitignore` de ambos repos está bien armado (`.env`, `.p12`, `.pem`,
`db.sqlite3`, `/media/`, `/respaldos/` excluidos). No encontré secretos
trackeados en ninguno de los dos historiales (`git ls-files` / `ls-tree` sin
coincidencias de `.env`, `.p12`, `.pem`, `.key`, `secret`, `credential`).

---

## 2. Qué quedó hecho, por bloque

### Bloque 0 — Red de seguridad y reconocimiento

- [x] Dump de PostgreSQL (`respaldos/pre-noche-2026-08-28.dump` +
  `.sql`), restaurado en una base temporal (`allpetcr_verificacion_restore`)
  y verificado por conteo de filas contra la base real
  (`catalogo_producto`, `ventas_facturaventa`, `caja_movimientocaja`,
  `inventario_movimientoinventario`: coinciden exacto). Base temporal
  eliminada después de verificar.
- [x] Tag `antes-noche-2026-08-28` en `allpetcr-erp`, sobre el commit que
  ya estaba en `rediseno-inicio-evidencia`.
- [x] Rama nueva `noche-2026-08-28` (partiendo de `rediseno-inicio-evidencia`,
  **no** de `main` — esa era la rama activa con el trabajo más reciente).
- [x] Cambios sin commitear que ya estaban en el working tree (de una sesión
  anterior: `caja/forms.py`, `caja/views.py`, `ventas/views.py`, varias
  plantillas) se guardaron en un `git stash` con mensaje
  `wip-oscar-pre-noche-2026-08-28` **antes** de crear la rama, para no
  mezclarlos con el trabajo de esta noche. Recuperalos con
  `git stash pop` (o `git stash list` para verlo primero). Los archivos
  sueltos sin trackear (`.claude/`, `_respaldo_20260825_2333/`,
  `_respaldo_previo_claude/`, `_to_delete/`, dos `.md`/`.html`) no se
  tocaron.
- [x] `allpetcr-web`: copia de seguridad completa hecha (ver Alertas). No se
  pudo taggear ni ramificar por la corrupción del git.
- [x] `INVENTARIO.md` escrito.
- [x] Suite de pruebas corrida como línea base: **330 pruebas, todas en
  verde** (`core catalogo inventario`: 185; `ventas caja compras
  contabilidad`: 145).
- [x] Encontrado y corregido un bug real fuera de la lista (ver sección 7):
  el POS calculaba el crédito disponible del cliente restando dos `float`
  en vez de restar en `Decimal`. Corregido con prueba de regresión, suite de
  `ventas` corrida completa después del cambio (92/92 OK).

### Bloque 1 — Modelo de datos y catálogo

- [x] `Producto`: agregados `marca`, `peso_valor` + `peso_unidad` (kg/g/lb/oz/l/ml/unidad),
  `cabys`. `imagen` ya existía (no se tocó su nombre). Migración
  `catalogo/0005_...` aplicada contra la base real.
- [x] `cabys` en texto, vacío por defecto, con validador de 13 dígitos
  numéricos. **No se rellenó ni un solo valor** — queda para que lo cargues
  vos desde el catálogo oficial de Hacienda.
- [x] Almacenamiento de fotos configurable por variable de entorno
  (`MEDIA_STORAGE_BACKEND=s3` + variables `AWS_*`). Nuevo `core/imagenes.py`
  como único punto de lectura/escritura; los tres lugares que escribían
  directo a `MEDIA_ROOT` (`importar_imagenes`, alta rápida de producto en
  compras, y el puente `exportar_catalogo_web`) ahora pasan por ahí. En
  local, sin esas variables, el comportamiento es idéntico a antes.
  `django-storages` agregado a `requirements.txt` (boto3 ya estaba).
- [x] Comando nuevo `cargar_fotos_por_sku`: carga una carpeta de archivos
  nombrados por SKU exacto (distinto de `importar_imagenes`, que extrae
  fotos embebidas del Excel por posición de fila). No pisa fotos existentes
  salvo `--reemplazar`, no adivina coincidencias parciales.
- [x] Comando `reporte_nombres_incompletos`: **corrido contra el catálogo
  real (532 productos)**. Resultado: **0 nombres con abreviaturas tipo
  "R.C.", solo 2 nombres cortos** ("Peluche Pizza", "Peluches Dona" — ninguno
  parece realmente incompleto). El ejemplo de la consigna no representa el
  estado real del catálogo; guardado en
  `reportes/nombres_incompletos_2026-08-28.md`. No se corrigió nada — el
  comando solo lista, según lo pedido.
- [x] Historial de compras por cliente: no existía una pantalla dedicada
  (`Cliente.compras` ya traía el dato vía `FacturaVenta.cliente`, pero
  `estado_cuenta` solo muestra documentos de CxC). Vista nueva
  `ventas:historial_compras`, con las anuladas visibles y marcadas.
- [x] Prueba de regresión del POS: la vista `pos()` (`ventas/views.py`) se
  tocó dos veces esta noche (fix de `disponible` + cambio de
  `url_imagen_producto`). Suite completa corrida al cierre del bloque:
  **334 pruebas, todas en verde** (antes 330; +4 netas de las pruebas
  nuevas). `check --deploy` muestra las 6 advertencias esperadas de modo
  desarrollo (HSTS, SSL, SECRET_KEY corta, cookies) — son las mismas que
  desaparecen con `DJANGO_PRODUCTION=1`, no una regresión introducida hoy.

### Bloque 2 — Pedidos y disponibilidad

- [x] App nueva `pedidos` (separada de `ventas`: un Pedido nace ya pagado,
  con datos de envío que `FacturaVenta` no necesita — ver el porqué largo
  en `pedidos/models.py`).
- [x] `Pedido` con los 5 estados pedidos, transiciones válidas declaradas y
  aplicadas en `pedidos/services.py::cambiar_estado` (no se puede saltar de
  "pago confirmado" a "entregado", ni tocar un pedido ya entregado/cancelado).
- [x] `CambioEstadoPedido`: bitácora con fecha y usuario en cada cambio,
  igual criterio que `CambioPrecio`.
- [x] `ReservaStock`: reserva temporal durante el checkout, **15 minutos**
  (justificado en el modelo: tiempo de sobra para pagar, corto para no
  bloquear un carrito abandonado). Usa `select_for_update()`, el mismo
  patrón de concurrencia que ya usaba `inventario.services`.
  **Prueba de concurrencia real** (`TransactionTestCase` + threads +
  conexiones separadas a PostgreSQL): dos reservas simultáneas de la
  última unidad, solo una gana — corrida 5 veces seguidas sin
  intermitencias.
- [x] `crear_pedido` idempotente por `referencia_pago`, **también bajo
  concurrencia real** (no solo "si lo llamás dos veces seguidas"): un
  índice único parcial en la base + captura de `IntegrityError` con
  savepoint. Un `SELECT` antes del `INSERT` sin esto es una condición de
  carrera clásica — dos webhooks a la vez pasarían el `SELECT` los dos
  antes de que ninguno hubiera insertado nada. Probado con dos hilos
  golpeando `crear_pedido` con la misma `referencia_pago` al mismo tiempo:
  un solo pedido, el stock baja una sola vez.
- [x] `AvisoDisponibilidad`: tabla correo + producto, con restricción única
  para no duplicar el mismo aviso.
- [ ] **Ítem 10 (agotado no se oculta, mantiene su página) — NO
  implementado, es una decisión de negocio que ya estaba tomada en
  sentido contrario.** `catalogo/management/commands/exportar_catalogo_web.py`
  tiene la bandera `SOLO_EN_EXISTENCIA = True`, puesta por vos el
  02/08/2026 a propósito, con el costo documentado en el propio archivo
  (perder el posicionamiento de Google de la página de un agotado). El
  puente actual literalmente NO exporta los agotados al sitio — ni
  ocultos ni con insignia, no existen en el JSON que consume la web. Tu
  pedido de esta noche es lo opuesto a esa decisión. No la cambié
  (el archivo ya trae la instrucción de cómo revertirla: poner la bandera
  en `False`), porque pesar el costo de SEO documentado es tuyo, no mío.
  Decime y lo aplico.
- [x] Prueba de regresión del POS + suite completa al cierre: **356
  pruebas, todas en verde** (334 del Bloque 1 + 22 nuevas de `pedidos`).
  `core/test_arquitectura.py` extendido para que las reglas de
  aislamiento por empresa también cubran la app nueva.

### Bloque 3 — API (Django REST Framework)

- [x] DRF instalado, app nueva `api/` (serializers + vistas, separada de
  `pedidos`/`catalogo` para no mezclar la capa HTTP con el dominio).
- [x] Lectura: catálogo paginado con filtros (`categoria`, `mascota`,
  `marca`, `q`, `disponible`), ficha por SKU, disponibilidad (booleano).
- [x] Escritura: alta de pedido pagado, idempotente por `referencia_pago`
  incluso bajo concurrencia real (reutiliza `pedidos.services.crear_pedido`
  del Bloque 2, no duplica la lógica).
- [x] Consulta de estado de pedido para el cliente: número + teléfono. Con
  el teléfono equivocado responde 404, no 403 — no le confirma a quien
  adivina un número que ese pedido existe.
- [x] Autenticación por token (`rest_framework.authtoken`) en **toda** la
  API — ver la decisión abajo. CORS cerrado por defecto, se habilita con
  `CORS_ALLOWED_ORIGINS` (lista separada por comas). Límite de tasa con las
  throttle classes propias de DRF (`anon` 60/min, `user` 120/min — valores
  de arranque, no medición, mismo criterio que `ReservaStock.PLAZO_MINUTOS`).
- [x] Regla dura del costo: `api/tests.py::CostoNuncaSaleDelERP` revisa la
  **definición** de los serializers (no solo la respuesta de hoy) y falla
  si alguien agrega `costo_promedio`/`margen_pct`/`markup_pct` — y de paso
  cubre que tampoco se exponga el stock exacto.
- [x] 30 pruebas nuevas, todas en verde. Suite completa al cierre: **386
  pruebas, todas en verde**.

**Decisión que tomé por vos:** toda la API pide token, incluida la lectura
del catálogo (no dejé nada como público/`AllowAny`). Razón: dijiste que el
ERP "corre solo en local" — no está pensado para recibir tráfico directo de
un navegador en internet. Mientras eso sea así, la única forma legítima de
llegar a esta API es el backend del sitio web llamándola servidor a
servidor con un token, nunca el navegador del cliente. Si en algún momento
publicás el ERP o ponés un proxy delante, ahí sí tendría sentido abrir la
lectura del catálogo sin token — decilo y lo ajusto.

**Importante para cuando conectes el sitio real:** esta API queda
funcionando y probada, pero **nadie de internet puede llamarla todavía**
porque el ERP no está desplegado (y esta noche no lo iba a desplegar — está
en los límites duros). Conectar el sitio (en Vercel u otro lado) con esta
API va a necesitar que decidas cómo: VPS con el ERP corriendo, un túnel, o
algo intermedio. Es un pendiente de infraestructura, no de código.

*(Bloque 4 en adelante se agrega abajo a medida que cierra.)*

---

## 3. Qué no se pudo hacer y por qué

*(pendiente — se completa a medida que avanza la noche)*

## 4. Decisiones que tomé por vos, con la razón

- **Rama de trabajo desde `rediseno-inicio-evidencia`, no desde `main`**:
  era la rama activa con el trabajo más reciente (incluido el stash). Crear
  la rama desde `main` habría significado perder de vista ese trabajo o
  mezclarlo raro al integrar después.
- **Guardar el WIP preexistente en un stash en vez de commitearlo o
  descartarlo**: no es trabajo mío, no sabía si estaba a medio terminar, y
  mezclarlo con mis commits de esta noche habría hecho imposible revisar
  cada cosa por separado.
- **No tocar `allpetcr-web` en absoluto**: ver alerta arriba.

## 5. Marcadores `PENDIENTE` y qué dato falta

*(pendiente — se completa en el Bloque 1 y 4, que son los que más los usan)*

## 6. Qué necesita un trámite tuyo antes de poder avanzar

- Confirmar la cédula jurídica real (discrepancia arriba).
- Decidir cómo recuperar `allpetcr-web` (opción A o B arriba).
- Confirmar si el plan sigue siendo pasar a régimen tradicional (para saber
  si el Bloque 4 se activa alguna vez o queda solo de reserva).

## 7. Problemas encontrados que no estaban en la lista

- **Bug real de dinero en float, ya corregido**: `ventas/views.py`, vista
  `pos()` — el crédito disponible del cliente (`limite_credito - saldo`) se
  calculaba restando dos `float` ya convertidos, en vez de restar en
  `Decimal` y convertir el resultado. Con ciertos montos (ej. 100000.10 −
  99999.99) el resultado en pantalla podía salir con imprecisión binaria
  (`0.10999999999985448` en vez de `0.11`). Corregido en un commit aparte
  (`fix(ventas): calcular crédito disponible del cliente en Decimal, no en
  float`), con prueba de regresión nueva y la suite de `ventas` completa en
  verde después del cambio.

## 8. Estado de la suite de pruebas

- **Línea base (antes de tocar nada):** 330/330 OK.
- **Después del fix de `disponible`:** `ventas` 92/92 OK (no se volvió a
  correr la suite completa todavía; se hará al cerrar cada bloque).

## 9. Qué recomiendo como primer paso cuando vuelvas

*(pendiente — se completa al final)*
