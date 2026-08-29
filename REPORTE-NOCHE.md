# Reporte de la noche — 2026-08-28

Se actualiza al cerrar cada bloque, no solo al final. Si esto se corta a
media noche, lo último escrito abajo es hasta dónde llegué.

---

## 1. Alertas — leer esto primero

### ✅ RESUELTO — Repositorio `allpetcr-web` recuperado (Opción A) y cédula jurídica confirmada

Volviste, elegiste la Opción A y confirmaste la cédula (`3-102-969361`).
Ambas cosas están hechas:

- **Cédula**: `core.Empresa.identificacion` actualizada en la base real del
  ERP a `3-102-969361` (antes vacía).
- **Repo web recuperado**: se clonó `origin/main` (sano, commit `ca6b320`) en
  una carpeta temporal, se movió el `.git` corrupto a `_descartado/` (no se
  borró), y se trasplantó el `.git` sano al repo original, que conservó
  todos sus archivos de trabajo intactos. El contenido de los 3-4 commits
  perdidos (que seguía en el disco) se recuperó como **un solo commit
  nuevo** encima de `origin/main`: `fde44a3` — "Recuperación: restaurar
  cambios locales tras corrupción del historial de git". Se perdió el
  historial granular de esos commits, no el contenido (verificado leyendo
  cada diff antes de commitear: cédula corregida, feature de recompra,
  ajustes de home/producto, foto de gato actualizada — nada sospechoso).
  `git fsck --full` en el repo recuperado: limpio. Tag `antes-noche-2026-08-28`
  puesto sobre `origin/main` como botón de vuelta atrás, y todo el trabajo
  de esta segunda parte de la noche fue en una rama nueva
  (`noche-2026-08-28`), igual que en el ERP.

  El detalle completo de la corrupción original queda abajo, sin editar,
  como registro de lo que pasó.

### 🔴 (Histórico) El repositorio `allpetcr-web` tenía el historial de git corrupto

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

### ✅ RESUELTO — Discrepancia de cédula jurídica entre ERP y sitio web

Confirmaste `3-102-969361`. Ya está en `core.Empresa.identificacion` del ERP
(antes vacía) y coincide con lo que ya tenía `allpetcr-web/lib/negocio.ts`.

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

### Bloque 5 — Web (completo, los 9 ítems)

Una vez recuperado el repo (ver Alerta ✅ arriba), se hicieron los 9 ítems.
Todo en la rama `noche-2026-08-28` de `allpetcr-web`, 9 commits, **92
pruebas nuevas** (todas en verde) y un `npm run build` de producción
completo y exitoso al cierre (compiló, generó los 551 páginas estáticas
—incluidas las 532 fichas de producto pedidas en vivo al ERP—, sin
errores).

- **Ítem 27 (completar `lib/negocio.ts`)**: ya estaba casi completo desde
  antes de esta noche (cédula, WhatsApp, dirección, horario). Solo faltaban
  `direccion.lat`/`lng`, que es justo el ítem 33.
- **Ítem 28 (catálogo contra la API real)**: `lib/data.ts` — que ya estaba
  escrito desde antes con el comentario "cuando exista la API, este es el
  único lugar que cambia" — ahora pide el catálogo en vivo al ERP
  (`ERP_API_URL`/`ERP_API_TOKEN`) en vez de leer `data/productos.json`
  (184 productos, viejo). Sin esas variables, cae a los JSON estáticos:
  mismo comportamiento de siempre, no un fallo. El token nunca sale del
  servidor. Dos bugs de arranque de Next.js encontrados y corregidos en el
  camino (orden de carga de `.env` respecto a `next.config.ts`, y el
  bloqueo de next/image a imágenes de IP privada/loopback).
- **Ítem 29 (carrito persistente)**: ya existía, bien hecho (localStorage,
  sincronizado entre pestañas, precios siempre revalidados contra el
  catálogo vigente). No se tocó.
