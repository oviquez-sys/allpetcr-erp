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

### Bloque 4 — Facturación electrónica

**Busqué el Anexo de Estructuras v4.4 y los XSD oficiales en TODO el
proyecto (los dos repos y toda la carpeta `AllPet`), no solo en el ERP. No
están.** Por lo tanto, siguiendo la instrucción del encargo: **no escribí
ningún generador de XML.** Lo que sí se construyó:

- [x] 5 modelos (`FacturaElectronica`, `TiqueteElectronico`,
  `NotaCreditoElectronica`, `NotaDebitoElectronica`,
  `ReciboElectronicoPago`) sobre una base común. `clave` y `numero_interno`
  como **texto**, nunca entero.
- [x] `clave` queda **vacía a propósito**: no inventé su formato de 50
  caracteres sin el Anexo delante (hard limit #9 del encargo).
- [x] `numero_interno` sí se numera de verdad — es el consecutivo INTERNO
  del ERP, no el consecutivo de 20 dígitos que Hacienda exige incrustado en
  la clave (esa estructura tampoco se inventó). Reutiliza
  `ventas.Consecutivo`, y quedó **probado con 20 hilos reales pidiendo
  consecutivo al mismo tiempo: ninguno se repite** (ítem 23, corrido 4
  veces seguidas sin fallos).
- [x] Punto de conexión para la firma XAdES-EPES
  (`facturacion_electronica/services.py::firmar_xades_epes`): lee
  `HACIENDA_P12_PATH` / `HACIENDA_P12_PASSWORD` del entorno y avisa con
  claridad si faltan, en vez de fallar con un traceback oscuro. No firma
  nada de verdad todavía (no hay XML que firmar).
- [x] Envío asíncrono real **en sus estados**: un comprobante `ENVIADO` NO
  es válido (`comprobante.valido` es `False`) hasta que
  `registrar_respuesta_hacienda()` lo marca `ACEPTADO`. Reintentos con
  tope de 5 y estado `ERROR_ENVIO` al agotarse — probado.
- [x] Conservación de XML con el mismo `default_storage` configurable del
  Bloque 1 (local ahora, S3-compatible después sin tocar código).
- [x] 18 pruebas + la de concurrencia, todas en verde. Suite completa al
  cierre: **404 pruebas, todas en verde.**

**Bug real que encontré y corregí en el camino:** la primera versión de
`enviar_a_hacienda()` guardaba el estado `ERROR_ENVIO` y lanzaba la
excepción de reintentos agotados TODO dentro del mismo
`transaction.atomic()` — lanzar la excepción revertía también el guardado,
así que el comprobante quedaba en `ENVIADO` aunque el mensaje dijera que se
había agotado. Lo detectó una prueba que falló, no lo vi a ojo. Corregido:
el guardado sale de un `with transaction.atomic()` que cierra limpio antes
de lanzar el error.

#### Lo que necesito que hagas vos antes de que esto se pueda terminar

1. **Descargar del sitio de Hacienda** (Ministerio de Hacienda, Factura
   Electrónica, versión 4.4 — el que mencionaste con la actualización del
   22/04/2026, obligatoria desde el 1/11/2026):
   - El **Anexo de Estructuras de comprobantes electrónicos v4.4** (documento
     técnico que define cada campo, tipo de dato, tamaño y estructura de la
     clave/consecutivo — es lo que hace falta para no inventar nada de esto).
   - Los **XSD oficiales** de cada tipo de comprobante: factura, tiquete,
     nota de crédito, nota de débito, mensaje de recepción, y el del REP
     (Recibo Electrónico de Pago).
2. **Ponerlos en el ERP** en una carpeta nueva, por ejemplo
   `facturacion_electronica/esquemas_hacienda/` (no existe todavía — la
   creo yo cuando lleguen los archivos, o la creás vos y avisás). Con eso
   ahí, la próxima sesión puede escribir el generador de XML y validarlo
   contra el XSD en la misma prueba automatizada, como pide el encargo.
3. **La llave criptográfica (.p12)** para la firma XAdES-EPES — la tenés
   que tramitar vos con Hacienda; no hay nada que yo pueda hacer al
   respecto. Cuando la tengas, se configura por `HACIENDA_P12_PATH` y
   `HACIENDA_P12_PASSWORD` (variables de entorno, nunca en el repo).
4. Confirmar si el plan sigue siendo pasar a régimen tradicional (ver
   alerta al principio de este reporte) — si no, todo este bloque queda
   construido pero sin activarse nunca.

### Bloque 5 — Web

**No se tocó nada.** Depende del Bloque 3 (listo), pero el repositorio
`allpetcr-web` tiene el git corrupto (ver Alerta 🔴 arriba) y la regla del
encargo es trabajar siempre en una rama nueva con tag de reversa — no lo
puedo garantizar ahí. Además, aunque el git estuviera sano, la API de esta
noche no es alcanzable desde internet (el ERP corre solo en local), así que
conectar el sitio real requiere primero una decisión de infraestructura
tuya.

Reconocimiento igual hecho (sin tocar código), y con hallazgos que cambian
lo que pensabas del estado del sitio:
- `lib/negocio.ts` **no tiene marcadores `PENDIENTE` activos** — está casi
  completo (cédula, WhatsApp, dirección, horario). Solo faltan
  `direccion.lat`/`lng` (que es justo el ítem 33) y las redes sociales
  (vacías, no bloqueante).
- Ya existen `app/carrito`, `app/checkout`, `app/catalogo`,
  `app/producto/[sku]`, `app/contacto`, `app/sobre-nosotros`,
  `app/recompra`. **No existen las páginas legales** (términos, privacidad,
  devoluciones) — sigue siendo un pendiente real.
- `data/productos.json` tiene 184 productos; el ERP ya tiene 532 — hay que
  correr `exportar_catalogo_web` de nuevo (esto ya estaba anotado en el
  propio `CLAUDE.md` del ERP, no es un hallazgo nuevo).

### Bloque 6 — Si sobra tiempo

Los dos ítems de este bloque **ya estaban hechos antes de esta noche**;
verificado, no asumido:

- [x] Ítem 37 (estilo de `abrir.html`, `cerrar.html`, `ajuste.html`,
  `precios.html`, `estado_cuenta.html`): los cinco archivos ya tienen el
  mismo sistema de diseño (mismas variables CSS, misma paleta, mismos
  radios y sombras) que el resto de pantallas del ERP. No hay nada
  descuidado que corregir.
- [x] Ítem 38 (llenar `mascota` donde se deduzca con seguridad): los 532
  productos activos **ya tienen `mascota` cargada** (261 Perro, 174 Perro y
  gato, 70 Gato, 24 Peces, 2 Otros, 1 Tortugas — cero vacíos). No hay nada
  que completar ni que listar como dudoso.

Con esto, **la lista completa de la noche quedó cerrada** salvo el Bloque 5
(bloqueado por el git corrupto de `allpetcr-web`, no por falta de tiempo).

---

## 3. Qué no se pudo hacer y por qué

1. **Bloque 5 completo (web)** — bloqueado por el git corrupto de
   `allpetcr-web`. Ver Alerta 🔴 al principio y el detalle en la sección del
   Bloque 5. No es falta de tiempo: es que no puedo cumplir la regla de
   "rama nueva + tag de reversa" en un repositorio cuya base de objetos
   está rota, y tocar código ahí sin esa red de seguridad va contra la
   regla madre del encargo.
2. **Bloque 4, la parte que genera el XML de verdad** — bloqueado porque el
   Anexo de Estructuras v4.4 y los XSD oficiales de Hacienda no están en el
   repo. Ver la lista exacta de qué descargar en la sección del Bloque 4.
3. **Bloque 4, la firma XAdES-EPES real** — bloqueada porque no hay una
   llave `.p12` (trámite tuyo con Hacienda, nada que yo pueda adelantar).
4. **Ítem 10 del Bloque 2** (que un producto agotado mantenga su página en
   el sitio en vez de desaparecer) — no lo apliqué porque choca con una
   decisión de negocio tuya ya tomada y documentada (`SOLO_EN_EXISTENCIA =
   True` en `exportar_catalogo_web.py`, con el costo de SEO explicado en el
   propio archivo). Ver sección del Bloque 2 para los detalles y cómo
   revertirlo si querés el comportamiento nuevo.
5. **Conectar el sitio real con la API de esta noche** — no es un bloqueo
   de código, es que el ERP no está desplegado ("corre solo en local", uno
   de los límites duros del encargo) y por lo tanto no hay forma de que un
   sitio en internet lo llame todavía. Es un pendiente de infraestructura.

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
- **App nueva `pedidos` separada de `ventas`**, en vez de agregarle campos a
  `FacturaVenta`: un pedido en línea nace ya pagado y con datos de envío que
  una venta de mostrador no tiene ni necesita. Mezclarlos habría obligado a
  llenar campos irrelevantes de un lado o del otro.
- **`ReservaStock` con plazo de 15 minutos**: valor de arranque razonado
  (ver `pedidos/models.py`), no una medición. Ajustable en una sola
  constante si en producción resulta corto o largo.
- **Toda la API pide token, incluida la lectura del catálogo**: ver el
  detalle en la sección del Bloque 3. Es la lectura más estricta de "el ERP
  corre solo en local, no lo iba a desplegar" — avisame si querés algo más
  abierto.
- **Reutilicé mecanismos existentes en vez de crear nuevos** donde ya
  resolvían exactamente el mismo problema: `ventas.Consecutivo` para la
  numeración de pedidos y de comprobantes electrónicos, y
  `ventas.services._desglose_fiscal` para el IVA de los pedidos web. Menos
  código nuevo, y la regla de "el impuesto se calcula en una sola función"
  se sostiene sin esfuerzo extra.
- **No implementé una tarea programada para limpiar `ReservaStock` vencidas**:
  `reservar_stock` ya las descarta de oficio cada vez que alguien reserva
  ese mismo producto (ver el servicio), así que la corrección es automática
  aunque no haya un barrido periódico. Un `manage.py` dedicado sería una
  mejora de housekeeping, no una necesidad de corrección — lo dejé fuera
  para no inflar el bloque con algo que no pedías.

## 5. Marcadores `PENDIENTE` y qué dato falta

| Dónde | Qué falta | Por qué no lo puse yo |
|---|---|---|
| `catalogo.Producto.cabys` (todos los productos) | El código CABYS de cada producto, del catálogo oficial de Hacienda | Un CABYS mal puesto rebota la factura electrónica — hard limit #8 del encargo |
| `core.Empresa.identificacion` | La cédula jurídica real | Está vacía en el ERP; el sitio web tiene `3-102-969361` pero no coincide con lo que dice `HALLAZGOS.md` que se había marcado como sospechoso (terminaba en `999999`) — hace falta que confirmes cuál es la correcta |
| `facturacion_electronica.*.clave` (los 5 modelos) | La clave de 50 caracteres de Hacienda | No existe el Anexo v4.4 que define su formato exacto — hard limit #9 |
| `HACIENDA_P12_PATH` / `HACIENDA_P12_PASSWORD` | La llave criptográfica para firmar XAdES-EPES | Trámite tuyo con Hacienda, no hay nada que yo pueda generar |
| `MEDIA_STORAGE_BACKEND` / variables `AWS_*` | Configuración del bucket S3/R2/B2, si decidís usar uno | Sigue funcionando en disco local mientras no las definas — no es obligatorio, es la opción que dejé lista |
| `allpetcr-web/lib/negocio.ts` → `direccion.lat` / `direccion.lng` | Coordenadas del local en el mapa | Es literalmente el ítem 33 del Bloque 5, que no se tocó esta noche (repo bloqueado) |
| `CORS_ALLOWED_ORIGINS` | El dominio del sitio web real, cuando exista | Vacío = ningún origen permitido (seguro por defecto); se llena cuando haya un dominio real que necesite llamar a la API desde el navegador |

## 6. Qué necesita un trámite tuyo antes de poder avanzar

- Confirmar la cédula jurídica real (discrepancia arriba).
- Decidir cómo recuperar `allpetcr-web` (opción A o B arriba).
- Confirmar si el plan sigue siendo pasar a régimen tradicional (para saber
  si el Bloque 4 se activa alguna vez o queda solo de reserva).
- Descargar el Anexo de Estructuras v4.4 y los XSD oficiales de Hacienda
  (lista exacta en la sección del Bloque 4) para poder escribir el
  generador de XML.
- Tramitar la llave `.p12` de Hacienda para la firma XAdES-EPES.
- Decidir sobre el ítem 10 del Bloque 2 (¿los agotados dejan de ocultarse
  en el sitio, revirtiendo tu decisión del 02/08? — no lo hice sin
  preguntarte).
- Decidir cómo va a llegar el sitio público (una vez reparado) hasta esta
  API del ERP, ya que el ERP no está desplegado.

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

## 8. Estado de la suite de pruebas (final)

**404 pruebas, todas en verde**, corridas en dos grupos justo antes de
cerrar esta noche:

```
python manage.py test core catalogo inventario pedidos api facturacion_electronica
python manage.py test ventas caja compras contabilidad --noinput
```

`check --deploy` (sin `DJANGO_PRODUCTION=1`, o sea en modo desarrollo):
las mismas 6 advertencias esperadas de siempre (HSTS, SSL, SECRET_KEY de
desarrollo, cookies) — ninguna nueva, ninguna es una regresión de esta
noche.

Progresión de la noche: 330 (línea base) → 334 (Bloque 1) → 356 (Bloque 2)
→ 386 (Bloque 3) → 404 (Bloque 4).

El POS se tocó dos veces (`ventas/views.py::pos`) y se re-verificó cada
vez con la suite de `ventas` completa además de la suite general al cierre
de cada bloque — sigue funcionando igual que antes de esta noche.

## 9. Qué recomiendo como primer paso cuando vuelvas

1. **Primero, leé la Alerta 🔴 de `allpetcr-web` y decidí cómo recuperarlo**
   (opción A o B, sección 1). Es lo único que de verdad bloquea seguir
   avanzando — todo lo demás de esta noche quedó en un estado consistente
   y sin prisa.
2. **Confirmá la cédula jurídica** (discrepancia ERP/web) — es rápido y
   desbloquea cargarla en `Empresa.identificacion`.
3. Con el repo web resuelto, el Bloque 5 queda listo para arrancar: la API
   del Bloque 3 ya está construida y probada del lado del ERP.
4. Cuando tengas un rato con el contador o con Hacienda: bajá el Anexo
   v4.4 + XSD (Bloque 4) y empezá el trámite de la llave `.p12`. Ninguno de
   los dos es urgente esta semana —hoy seguís en RTS—, pero son los que más
   tardan en resolverse por trámite externo, así que conviene arrancarlos
   temprano si en algún momento vas a pasar a régimen tradicional.
5. Corré `python manage.py reporte_nombres_incompletos` y
   `exportar_catalogo_web` cuando quieras republicar el catálogo real al
   sitio (184 → 532 productos) — ninguno de los dos depende de nada de lo
   de arriba.
6. Cuando quieras, decime si el `git stash` de tu trabajo previo
   (`caja/forms.py`, `caja/views.py`, plantillas) lo recuperás con
   `git stash pop` para seguir donde lo dejaste, o si ya no hace falta.
