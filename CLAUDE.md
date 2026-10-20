# ALLPETCR ERP — contexto del proyecto

> **Este archivo lo lee Claude automáticamente al abrir la carpeta.** Su
> propósito es que una sesión nueva arranque con el contexto correcto sin que
> Oscar tenga que repetirlo ni buscar archivos.

## Antes de proponer cualquier trabajo: leé `HALLAZGOS.md`

**`HALLAZGOS.md` es la fuente de verdad sobre qué está corregido y qué no.**
No los informes de auditoría: esos se escriben una vez y el código sigue
cambiando.

Esto ya pasó dos veces. El 28/07 se perdió tiempo revisando la auditoría del
22/07 cuyos hallazgos ya estaban cerrados, y horas después volvió a pasar con
la auditoría del 28/07: cuatro de sus siete hallazgos críticos se habían
corregido entre que se escribió el informe (10:14) y que se leyó.

**Regla: verificá el estado real en el código antes de "corregir" algo.**
Y al cerrar un hallazgo, actualizá `HALLAZGOS.md` en el mismo commit.

## Auditoría del 26/09/2026 (rama `auditoria-erp-fase2`)

Informe: `AUDITORIA_ERP_FASE2.md` (sección 0 = qué se hizo y qué le toca a Oscar).
Todo el trabajo está en la rama `auditoria-erp-fase2`, **sin publicar** hasta que
Oscar corra `PUBLICAR_AUDITORIA.bat`. 702 pruebas en verde.

- **El repositorio de GitHub es PÚBLICO.** Nunca subir respaldos, `.dump`, `.sql`,
  Excel con costos ni bases de datos (`.gitignore` ya los bloquea). Pendiente de Oscar:
  ponerlo privado, cambiar contraseñas y regenerar el token de la API.
- Pantallas nuevas: `ventas:historial`, `compras:carga_masiva`, `core:reporte_ventas`,
  `contabilidad:exportar`, `contabilidad:preparacion_fe`.
- Pago mixto: el reparto por medio vive SOLO en `ventas/pagos.py`; ningún reporte
  debe agrupar por `FacturaVenta.medio_pago` por su cuenta.
- Caja compartida por defecto (`CAJA_COMPARTIDA`): `caja.services.sesion_abierta_de`
  devuelve la caja abierta aunque la haya abierto otro usuario.
- Comentarios de plantilla de varias líneas: `{% comment %}`, nunca `{# #}`
  (`core/test_arquitectura.ComentariosDePlantilla`).
- **No correr dos `manage.py test` a la vez**: comparten la base `test_allpetcr` y
  uno le borra la base al otro (pasó el 26/09).

## Qué es

ERP interno de AllPetCR, tienda de mascotas en Heredia Central, Costa Rica.
Django 5.2 sobre PostgreSQL. Lo usa el personal de la tienda: punto de venta,
inventario con kardex, caja, ventas, cuentas por cobrar, compras y
contabilidad de partida doble. Además: `pedidos` (pedidos web, reservas de
stock, avisos de disponibilidad), `api` (API REST para el sitio, Django
REST Framework) y `facturacion_electronica` (modelos y flujo v4.4,
apagados hasta que el negocio pase a régimen tradicional — ver abajo).

Hay un **segundo repositorio**, `allpetcr-web` (Next.js 16), que es el sitio
público. El ERP expone una API real (`api/`, desde el 29/08/2026) que el
sitio ya consume en desarrollo; el puente viejo por JSON
(`exportar_catalogo_web`) sigue existiendo como respaldo cuando el ERP no
es alcanzable. Si un hallazgo dice "del sitio web", no es de este repo.

## Estado (29/08/2026)

- **435 pruebas** en verde · `check --deploy` sin advertencias (modo producción)
- **PostgreSQL** (base `allpetcr` en localhost) desde el 28/07/2026
- 532 productos reales en catálogo, con foto, descripción y taxonomía de
  dos niveles — ya aplicado, ya no es "pendiente"
- Régimen fiscal real: **tradicional desde el primer día** (lo confirmó el
  contador el 18-20/09/2026; hasta entonces se creía RTS). Todo lo que vende
  la tienda lleva IVA 13 %. Márgenes y ganancia ya se calculan sin IVA
  (20/09/2026). El IVA de compras (acreditable) y el resumen mensual de
  IVA están hechos; falta la factura electrónica — ver la sección del
  20/09/2026 en `HALLAZGOS.md`.
- Repos en GitHub: `oviquez-sys/allpetcr-erp` y `oviquez-sys/allpetcr-web`
  (este último recuperado de una corrupción de git el 29/08/2026 — ver
  `REPORTE-NOCHE.md`)

## Cómo correrlo

```
acceso-directo/Iniciar_AllPetCR_ERP.bat     # arranca en el puerto 8000
```

Requiere `POSTGRES_HOST` definido; el `.bat` aborta con instrucciones si falta.

**Las pruebas tardan ~90 s en total.** Corrolas en dos grupos para no chocar
con límites de tiempo:

```
python manage.py test core catalogo inventario pedidos api facturacion_electronica
python manage.py test ventas caja compras contabilidad
```

## Cómo correr comandos en la máquina de Oscar (01/09/2026)

Oscar **no es programador**: es administrador de empresas. Hay que hablarle sin
jerga, decidir lo técnico por él y consultarle solo lo del negocio.

Claude puede **leer y escribir** archivos en su computadora, pero **no puede
ejecutar comandos**: el uso de computadora solo concede las terminales en modo
"clic" —se ven, no se puede teclear en ellas—. Se comprobó el 01/09/2026, no
hace falta volver a intentarlo.

El patrón que sí funciona, y que le deja a Oscar un solo doble clic:

1. Escribirle un `.bat` en la carpeta del ERP que corra lo que haga falta y
   redirija **toda** la salida (`>> "%LOG%" 2>&1`) a un `.txt`.
2. Pedirle que le dé doble clic y avise.
3. Leer el `.txt` desde la carpeta.

Ya existen dos, reutilizables: `CORRER_PRUEBAS.bat` (migración + pruebas) y
`VERIFICAR.bat` (estado de la base real, solo lectura).

Los comandos que se le pasen a mano van **con la ruta completa**, listos para
pegar en PowerShell, y usando `.\.venv\Scripts\python.exe` en vez de activar
el entorno (así PowerShell no pide cambiar permisos de scripts):

    cd "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"
    .\.venv\Scripts\python.exe manage.py test compras