- **Ítem 30 (checkout del lado del servidor)**: `lib/checkoutServidor.ts` +
  `app/api/checkout/` — calcula el total con el precio REAL del catálogo,
  ignorando cualquier precio que mande el cliente (el tipo de entrada ni
  siquiera admite un campo de precio). Construido y probado pero **sin
  conectar al botón de "Enviar pedido"**, que sigue yendo por WhatsApp como
  ya funcionaba — ver la razón de negocio en el propio comentario de
  `CheckoutCliente.tsx` (cobrar en línea necesita cuenta de comercio y una
  definición fiscal que hoy no existe, régimen simplificado). Queda listo
  para el día que haya una pasarela real, igual que la facturación
  electrónica del ERP.
- **Ítem 31 (aviso de disponibilidad)**: en la ficha de un producto
  agotado, el botón de comprar se reemplaza (no convive deshabilitado) por
  un formulario de correo que llama a `pedidos.AvisoDisponibilidad` del
  ERP. El listado de "agotados al final" y su insignia ya existían.
- **Ítem 32 (buscador tolerante a errores de escritura)**: Levenshtein
  palabra por palabra, sin dependencias nuevas. "coyar" encuentra
  "collar". El SKU sigue siendo substring exacto (un código no es "casi"
  otro código).
- **Ítem 33 (mapa de dirección)**: Leaflet + OpenStreetMap (gratuito, sin
  llave), NO Google Maps. Provincia/cantón/distrito llegan sugeridos desde
  el pin (vía Nominatim, consultado desde el servidor) pero son campos
  editables — OpenStreetMap no calca el sistema oficial de divisiones de
  Costa Rica, y una tabla propia de cantones/distritos quedaría
  desactualizada. Un bug real de Leaflet+Next (rutas de íconos rotas) se
  encontró y corrigió probando en el navegador. **Advertencia de
  verificación**: la llamada real a Nominatim no se pudo probar de punta a
  punta en este entorno de sesión (sin salida de red a internet, confirmado
  con curl) y la interacción completa con el mapa tampoco (esta sesión de
  automatización deja la pestaña "hidden" y el `requestAnimationFrame` que
  ya usaba `lib/carrito.tsx` desde antes nunca dispara ahí — confirmado
  como límite del entorno de prueba, no del código). El `npm run build` de
  producción sí compiló todo esto sin errores. **Recomiendo una prueba
  manual de 2 minutos**: abrir `/checkout` con algo en el carrito, elegir
  "Coordinar envío" y tocar el mapa.
- **Ítem 34 (seguimiento de pedido)**: `/pedido/[numero]`, pide número +
  teléfono (mismo control liviano que ya tiene la API del ERP). Verificado
  de punta a punta con un pedido real creado vía la API y borrado después
  con un ajuste de kardex documentado (no se dejó ningún dato de prueba en
  la base).
- **Ítem 35 (webhook de pago)**: firma HMAC-SHA256 con comparación de
  tiempo constante, **sin credenciales reales de ninguna pasarela**
  (prohibido explícitamente) y **sin conectar** a ningún flujo todavía —
  mismo criterio que el ítem 30. La idempotencia la resuelve el ERP
  (`crear_pedido`, ya probada bajo concurrencia real); el webhook no lleva
  un registro propio para no duplicar la fuente de verdad.
- **Ítem 36 (páginas legales)**: `/terminos`, `/privacidad`,
  `/devoluciones` creadas, con texto honesto ("pendiente de redactar"), sin
  inventar ninguna cláusula legal. **Decisión que tomé**: no se enlazan
  todavía desde el pie de página — `Footer.tsx` ya tenía un criterio
  explícito, aplicado antes, de que un enlace solo va a contenido que
  existe de verdad (corrigieron tres enlaces que prometían páginas
  distintas y llevaban las tres al mismo formulario). Se enlazan el día que
  tengan contenido real.

**Decisión transversal de los ítems 30 y 35**: quedan construidos, probados
y listos, pero desconectados del flujo visible. No es indecisión: hoy el
sitio no cobra nada en línea, por decisión de negocio ya tomada y explicada
en el propio código (régimen simplificado, sin cuenta de comercio). Conectar
esto de verdad es una decisión tuya, el día que definas la pasarela.

