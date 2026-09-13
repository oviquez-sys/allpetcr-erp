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
- Régimen fiscal real: **RTS** (Régimen de Tributación Simplificada).
  `Empresa.regimen` ya soporta cambiar a `TRAD` (tradicional) el día que
  corresponda; el motor de IVA (`ventas/services.py::_desglose_fiscal`) y
  el Bloque de facturación electrónica ya están construidos para ese
  cambio, apagados mientras tanto.
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

- `AGENTE_IMPRESION.bat` — doble clic en la computadora de la tienda; se deja
  abierto todo el día.

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
4. Confirmar si el plan sigue siendo pasar a régimen tradicional (activa el
   Bloque de facturación electrónica, ya construido).
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