**Ojo**: que las pruebas pasen NO prueba que la base real esté migrada —las
pruebas arman su propia base temporal—. Para la base real, `VERIFICAR.bat`.

## Impresoras de la tienda (05/09/2026)

Tres aparatos, y solo dos necesitan código:

| Aparato | Nombre en Windows | Cómo lo usa el ERP |
|---|---|---|
| Etiquetas Xprinter XP-360B (rollo 44,5 × 31,8 mm) | `Xprinter XP-360B` | imagen dibujada con Pillow, enviada **por el driver** |
| Recibos Caysn/Cashino 80 mm | `Caysn 80mm` | ESC/POS **crudo**, corta el papel solo |
| Pistola lectora (USB HJ Scanner) | — | es un teclado; el POS y "Recibir mercadería" ya la aprovechan |
| Gaveta de dinero Dynapos (cable RJ11) | — | va al puerto **DK de la Caysn**, no a la computadora; la abre el pulso `ESC p` |

**Diseño de la etiqueta (09/09/2026).** De arriba abajo: logo AllPetcr.com,
precio en grande, código de barras con su número, descripción corta. Lo eligió
Oscar copiando la etiqueta de fábrica de un proveedor. El reparto vertical es a
mano en `impresion/etiqueta.py` con alturas fijas en milímetros, para que todas
las etiquetas del rollo se vean iguales; la prueba
`test_nada_se_sale_de_la_etiqueta` es la que evita que un cambio de tamaño de
letra empuje la descripción fuera del papel. El logotipo vive ya binarizado en
`impresion/marca/` (la térmica solo imprime negro o nada) y si falta el archivo
la etiqueta sale sin logo en vez de reventar.

**El logo va en los dos.** Vive ya binarizado en `impresion/marca/` y lo carga
`impresion/logotipo.py`, que es el único lugar donde se compone: la etiqueta lo
dibuja dentro de la imagen y el tiquete lo manda como imagen de trama ESC/POS
(`GS v 0`, ver `tiquete.bytes_logo`). Está en un módulo aparte justamente para
que no se separen y un día el logo del recibo deje de ser el de la etiqueta. En
el tiquete se rellena con blanco hasta el ancho del papel en vez de usar
`ESC a 1`, porque no todos los firmwares centran las imágenes. Con
`TIQUETE_LOGO_PUNTOS=0` el recibo vuelve a salir sin logo.

**Gaveta de dinero (19/10/2026).** Pedido de Oscar: que se abra sola con las
ventas en efectivo. Es un electroimán enchufado al puerto DK de la térmica:
Windows no la ve, se prueba con `PROBAR_GAVETA.bat`. El POS antepone
`tiquete.ABRIR_GAVETA` (patillas 2 y 5: no se anotó con cuál abrió) al tiquete
de una venta NUEVA con efectivo o mixta con parte en efectivo
(`ventas.views._entra_efectivo`); la reimpresión y la venta repetida no la
abren. Viaja dentro del mismo trabajo del agente: no hay que rearmar el .exe.
`GAVETA_AUTOMATICA=0` la apaga. Pruebas: `impresion/test_gaveta.py`.

**No volver a intentar comandos crudos con la XP-360B.** El 05/09/2026 se le
mandaron TSPL, ZPL y EPL: no imprimió ninguno. Por el driver imprime perfecto.
La térmica de recibos es al revés: ESC/POS crudo es lo correcto ahí.

Todo vive en `impresion/`, y es el único módulo que habla con Windows
(`impresion/windows.py`). Está aislado a propósito: el día que el ERP se mude
al VPS, el servidor deja de ver el USB de la tienda y habrá que poner un
agente en la caja — ese día se reemplaza ese archivo y nada más.

- `INSTALAR_IMPRESION.bat` — instala pywin32 y Pillow, corre las pruebas y deja
  el diagnóstico en `resultado_impresion.txt`.
- `PROBAR_IMPRESORAS.bat` — saca una prueba en papel de cada impresora.
- `/impresion/estado/` — la misma comprobación desde el navegador (gerente).

## El agente de impresión (10-12/09/2026)

Ese día llegó: el ERP corre en DigitalOcean y el servidor de Nueva York no ve
el USB del mostrador. El ERP ya no imprime: **encola**. `_agente_impresion.py`
corre en la tienda, le pregunta al ERP cada 3 segundos si hay algo y lo manda a
la impresora que tiene al lado.

- El agente pregunta hacia afuera; nadie le abre un puerto a la tienda.
- Es tonto a propósito: recibe bytes y los entrega. El diseño del tiquete y de
  la etiqueta se arma en el servidor, así que cambiarlos no obliga a
  actualizar nada en la tienda.
- Los trabajos **vencen a los 15 minutos** (`IMPRESION_VIGENCIA_MINUTOS`):
  encender la computadora a mediodía no debe escupir los tiquetes de la mañana.
- Se protege con `IMPRESION_AGENTE_TOKEN` (en `_llaves_agente.py`, que NO se
  sube: el repo es público). Sin la variable, las puertas quedan **cerradas**.

**Hay varias computadoras y unas solas impresoras (12/09/2026).** Oscar tiene
la suya, Francisco la suya y más adelante habrá una de un empleado; las
impresoras viven en el mostrador. Por eso el agente manda en cada consulta la
lista de impresoras que esa máquina tiene instaladas y el ERP solo le entrega
los trabajos que puede imprimir de verdad (`cola.tomar_pendientes`). Sin ese
filtro, el agente que Oscar dejó abierto en la casa se llevaba el tiquete de
una venta hecha en la tienda, fallaba, y el cliente se quedaba sin comprobante
sin que nadie entendiera por qué. Con el filtro, el agente se puede instalar en
las tres computadoras sin pensarlo: cada una se lleva solo lo suyo.

Cuidado con un detalle: en esa función `impresoras=[]` (máquina sin ninguna
impresora) tiene que dar cero trabajos y `impresoras=None` (no se mandó la
lista) tiene que darlos todos. Confundirlos revive el problema entero.