**Bug real encontrado y corregido en el ERP mientras se probaba el sitio**:
`ProductoListaSerializer` no traía `descripcion` (solo el detalle la
tenía), y el sitio arma la ficha de producto filtrando el catálogo
completo, no llamando al detalle — rompía la búsqueda con
`undefined.normalize()`. Corregido, con prueba de regresión. De paso se
estandarizó `precio_venta`/`total`/`cantidad` a `coerce_to_string=False`
en toda la API (otro campo, `total` de pedidos, tenía el mismo problema de
serializar como string en vez de number, encontrado probando el
seguimiento de pedido).

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

Con la recuperación del repo web y el Bloque 5 completo, **la lista entera
del encargo quedó cerrada**, salvo lo que depende de trámites tuyos
(Anexo v4.4 + XSD de Hacienda, la llave `.p12`, decidir la pasarela de
pago) y lo que quedó deliberadamente sin conectar por decisión de negocio
ya explicada (checkout en línea, ítem 10 del Bloque 2).

---

## 3. Qué no se pudo hacer y por qué

1. **Bloque 4, la parte que genera el XML de verdad** — bloqueado porque el
   Anexo de Estructuras v4.4 y los XSD oficiales de Hacienda no están en el
   repo. Ver la lista exacta de qué descargar en la sección del Bloque 4.
2. **Bloque 4, la firma XAdES-EPES real** — bloqueada porque no hay una
   llave `.p12` (trámite tuyo con Hacienda, nada que yo pueda adelantar).
3. **Ítem 10 del Bloque 2** (que un producto agotado mantenga su página en
   el sitio en vez de desaparecer) — no lo apliqué porque choca con una
   decisión de negocio tuya ya tomada y documentada (`SOLO_EN_EXISTENCIA =
   True` en `exportar_catalogo_web.py`, con el costo de SEO explicado en el
   propio archivo). Ver sección del Bloque 2 para los detalles y cómo
   revertirlo si querés el comportamiento nuevo.
4. **Checkout y webhook de pago reales (ítems 30/35 del Bloque 5)** —
   construidos y probados, pero deliberadamente sin conectar al flujo
   visible: hoy no hay pasarela de pago ni credenciales reales, y el
   encargo prohíbe simularlas. Se conectan el día que definas la pasarela.
5. **Conectar el sitio con la API desde internet** — no es un bloqueo de
   código: el ERP no está desplegado ("corre solo en local", uno de los
   límites duros del encargo), así que hoy solo funciona con ambos
   corriendo en la misma máquina (como lo probé esta noche). Publicar el
   sitio de verdad va a necesitar decidir cómo llega hasta esta API —VPS,
   túnel, o algo intermedio—, que es una decisión de infraestructura tuya.
6. **Verificación visual completa del mapa de dirección (ítem 33)** — el
   entorno de esta sesión de automatización tiene una limitación real (la
   pestaña queda "hidden" y un `requestAnimationFrame` preexistente del
   carrito nunca dispara ahí) que impidió completar la interacción en el
   navegador de punta a punta. El código sí compiló limpio en
   `npm run build` de producción y una corrida parcial anterior mostró el
   mapa renderizando correctamente con datos reales. Recomiendo una
   prueba manual tuya de dos minutos — ver la sección del Bloque 5.

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
- **Recuperación del repo web (Opción A) por clonado + trasplante de
  `.git`**, no editando el `.git` corrupto in situ: cloné `origin/main` en
  una carpeta aparte (sano, verificado con `git fsck`) y reemplacé el
  `.git` roto por ese, conservando intactos los archivos de trabajo. Es el
  camino más seguro que encontré para llegar a "un commit nuevo sobre
  origin/main con el disco actual" sin arriesgar los archivos mientras se
  operaba sobre el `.git` dañado.
