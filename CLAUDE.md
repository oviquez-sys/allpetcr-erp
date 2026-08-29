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

- **432 pruebas** en verde · `check --deploy` sin advertencias (modo producción)
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