**Conectadas, no instaladas (06/10/2026).** En la tienda se usan dos
computadoras en horarios distintos y el cable de las impresoras pasa de una a
otra. Windows deja las colas listadas aunque el cable esté en la otra máquina,
así que la que no lo tenía se llevaba el trabajo y mostraba un error. Ahora el
agente manda `windows.impresoras_conectadas()` (descarta colas «sin conexión»:
atributo 0x400 o estado offline/no disponible; una copia «(Copiar N)» viva
cuenta como la original). Y si igual le toca un trabajo y la impresora no está
(`ImpresoraNoDisponible`), lo devuelve: `resultado` con `devolver=True` →
`cola.reportar` lo pasa a PENDIENTE sin aviso en pantalla. Los agentes viejos
no mandan `devolver` y siguen igual hasta reinstalarlos. Requiere rearmar el
.exe. Pruebas en `impresion/test_dos_computadoras.py`.

- `AGENTE_IMPRESION.bat` — la forma vieja (ventana abierta todo el día). Queda
  solo para diagnosticar a mano.

**Programa instalable, sin .bat (27/09/2026).** `AllPetCR-Impresion.exe`
(PyInstaller, un solo archivo, lleva Python, el agente y la llave). Doble clic
en cualquier computadora con impresoras → se instala en
`%LOCALAPPDATA%\AllPetCR\Impresion`, sin pedir administrador, arranca con
Windows (entrada `Run` de HKCU) y una tarea programada lo relanza cada 10 min
(un mutex evita copias dobles). Corre sin ventana con el logo junto al reloj
(verde conectado / naranja sin conexión) y notifica si un trabajo falla.
Volver a abrir el instalador = actualizar; `--desinstalar` o el menú del icono
lo quitan.

- Código: `_agente_escritorio.py` (instalar, bandeja, arranque) sobre el motor
  `_agente_impresion.py`. Se arma con `CONSTRUIR_AGENTE_IMPRESION.bat` y queda
  en `AllPet\INSTALADORES`, **fuera del repo**: lleva la llave adentro.
- Rearmarlo solo si cambia la llave, la URL o el código del agente; el tiquete
  y la etiqueta se dibujan en el servidor.
- **Avast** revisa HTTPS con su propio certificado raíz, y Python 3.13 lo
  rechazaba (`VERIFY_X509_STRICT`): el agente quedaba «sin conexión» para
  siempre. `_contexto_tls` apaga solo esa exigencia; cadena y nombre se
  siguen verificando. No «arreglarlo» apagando la verificación entera.
- La tarea se crea desde XML: por defecto Windows no la arranca con batería y
  la mata a las 72 h.

## Respaldos, después de la mudanza al servidor (12/09/2026)

Hasta esta fecha los respaldos los sacaba la computadora de Oscar. Eso dejó de
proteger el negocio el día que el ERP se mudó a DigitalOcean: las ventas pasaron
a ocurrir en la base de la nube, y la tarea de su computadora seguía copiando la
base **local** —la vieja— en verde todos los días. Un respaldo que no falla y no
protege es peor que no tener ninguno: da por cubierto lo que no lo está.

Ahora hay tres capas, y cada una cubre lo que la anterior no:

| Capa | Qué protege | Dónde vive | Cuánto dura |
|---|---|---|---|
| Respaldo automático de DigitalOcean | que se caiga la base | misma cuenta | 7 días |
| `manage.py respaldar` en el servidor, diario | borrado por error, mudanza | bucket Spaces, carpeta `respaldos/` | 30 copias |
| `TRAER_RESPALDOS_NUBE.bat` en la tienda, diario | perder la cuenta de DigitalOcean entera | OneDrive de Oscar | 60 copias |

Detalles que no hay que perder:

- El respaldo del servidor va **sin fotos** (`--sin-fotos`): las fotos ya viven
  en el bucket y pesan 130 MB. Lo que cambia todos los días se respalda todos
  los días; lo que cambia poco, poco.
- El zip sube con permiso **privado**. En ese mismo bucket las fotos de producto
  son públicas; el zip lleva ventas, clientes y contabilidad.
- Si el comando corre en el servidor y no hay a dónde mandar la copia, **falla a
  propósito**. El disco del contenedor se borra en cada despliegue: terminar
  "bien" ahí sería mentir.
- `pg_dump` tiene que ser de PostgreSQL **18**, igual que el servidor de base.
  Por eso el Dockerfile agrega el repositorio oficial de PostgreSQL; Debian 12
  solo trae la 15 y pg_dump se niega a volcar una base más nueva que él.
- Backblaze B2 sigue siendo el destino preferido (llave "Write Only" + Object
  Lock: ni un administrador puede borrar lo subido). Si esas variables están
  puestas, gana B2 y el bucket no se usa. Falta abrir la cuenta.
- La tarea de la tienda **falla a propósito** si el respaldo más reciente del
  servidor tiene más de 36 horas, y manda un correo. Es la única señal de que
  el trabajo del servidor dejó de correr.

## Documentos del proyecto

| Archivo | Para qué |
|---|---|
| `HALLAZGOS.md` | **Estado de los 42 hallazgos de auditoría. Empezá por acá.** |
| `REPORTE-NOCHE.md` | Sesión del 28-29/08/2026: pedidos, API, facturación electrónica, sitio web conectado al catálogo real. Alertas, decisiones y pendientes de esa noche. |
| `INVENTARIO.md` | Lo que ya existía antes de esa sesión — para no reconstruir lo que ya estaba hecho |
| `README.md` | Historia del desarrollo por sprints |
| `ACTUALIZAR_INVENTARIO.txt` | Cómo sincronizar el Excel con el ERP y el sitio |
| `COMO_USAR.txt` | Manual para el personal de la tienda |
| `PRODUCCION.txt` | Guía de despliegue en VPS |
| `RESPALDOS.txt` | Cómo respaldar y restaurar |
| `../Auditoria_2026-07-28/` | Auditoría integral, 8 documentos (F0–F7) |

## Fotos de producto (20/09/2026)

Regla de Oscar: **donde se hable de un producto, se ve su foto.**

- En plantillas, SIEMPRE `{% foto_producto p 44 "clickable-product-img" %}`
  (tag builtin, `core/templatetags/fotos.py`). En pantallas armadas en
  JavaScript, `fotoHTML(p, tam, clase)` de `static/js/fotos.js`, con los datos
  de `core.imagenes.completar_foto` / `datos_foto`. En el admin,
  `core.admin_fotos.columna_foto("producto")`.
- **Nunca** `{{ MEDIA_URL }}{{ p.imagen }}` ni `/media/...`: en el servidor
  las fotos viven en el bucket y esa URL da 404. Eso dejó fotos rotas en
  Precios, Stock, Devolver y "Registrar entrada" hasta el 20/09.
  `core/test_fotos.py` lo verifica solo.