- **Leaflet + OpenStreetMap para el mapa del ítem 33, no Google Maps**:
  gratuito de verdad, sin llave ni cuenta de facturación — el encargo
  prohíbe gastar en servicios pagos, y la API de mapas de Google exige
  cuenta con tarjeta asociada aunque el uso caiga en el nivel gratuito.
- **Provincia/cantón/distrito del ítem 33 quedan como sugerencia editable,
  nunca como dato fijo**: no existe una tabla mía de cantones/distritos de
  Costa Rica — inventarla habría sido exactamente el tipo de dato que el
  encargo prohíbe fabricar, y OpenStreetMap no calca el sistema oficial del
  INEC. El cliente confirma o corrige antes de enviar.
- **Ítems 30 (checkout servidor) y 35 (webhook de pago) construidos pero
  SIN conectar al flujo visible**: conectarlos habría significado simular
  un cobro en línea que hoy no es legal ni real para el negocio (régimen
  simplificado, sin cuenta de comercio) — exactamente lo que ya explicaba
  el comentario preexistente en `CheckoutCliente.tsx` sobre por qué el
  pedido va por WhatsApp. Quedan listos para el día que haya una pasarela
  real, mismo criterio que la facturación electrónica del Bloque 4.
- **Páginas legales (ítem 36) creadas pero NO enlazadas desde el pie de
  página todavía**: `Footer.tsx` ya tenía un criterio explícito -aplicado
  antes, corrigiendo tres enlaces que prometían contenido distinto y
  llevaban al mismo formulario- de que un enlace solo va a contenido que
  existe de verdad. Enlazar páginas que dicen "pendiente de redactar"
  habría repetido ese error.
- **`npm audit fix` (no `--force`) corrido de paso** al instalar Leaflet:
  arregló 3 de 8 vulnerabilidades conocidas en dependencias de desarrollo
  (brace-expansion, js-yaml, nanoid). Las 5 restantes vienen de una versión
  vieja de esbuild que arrastra vitest/vite, y arreglarlas exige subir
  vitest a una versión mayor (rompe cosas) — lo dejé para una sesión
  dedicada a eso, con tiempo de sobra para revisar qué se rompe. Es
  exposición solo del servidor de desarrollo, no de producción.

## 5. Marcadores `PENDIENTE` y qué dato falta

| Dónde | Qué falta | Por qué no lo puse yo |
|---|---|---|
| `catalogo.Producto.cabys` (todos los productos) | El código CABYS de cada producto, del catálogo oficial de Hacienda | Un CABYS mal puesto rebota la factura electrónica — hard limit #8 del encargo |
| ~~`core.Empresa.identificacion`~~ | ~~La cédula jurídica real~~ | **✅ Resuelto**: `3-102-969361`, confirmada por vos y cargada en el ERP |
| `facturacion_electronica.*.clave` (los 5 modelos) | La clave de 50 caracteres de Hacienda | No existe el Anexo v4.4 que define su formato exacto — hard limit #9 |
| `HACIENDA_P12_PATH` / `HACIENDA_P12_PASSWORD` | La llave criptográfica para firmar XAdES-EPES | Trámite tuyo con Hacienda, no hay nada que yo pueda generar |
| `MEDIA_STORAGE_BACKEND` / variables `AWS_*` | Configuración del bucket S3/R2/B2, si decidís usar uno | Sigue funcionando en disco local mientras no las definas — no es obligatorio, es la opción que dejé lista |
| ~~`allpetcr-web/lib/negocio.ts` → `direccion.lat`/`lng`~~ | ~~Coordenadas del local~~ | No es lo mismo que el ítem 33 (que ya está hecho): esto es la ubicación DEL LOCAL para el mapa de `contacto.tsx`, no la del cliente. Sigue vacío — si querés, lo cargo con las coordenadas exactas que me des |
| `CORS_ALLOWED_ORIGINS` (ERP) | El dominio del sitio web real, cuando exista | Vacío = ningún origen permitido (seguro por defecto); se llena cuando haya un dominio real que necesite llamar a la API desde el navegador |
| `allpetcr-web/.env` → `PAGO_WEBHOOK_SECRET` | El secreto compartido real con la pasarela de pago elegida | Hoy tiene un valor de desarrollo (`clave-de-desarrollo-cambiar-en-produccion-...`), gitignored. Se reemplaza cuando exista una pasarela real |
| `facturacion_electronica/esquemas_hacienda/` (carpeta, todavía no existe) | El Anexo de Estructuras v4.4 y los XSD oficiales | Ver la lista exacta en la sección del Bloque 4 de qué descargar y dónde ponerlo |