- Se muestran **miniaturas** (`productos/min/<sku>.webp`, 240 px, ~10 KB),
  no el original de ~1024 px. Se crean al guardar la foto; si falta una, el
  navegador pide `/foto/<id>/`, que la genera y redirige. `entrypoint.sh`
  corre `generar_miniaturas` en segundo plano en cada despliegue.
- El chat de ayuda tiene la herramienta `buscar_producto` y la respuesta trae
  la foto de cada producto que devolvieron las herramientas.

**Solo las fotos nuevas (12/10/2026).** Las carpetas de fotos juntan todas
las compras (la de alimentos oficiales ya tenía 145) y los .bat las volvían a
subir todas. Ahora `CARGAR_FOTOS_ALIMENTOS.bat` y `CARGAR_FOTOS_EDITADAS.bat`
usan `cargar_fotos_por_sku --solo-cambiadas`: se salta la foto cuyo archivo ya
está en el bucket con los mismos bytes (`core.imagenes.ya_guardada_igual`,
compara el ETag/MD5 sin descargar). No se exige que el producto siga
apuntando a ella: si después le pusieron otra foto, fue a propósito y no se le
devuelve la vieja. El de alimentos primero corre `--simular` y le muestra a
Oscar la cuenta real antes de pedirle el SI.

## Búsqueda por descripción (20/09/2026)

Regla de Oscar: los buscadores de producto deben encontrar por **nombre o
descripción**, no solo por nombre. Ejemplo real: "peluche gallina" o "taza
comida azul" — la palabra clave a veces solo está en la descripción, no en
el nombre corto del producto.

- **POS, Recibir mercadería, Etiquetas** (JS con la lista precargada): el
  filtro del navegador ahora también compara contra `descripcion`. Cada
  vista Python que arma esa lista (`ventas.views.pos`, `compras.views.nueva`,
  `inventario.views.etiquetas`) agrega el campo `descripcion` al `.values()`.
- **Precios** (`catalogo.views.precios`): el filtro del servidor agrega
  `Q(descripcion__icontains=q)`.
- **Chat de ayuda** (`buscar_producto` en `core/chat_tools.py`): busca
  palabra por palabra, y cada palabra puede caer en el nombre O en la
  descripción — no exige la frase completa en un único campo, porque
  "azul" puede estar solo en la descripción mientras "taza" y "comida"
  están en el nombre.
- Pendiente, si Oscar lo pide: el buscador del sitio web (`api/views.py`,
  parámetro `?q=`) todavía solo busca en nombre y SKU exacto — no se tocó
  porque alimenta el sitio público (`allpetcr-web`) y no es lo que Oscar
  pidió esta vez.

## CABYS de cada producto (21/09/2026)

- `catalogo/cabys.py` es la ÚNICA tabla de códigos: cada uno verificado en
  la API de Hacienda (`api.hacienda.go.cr/fe/cabys?codigo=`), con su
  descripción oficial. Todos son de 13 %. `test_cabys` falla si una regla
  apunta a un código que no está en la tabla — así no se cuela uno inventado.
- Se asigna por categoría raíz, afinado por palabras del nombre y de la
  subcategoría (champú vs. cepillo, collar antipulgas, alimento húmedo).
- `asignar_cabys` no pisa un código ya puesto (a mano o por el contador)
  salvo `--reemplazar`, y no le pone código a un producto con IVA distinto
  de 13 %. Siempre deja el Excel `data/CABYS_PARA_EL_CONTADOR.xlsx`.
- Se aplica en el servidor con `ASIGNAR_CABYS.bat` (patrón de siempre: pide
  la contraseña, simula, pregunta SI).
- Desde la sandbox de Claude la API de Hacienda solo responde por WebFetch:
  `curl` la bloquea el proxy.

## Fichas de alimento (26/09/2026)

Información oficial de cada FÓRMULA de alimento (no de cada bolsa): beneficios,
"ideal para", análisis garantizado, ingredientes, guía de alimentación y
fuentes con fecha. Modelo `catalogo.FichaAlimento`; cada `Producto` apunta a
la suya por `ficha_alimento`. El sitio la recibe en el detalle de la API.

- Las fichas viven como JSON en `catalogo/fichas_alimento/` (versionadas en
  git) y se pasan a la base con `manage.py cargar_fichas_alimento`
  (`CARGAR_FICHAS_ALIMENTO.bat` para el servidor). Editar la ficha en el admin
  sirve, pero la próxima carga del JSON la pisa: corregir en el JSON.
- Etiquetas (etapas, necesidades, beneficios, nutrientes): vocabulario cerrado
  en `catalogo/alimentos.py`. Una clave nueva va ahí primero.
- Valores del análisis en formato canónico (punto decimal, sin miles).
- Estados: `verificado` y `parcial` se publican; `sin_investigar` y `revisar`, no.
- Regla absoluta: nada se deduce ni se copia de otra fórmula. Si el fabricante
  no lo publica, el campo queda vacío y la sección no se muestra.
- Fichas viejas: filtro "última verificación" en el admin.

## Tope de descuento disfrazado en el POS (02/10/2026)

Pedido de Oscar: al negociar un descuento frente al cliente, saber hasta dónde
ceder sin que se note. En el POS, solo para gerentes, cada tarjeta y cada línea
del carrito llevan dos dígitos gris claro sin rótulo (p. ej. `38`): el descuento
máximo en % sin vender bajo costo = margen sin IVA redondeado hacia abajo. En la
línea del carrito se tiñe rosado si el descuento escrito lo pasa. **Es a
propósito casi invisible y sin explicación: no "mejorarlo" poniéndole rótulo.**
Lógica en `ventas.views._filas_pos(con_tope=...)`; pruebas en
`ventas/test_tope_descuento.py` (incluye que al cajero no le llegue).

## Vender (POS) con la venta en grande (17/10/2026)

Pedido de Oscar: "lo mismo" que en Recibir mercadería. La venta a la
IZQUIERDA y en grande; el catálogo a la derecha, angosto (`minmax(330px,31%)`).
- Cada producto en UNA fila (foto+nombre+precio c/u · − n + · Regalía /
  Descuento % / o precio ₡ / tope · monto). `@container (max-width:900px)` baja
  los controles a un 2.º renglón (pasa en laptop 1366); `(max-width:520px)` en
  celular pone el nombre arriba con todo el ancho.