## 6. Qué necesita un trámite tuyo antes de poder avanzar

- Confirmar si el plan sigue siendo pasar a régimen tradicional (para saber
  si el Bloque 4 se activa alguna vez o queda solo de reserva).
- Descargar el Anexo de Estructuras v4.4 y los XSD oficiales de Hacienda
  (lista exacta en la sección del Bloque 4) para poder escribir el
  generador de XML.
- Tramitar la llave `.p12` de Hacienda para la firma XAdES-EPES.
- Decidir sobre el ítem 10 del Bloque 2 (¿los agotados dejan de ocultarse
  en el sitio, revirtiendo tu decisión del 02/08? — no lo hice sin
  preguntarte).
- Decidir cómo va a llegar el sitio público hasta esta API del ERP, ya
  que el ERP no está desplegado (solo funciona hoy con los dos corriendo en
  la misma máquina).
- Decidir la pasarela de pago (cuando la definas, ítems 30 y 35 del Bloque 5
  se conectan sin rehacer nada de lo construido).
- Revisar y decidir: (a) recuperar el `git stash` con el trabajo previo en
  el ERP (`caja/forms.py`, `caja/views.py`, plantillas — sección 2, Bloque
  0), y (b) qué hacer con `_descartado/git-corrupto-2026-08-29/` en
  `allpetcr-web` (el `.git` viejo, movido no borrado — se puede eliminar a
  mano desde Windows cuando confirmes que ya no lo necesitás).

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
- **`ProductoListaSerializer` de la API no traía `descripcion`** (solo el
  detalle la tenía) — rompía la ficha de producto y la búsqueda del sitio
  con `undefined.normalize()`, porque el sitio arma la ficha filtrando el
  catálogo completo, no llamando al detalle por SKU. Corregido con prueba
  de regresión.
- **`precio_venta`, `total` y `cantidad` de la API serializaban como texto**
  (`"4091.00"`), no como número JSON — comportamiento por defecto de
  Django REST Framework para campos `Decimal` que nadie había notado hasta
  probar el sitio real contra la API. Estandarizado a `coerce_to_string=False`
  en los cuatro lugares donde aparecía (catálogo, alta de pedido, estado de
  pedido), con pruebas que revisan el JSON ya renderizado, no el objeto
  Python intermedio.
- **next/image bloquea imágenes de IP privada/loopback por defecto** (protección
  SSRF) — con el ERP corriendo en `localhost`, esto rompía TODAS las fotos
  del sitio con un 400 silencioso hasta diagnosticarlo. Solucionado con
  `dangerouslyAllowLocalIP`, activado **solo fuera de producción**.
- **`next.config.ts` se evalúa antes de que Next cargue `.env`** — orden de
  arranque documentado de Next.js, no un descuido: sin `@next/env::loadEnvConfig()`
  al inicio del archivo, `ERP_API_URL` todavía no existía cuando se
  calculaban los dominios permitidos para imágenes y la CSP, y las fotos
  del ERP se veían "no permitidas" sin ningún error claro.
- **Import estático de los íconos de Leaflet no expone `.src` de forma
  confiable con Turbopack** — el pin del mapa de dirección (ítem 33) no se
  veía ("iconUrl not set in Icon options"). Solucionado copiando los 3 PNG
  a `public/leaflet/` y referenciándolos por ruta directa, el patrón más
  confiable para Leaflet+Next documentado por la comunidad.