- Arriba: cliente y casilla dorada lado a lado. Abajo (`.pie`): a la izquierda
  el resumen de la última venta (`#ultima`) y la nota; a la derecha total,
  Efectivo/Tarjeta/SINPE/Mixto y Fiado. Con alto ≤ 820 px el pie se compacta.
- Lo recién escaneado se lleva a la vista y parpadea (`resaltarLinea`).
- El botón de la línea dice "🎁 Regalía" (antes "Regalo"); el tiquete impreso
  sigue diciendo REGALO, que es lo que lee el cliente.
- El chat sigue oculto y se abre con "Asistente"; ahora cae sobre el catálogo.
- **Ventas en espera** (pedido de Oscar: una clienta fue a buscar más cosas y
  llegó otra a pagar). Botón "Atender a otro cliente" → la venta queda en una
  pestaña (cliente · total · "en espera") y se abre otra. Cada venta guarda
  carrito, cupón, cliente y su `clave` de cobro. `enEspera(id)` resta lo
  apartado en otras ventas del stock disponible. Se guardan en `localStorage`
  (`allpetcr.pos.ventas`, se descartan pasadas 12 h) para sobrevivir un Ctrl+F5.
  El servidor no se enteró: una venta en espera no existe hasta cobrarse.

## Aviso de agotados (02/10/2026)

Pedido de Oscar: cuando un producto que tuvo existencia queda en cero, alarma
visible y una lista (con código del proveedor) para decidir si se vuelve a
pedir. La decisión es del negocio.

- Modelo `inventario.Agotamiento`. Lo abre y lo cierra SOLO
  `registrar_movimiento` (`_avisar_agotamiento`): salida VEN/REG/AJU/TRA que
  deja stock 0 → abre; cualquier entrada → cierra (`repuesto_en`). La
  anulación de una compra (DEV negativo) no avisa. Uno abierto por producto
  (restricción en la base).
- Pantalla `inventario:agotados` (gerente) y Excel `inventario:agotados_excel`,
  ambos de `inventario/agotados.filas`. Código del proveedor = SKU sin BEL-/
  GOS-/ZDG-/SPC-; los NP… no se muestran.
- Alarma: banner rojo en el Inicio (sin caché) y aviso en el POS
  (`agotados` en la respuesta de la venta). El cajero no ve costos.
- La migración 0007 creó los avisos de lo que ya estaba agotado.

## Precio por kilo en el POS (19/10/2026)

"Experimento" de Oscar: al consultar un alimento, ver cuánto sale el kilo.
La tarjeta del catálogo dice "15 kg · ₡3.993 el kg" y la línea de la venta
"₡59.900 c/u · ₡3.993 el kg". Lógica en `catalogo/por_kilo.py`:
- Contenido: `peso_valor`/`peso_unidad`; si faltan, la presentación SOLO si es
  un peso limpio ("15 kg", "500 g"; misma regla que `cargar_fichas_alimento`).
  Nunca desde el nombre. En producción (19/10) los 185 alimentos secos y
  húmedos tenían presentación limpia; 22 de 26 snacks también.
- Solo raíces Alimento, Snacks y premios, Arena y sanitarios (o con ficha de
  alimento): un jarabe de 30 ml "a ₡300.000 el litro" solo confunde.
- Precio con IVA, colones enteros; l/ml → "el litro". Pruebas:
  `catalogo/test_por_kilo.py`.

## Lo vendido, para reponer (20/10/2026)

Pedido de Oscar: "encuentro que se agotó y que quedan pocas, pero no sé qué se
vendió para reponer… con un rango de fechas". Pantalla `inventario:vendido`
(gerente; tarjeta primera de Inventario en el Centro de reportes) y Excel
`inventario:vendido_excel` (con columna "A pedir" vacía), ambos de
`inventario/vendido.filas`.
- Rango: atajos Hoy · Ayer · 7 · 15 días · Este mes, o fechas a mano
  (`normalizar`: en orden, sin futuro, máx. 366 días). Por defecto 7 días.
- Facturas EMITIDAS; regalías cuentan; lo devuelto de esas ventas se resta.
- Estado: Agotado (0) · Quedan pocas (≤ `stock_minimo`) · Hay. Orden: estado,
  luego más vendido. Filtro por proveedor (de la ÚLTIMA compra recibida,
  `agotados._ultima_compra`) y "Solo agotados y con pocas".
- Código del proveedor con `agotados.codigo_proveedor`. Pruebas:
  `inventario/test_vendido.py`.
- De paso: `msg()` de Recibir mercadería vuelve a escribir `m.textContent=t`
  (la v6.2 lo había cambiado y rompía `core.test_seguridad_cabeceras`).

## Asistente: alimentos por ficha técnica y pantallas nuevas (20/10/2026)

Oscar quiere preguntarle a la barra "¿qué alimento le sirve a un gato con
bolas de pelo?" y que responda con la ficha técnica. Revisión previa: el
chat estaba conectado (Haiku 4.5, sin errores desde julio, números = Inicio).
- Herramienta `buscar_alimento` (todos los roles, sin costos) →
  `catalogo/recomendar.buscar`: traduce la necesidad a claves del vocabulario
  (`SINONIMOS`, comparación al inicio de palabra), filtra por especie, etapa,
  tamaño y tipo, y solo devuelve fichas con un motivo DECLARADO
  (`coincide_por`: necesidad, beneficio, texto oficial, proteína principal o
  lugar en la lista de ingredientes). Presentaciones en existencia con precio
  por kilo. Productos sin ficha (pasta de malta) van aparte, por nombre o
  descripción (`PALABRAS_SOLO_PRODUCTOS`).
- Hallazgo (20/10): ninguna ficha de gato declara "Control de bolas de pelo";
  la respuesta honesta es esa + Tabergat Malta. Producción tenía 120 fichas
  (repo 139: las 14 de 1st Choice no están cargadas y no hay productos 1st
  Choice) y 161 productos vinculados.
- Herramienta `lo_vendido` (gerente/contador) = `inventario/vendido.filas`.
- `SYSTEM_PROMPT_CHAT`: identidad ("sos parte de AllPet"), POS v2 (ventas en
  espera, redondeo, regalía, gaveta, precio por kilo), caja por billetes,
  Recibir mercadería v6.2, Lo vendido y Agotados, reglas de recomendación.
  `max_tokens` 1024 → 1500. Pruebas: `catalogo/test_recomendar.py`.

## Fichas al 100 % y lista "Alimentos sin ficha técnica" (20/10/2026)

- Oscar corrió CARGAR_FICHAS_ALIMENTO.bat: producción pasó a 139 fichas y
  186 productos vinculados (First Choice y Pink). Ojo: los 1st Choice se
  llaman "First Choice" en el ERP.
- Nuevas: 3 Gosbi Exclusive Grain Free (Adult Toy Duck, Adult Mini Fish with
  Lamb, Puppy Medium Fish with Lamb; verificadas contra gosbi.com en el
  navegador) y 6 Loving Pets (parciales: el fabricante no publica
  ingredientes). Los Sticks "unidad" se sumaron a las fichas existentes.
- Sin fuente oficial en línea (NO se cargaron fichas vacías; esperan la foto
  de la etiqueta): Balance Castrado, LR Weight Control, Weight Control 14.97,
  Skin & Coat; Red Oak High Performance (Corey Nutrition); Dukan/Dukat
  húmedos 85 g; NutriSource Soft & Tender Lamb y PureVita Kangaroo
  (descontinuados en el sitio); BEL-80052 (no existe ese sabor en el sitio).
  belinanutricion.com solo carga con navegador; gosbi.com ya no muestra EAN.
- `catalogo:sin_ficha` (/precios/sin-ficha/, gerente, tarjeta en Reportes →
  Inventario): alimentos y snacks activos sin ficha + fichas no verificadas
  con lo que falta. `recomendar.alimentos_sin_ficha` / `fichas_incompletas`.
  `buscar_alimento` devuelve `alimentos_sin_ficha` y el asistente lo dice.
- En el PC las fichas JSON están en CRLF: conservarlo al copiar.

## Recibir mercadería más clara (12/10/2026)

Oscar creó un producto nuevo desde "Recibir mercadería" y no encontró dónde
poner la cantidad: entraba con 1 y se cambiaba en una casilla de 52 px
rotulada "cant.". Ahora el formulario de producto nuevo pide **Cantidad que
llegó** y **De regalo** junto al costo por unidad, y cada línea de la compra
va en dos filas con rótulos completos (Cantidad · De regalo · Costo c/u ·
Ganancia %); lo recién agregado se lleva a la vista y parpadea.

Se corrigió de paso un error: la ganancia del formulario se heredaba a la
línea y al registrar se recalculaba el precio que se acababa de poner
(₡55.900 → ₡56.000 por el redondeo, o más bajo si había unidades de regalo).
El producto nuevo entra ahora con `gan: null`: queda el precio que se vio.

**Distribución (v5, 12/10/2026).** Pedido: "que absolutamente todo se pueda
ver bien". La lista de lo recibido va arriba con todo el alto; proveedor,
factura, forma de pago e IVA van abajo en dos filas junto a "Registrar" (paso
3). El chat de ayuda va abajo a la IZQUIERDA en esta pantalla (a la derecha
tapaba el botón de registrar) y la grilla tiene relleno abajo para que la
última fila suba por encima. "Cómo se usa" pasó a la barra de arriba. Con
alto ≤ 820 px los tres pasos se esconden. Probado en 1920×1080, 1366×768,
1280×720 y 390 px de ancho (sin desborde horizontal).

**Distribución v6 y descuento de factura (16/10/2026).** Pedido de Oscar: la
lista de lo recibido a la IZQUIERDA y en grande; el buscador a la derecha,
angosto. Cada producto va en UNA fila (nombre + precio · 4 casillas · subtotal);
si la lista queda angosta, `@container (max-width:800px)` baja las casillas.
Abajo: datos de la factura a la izquierda, totales y "Registrar" a la derecha.
El chat volvió a la derecha (ahora cae sobre el buscador, no sobre la factura).
- **Descuento de la factura**: el del pie, sobre el subtotal y ANTES del IVA
  (caso real Belina: ₡29.260 − ₡878 = ₡28.382; IVA ₡3.690 = 13 % de eso).
  `Compra.descuento`; `Compra.total` ya va neto; cada `LineaCompra` guarda su
  `total` de factura y su parte (`descuento`), repartida por
  `services.repartir_descuento` (proporcional, céntimos exactos, el sobrante a
  la línea más grande). `costo_real_unitario` = (total − descuento) / recibidas,
  así kardex y asiento cuadran con lo pagado.
- El descuento SÍ llega al precio calculado con "Ganancia %" (mismo criterio
  que la bonificación: el descuento conseguido tiene que llegar al precio).
- Bajo el IVA se muestra "13 % de ₡neto = ₡X" para comparar con el papel.
- Excel contable: columna "Descuento de la factura". La carga masiva desde
  Excel todavía NO tiene descuento. Pruebas: `compras/test_descuento_factura.py`.

**v6.2 "Registrar" que no parece muerto (19/10/2026).** Oscar dijo que
"Registrar compra no hace nada" (Gosby); en producción el POST respondía 200 y
la registré yo (OC-00000017). Causa probable: sesión vencida, página trabada o
el aviso de 4 s que no vio. Ahora: el botón dice "⏳ Registrando…" mientras
trabaja; los errores quedan fijos (con ✕, se cierran con un clic) y los éxitos
se van solos; si la respuesta es el login → "se venció la sesión"; si no es
JSON → "el servidor tuvo un problema (código N), NO se registró"; a los 45 s
se aborta y se avisa que revise en Administración → Compras si quedó.

## Ajustes de inventario (12/10/2026)

Pedido de Oscar: sacar el ajuste de Etiquetas y tener en Administración →
Herramientas una pantalla "Ajustes de inventario" para corregir existencias,
todos los datos del producto y su foto.

- `inventario:ajustes` (lista con buscador; escáner + Enter abre el producto)
  y `inventario:ajuste_producto` (una página por producto, tres formularios
  con `accion` = existencia / datos / foto). Solo gerente.
- Existencia: se escribe **lo que hay de verdad** (`ExistenciaRealForm`) y el
  sistema registra la diferencia como AJU por `registrar_movimiento`. Si se
  suman unidades y el producto no tiene costo, el costo es obligatorio; si
  tiene, se usa el promedio.
- Datos: `DatosProductoForm` (sin SKU, costo ni existencia). El precio pasa por
  `cambiar_precio` en la misma transacción, así queda en su historial.
- Foto: se guarda como `<sku>-<fecha>.<ext>` para que el sitio/Cloudflare no
  sigan mostrando la vieja; valida con `compras.views._validar_foto`.
- La lista NO filtra por existencia ni por activo (EXCEPCIÓN DELIBERADA,
  comentada en la vista). `/inventario/ajuste/` GET redirige a la nueva.