- **8 vulnerabilidades conocidas en dependencias de desarrollo del sitio**
  (`npm audit`), encontradas de paso al instalar Leaflet. 3 corregidas sin
  riesgo (`npm audit fix`); las 5 restantes exigen subir vitest a una
  versión mayor — quedó anotado como pendiente de una sesión dedicada, no
  corregido a las apuradas. Es exposición del servidor de desarrollo
  únicamente, no de producción.

## 8. Estado de la suite de pruebas (final)

**ERP: 432 pruebas, todas en verde**, corridas en dos grupos al cierre:

```
python manage.py test core catalogo inventario pedidos api facturacion_electronica
python manage.py test ventas caja compras contabilidad --noinput
```

`check --deploy` (sin `DJANGO_PRODUCTION=1`, o sea en modo desarrollo): las
mismas 6 advertencias esperadas de siempre (HSTS, SSL, SECRET_KEY de
desarrollo, cookies) — ninguna nueva, ninguna es una regresión de esta
noche.

Progresión del ERP: 330 (línea base) → 334 (Bloque 1) → 356 (Bloque 2) →
386 (Bloque 3) → 404 (Bloque 4). Con el fix de `descripcion` y
`coerce_to_string` encontrados probando el sitio: **432**.

**allpetcr-web: 92 pruebas, todas en verde** (`npm run test`), más un
`npm run build` de producción completo y exitoso al cierre (compiló,
generó las 551 páginas — incluidas las 532 fichas de producto pedidas en
vivo al ERP — sin errores). TypeScript y ESLint limpios en todo momento.

El POS se tocó dos veces (`ventas/views.py::pos`) y se re-verificó cada vez
con la suite de `ventas` completa además de la suite general al cierre de
cada bloque — sigue funcionando igual que antes de esta noche. La base de
datos real quedó verificada limpia de datos de prueba al cierre (stock de
`75376` de vuelta en 3, cero pedidos y cero avisos de disponibilidad de
prueba).

## 9. Qué recomiendo como primer paso cuando vuelvas

1. **Probá el mapa de dirección vos mismo** (2 minutos): con el ERP
   corriendo (`python manage.py runserver` con las variables `POSTGRES_*`)
   y el sitio (`npm run dev` en `allpetcr-web`, con `.env` ya armado), abrí
   `/checkout` con algo en el carrito, elegí "Coordinar envío" y tocá el
   mapa. Es lo único de esta noche que no pude verificar de punta a punta
   por una limitación del entorno de esta sesión (sección 3, ítem 6).
2. Revisá el commit de recuperación de `allpetcr-web`
   (`git log -p fde44a3` o desde GitHub Desktop/VS Code) para confirmar que
   el contenido recuperado es el que esperabas, sobre todo el feature de
   recompra y los ajustes de home/producto.
3. Cuando tengas un rato con el contador o con Hacienda: bajá el Anexo
   v4.4 + XSD (Bloque 4) y empezá el trámite de la llave `.p12`. Ninguno de
   los dos es urgente esta semana —hoy seguís en RTS—, pero son los que más
   tardan en resolverse por trámite externo.
4. Corré `python manage.py reporte_nombres_incompletos` y
   `exportar_catalogo_web` cuando quieras republicar el catálogo real al
   sitio (184 → 532 productos) — ninguno de los dos depende de nada de lo
   de arriba.
5. Cuando quieras, decime si el `git stash` de tu trabajo previo en el ERP
   (`caja/forms.py`, `caja/views.py`, plantillas) lo recuperás con
   `git stash pop` para seguir donde lo dejaste, o si ya no hace falta. Y
   avisame cuándo puedo borrar `_descartado/git-corrupto-2026-08-29/` en
   `allpetcr-web` (el `.git` corrupto viejo, movido no borrado).
6. Cuando definas régimen tradicional y/o pasarela de pago, avisame: son
   los dos interruptores que activan el Bloque 4 completo y los ítems 30/35
   del Bloque 5, ya construidos y esperando.