- Ojo: un ajuste no genera asiento contable (solo kardex). Si unidades
  faltantes venían en una factura ya registrada sin esa línea, lo correcto es
  completar la compra, no ajustar.

## La manada AllPetcr.com — clientes por QR (13/10/2026)

Pedido de Oscar: QR en la tienda → `www.allpetcr.com/manada?o=qr-tienda` →
registro con Google o con correo → cupón de bienvenida (hoy 10 %, primera
compra, un solo uso por persona) → opcional "Contanos de tu mascota", una vez.

- App `manada`: `Regalia` (la edita el gerente en el admin; UNA activa; cada
  cupón copia el % al emitirse), `PerfilManada` (OneToOne con `ventas.Cliente`:
  NO hay una segunda tabla de clientes), `Mascota`, `Cupon`.
- Un cupón por cliente: restricción en la base (`un_cupon_bienvenida_por_cliente`);
  se busca por `google_sub` y por correo para no duplicar personas.
- Se quema en `ventas.services.registrar_venta(cupon=...)`, con
  `select_for_update`, en la MISMA transacción que la venta. Gana el mayor
  entre el descuento del cajero y el del cupón (no se suman). El tope de 15 %
  del cajero no frena el cupón; el piso de costo sí. Anular la venta libera
  el cupón; una devolución parcial no.
- API (token del sitio): `manada/registro/`, `manada/mascotas/`, `manada/regalia/`.
  **Sin `verificado: true` la API NO devuelve el código ni la llave de
  mascotas**: van solo al correo, que es la verificación del registro por
  correo. `verificado` lo pone el sitio únicamente cuando Google confirmó el
  correo (`email_verified`).
- POS: casilla dorada «Cupón de la manada» (`ventas:cupon` revisa sin quemar).
- Correo: `manada/correo.py` + `templates/manada/correo_bienvenida.*`;
  `SITIO_WEB_URL` arma el enlace de mascotas.
- Pruebas: `manada/tests.py`.

**Sin correo ni contraseña (14/10/2026).** En la tienda mucha gente mayor no
se acordaba de su correo ni de su clave de Google. Ahora:
- Registro web: nombre + WhatsApp (correo opcional). El código sale en
  pantalla **si el cupón se acaba de crear**; si el número ya estaba, no se
  muestra el código de esa persona ("pedilo en caja con tu número").
- `registrar_miembro` busca por google_sub → correo → teléfono
  (`cliente_por_telefono`: últimos 8 dígitos, los de caja tienen guiones).
  A un miembro existente solo se le completan datos vacíos; sus preferencias
  solo cambian con Google.
- La casilla dorada del POS acepta el código **o el WhatsApp** (≥ 8 dígitos).
- Botón **🐾 Unir** en el POS (`ventas:manada_rapido`, origen CAJA): para
  quien no pudo escanear el QR; aplica el regalo en la misma venta. Exige la
  casilla "el cliente aceptó" (Ley 8968).

**Historial de compras y recordatorios (14/10/2026).** Pedido de Oscar: ver
qué compró cada cliente y cuándo, para avisarle que se le acaba la comida y
mandarle promociones de sus marcas. Aprobó el ejemplo `ejemplo_ficha_cliente.html`.
- **Reconocer (control cruzado)**: `manada/identificar.py` busca cédula →
  teléfono (últimos 8 dígitos) → correo. El NOMBRE nunca une: solo sugiere
  (`avisar_si_mismo_nombre`). Si dos datos apuntan a clientes distintos se
  queda con el primero y crea `PosibleDuplicado` (uno por par, nunca insiste
  si ya se decidió). `unir_clientes` mueve facturas, pedidos, CxC (+saldo),
  mascotas, y perfil/cupón si faltaban; el absorbido queda inactivo.
- **Caja**: la casilla dorada (`ventas:cupon`) acepta código, WhatsApp, cédula
  o correo. Si el cliente tiene regalo disponible lo aplica; si no, igual lo
  pone en el selector de cliente → la venta queda a su nombre. Decisión de
  Oscar: pedir WhatsApp o cédula en CADA compra. `cliente_rapido` también
  reconoce antes de crear.
- **Sitio**: `Pedido.cliente` (nuevo) se llena en `crear_pedido` con
  `cliente_para_pedido`; si no reconoce, crea el Cliente pero NO lo hace
  miembro (falta su consentimiento). Pendiente en `allpetcr-web`: casilla
  "Quiero unirme a la manada" en el pago.
- **Historial** (`manada/historial.py`): facturas EMI + pedidos no cancelados.
  "Se le acaba" = ritmo real (kilos si todos los productos dicen su contenido,
  si no unidades); misma `ficha_alimento` = mismo alimento aunque cambie la
  bolsa. Con una sola compra NO estima. Consumibles = raíz Alimento o Arena.
- **Pantallas** (gerente). Oscar: "todo lo que tenga que ver con clientes y
  sus mascotas en el acceso rápido de Manada", "simple, estilo Apple". El
  botón Manada del Inicio abre `manada:clientes`; NO hay tarjeta en Admin.
  Control segmentado (`_pestanas.html`): Clientes · Mascotas · Recordatorios
  · Promociones, y a la derecha "Exportar a Excel" (`manada:exportar`, con
  compras/total/marcas) y "Regalo de bienvenida" (admin de Regalia). Los
  duplicados salen como franja "Revisar ›" solo si hay pendientes. Migas
  `_migas.html`: Inicio (/) › Manada, nunca a /admin/. Encabezado dice
  "Manada" (`{% block seccion %}` en `admin/base_site.html`). En celular
  los `.seg` van en una sola franja deslizable. WhatsApp por enlace `wa.me`
  (decisión de Oscar: a mano desde el teléfono de la tienda, sin API paga).
  Solo quien tiene `acepta_promociones` lleva botón (Ley 8968).
- Pruebas: `manada/test_historial.py`. Las 3 pruebas de concurrencia de
  pedidos/facturación fallan en SQLite (sandbox): necesitan PostgreSQL.

## Cierre de caja contando billetes y monedas (14/10/2026)

Pedido de Oscar: en el cierre, anotar cuántos billetes y monedas hay de cada
denominación y que el sistema vaya sumando.

- Denominaciones en `caja/denominaciones.py` (ÚNICA lista; fuente BCCR,
  revisada el 14/10/2026): billetes 20.000/10.000/5.000/2.000/1.000 y monedas
  500/100/50/25/10. Sin el billete de ₡50.000 ni la moneda de ₡5 (fuera de
  circulación). Si el BCCR cambia algo, se cambia solo esa lista.
- `CerrarCajaForm` arma campos `den_<valor>`; vacío = 0. El total lo calcula el
  SERVIDOR (`cerrar_caja(conteo=...)`); lo que sume el navegador es solo para
  verlo. Se guarda el desglose en `SesionCaja.conteo_efectivo` (JSON) y se ve
  en el admin. Los cierres viejos quedan con `null`.
- Sigue siendo arqueo ciego: el total contado se ve; lo esperado, solo al cerrar.
- Pantalla: − número + por fila, subtotal, total fijo arriba de la tarjeta;
  Enter pasa a la siguiente casilla (no cierra). Pruebas en
  `caja/test_conteo_billetes.py`.

**Apertura y cierre a la vista (17/10/2026).** Al abrir caja se ve "Así se
cerró la caja anterior" (`_cierre_anterior.html`: apertura, ventas, redondeos,
esperado, contado, diferencia, datáfono/SINPE y billetes) con
`caja.services.ultimo_cierre`. Al cerrar se ve "Así se abrió esta caja" y lo
que contó el cierre anterior, con un aviso si no calzan (puede ser un depósito:
el texto no acusa). Lo esperado de ESTA caja sigue oculto (conteo ciego).

## Redondeo del total en el POS (17/10/2026)

Caso real: ₡13.554 en efectivo, sin vuelto, se cobró ₡13.500 y el cierre quedó
con diferencia. Ahora "Redondear el total" (bajo el total) o el atajo "Dejar en
₡13.500" del cobro en efectivo.
- `registrar_venta(redondeo=)`: colones enteros, se reparte entre las líneas
  cobradas como descuento (`_aplicar_redondeo`, proporcional, sobrante a la
  más grande; IVA recalculado; piso de costo aplica). Queda en
  `FacturaVenta.redondeo` y `LineaVenta.redondeo` (ya incluido en `descuento`
  y `descuento_monto`: así lo pide la FE). Tiquete y factura muestran
  "Descuentos" sin el redondeo y un renglón "Redondeo".
- Topes: cajero ₡500 (`REDONDEO_MAXIMO_CAJERO`), gerente ₡1.000. Para más, es
  un descuento en el producto. Solo hacia abajo.
- En el POS el redondeo es de cada venta (también en espera) y se quita solo si
  la venta cambia (`redondeo.base`). Pruebas: `ventas/test_redondeo.py`,
  `caja/test_apertura_y_cierre.py`.

## Descuento por precio final y en números enteros (13/10/2026)

Pedido de Oscar: los decimales en el % eran imposibles de teclear, y quería
poner "lo dejo en ₡2.000" en vez de adivinar el %.

- POS: cada línea tiene **Descuento [ ] %** (entero; "12,6" se vuelve 13) y
  **o precio ₡[ ]** (precio final por unidad). Escribir uno borra el otro.
- `registrar_venta` acepta `precio_final` por línea: el descuento es exacto
  (`bruto − precio_final × cantidad`) y el % se guarda con decimales solo como
  registro (14,89 %). Tope del cajero (15 %) y piso de costo se aplican sobre ese %.
- Con %, el descuento se redondea a **colón entero** (`ROUND_HALF_UP`); el JS
  del POS hace lo mismo (`Math.round`). Nada de ₡2.044,50.
- Cupón vs. precio final: gana el que dé más descuento; no se suman.
- Pruebas: `ventas/test_precio_final.py`.

## Reglas del proyecto

**Los comentarios explican el *porqué*, no el *qué*.** Es la característica
mejor valorada del código en las dos auditorías (9/10 en documentación).
Mantenela: es lo primero que se pierde cuando hay prisa.

**Todo en español**, incluidos nombres de variables, funciones y mensajes.

**Las reglas de arquitectura se verifican solas** en `core/test_arquitectura.py`:
resolución de empresa vía `core/tenancy.py`, consultas de producto filtradas
por empresa, sin `except: pass` mudos, señales de auditoría conectadas por
`sender`. Si agregás una regla, agregá su prueba — una regla que no se
verifica se rompe en tres meses.

**No se edita el stock ni el costo a mano.** La fuente de verdad es el kardex
(`inventario.MovimientoInventario`); `stock_actual` y `costo_promedio` son
denormalizados. `manage.py reconciliar` verifica que cuadren.

**Al optimizar, demostrá equivalencia.** El patrón está en
`core/test_equivalencia_dashboard.py` y `core/test_equivalencia_reportes.py`:
se calcula el resultado por el método viejo y se exige que coincida.

## Cómo trabaja Oscar

Prefiere que se le desafíen las ideas antes que se le den la razón. Espera que
se distinga lo verificado de lo inferido, que se digan los límites de cada
medición, y que si falta un dato se pida en vez de suponerlo. Si una
recomendación de una auditoría o de un informe parece exagerada o mal
fundamentada, decilo con la evidencia — ya pasó con el hallazgo PERF-02.

## Pendientes que dependen del negocio, no del código

1. Programar `manage.py reconciliar` semanalmente en el Programador de tareas.
2. Sacar los respaldos de OneDrive (`ALLPETCR_RESPALDOS`) y probar una
   restauración completa.
3. Decidir sobre monitoreo en producción (Sentry u otro).
4. ~~Confirmar si el plan sigue siendo pasar a régimen tradicional~~ —
   resuelto el 20/09/2026: la empresa ES tradicional desde el día 1.
5. Descargar el Anexo de Estructuras v4.4 y los XSD oficiales de Hacienda,
   y tramitar la llave `.p12` — sin eso, `facturacion_electronica` no
   puede generar ni firmar XML de verdad. Detalle exacto de qué bajar y
   dónde ponerlo en `REPORTE-NOCHE.md`.
6. Decidir cómo el sitio público va a llegar hasta la API del ERP (que
   "corre solo en local"): VPS, túnel, o algo intermedio.
7. Elegir pasarela de pago cuando corresponda — el checkout del sitio y el
   webhook de confirmación ya están construidos y probados, solo faltan
   las credenciales reales de un proveedor.

La cédula jurídica real (`3-102-969361`) ya se confirmó y está cargada en
`Empresa.identificacion`.

Ver `HALLAZGOS.md` para la lista completa y las variables de entorno nuevas.
