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
contabilidad de partida doble.

Hay un **segundo repositorio**, `allpetcr-web` (Next.js 16), que es el sitio
público. Son sistemas separados: el ERP exporta el catálogo a JSON y el sitio
lo consume. Si un hallazgo dice "del sitio web", no es de este repo.

## Estado (28/07/2026)

- **235 pruebas** en verde · `check --deploy` sin advertencias
- **PostgreSQL** (base `allpetcr` en localhost) desde el 28/07/2026
- 184 productos reales en catálogo
- Repos en GitHub: `oviquez-sys/allpetcr-erp` y `oviquez-sys/allpetcr-web`

## Cómo correrlo

```
acceso-directo/Iniciar_AllPetCR_ERP.bat     # arranca en el puerto 8000
```

Requiere `POSTGRES_HOST` definido; el `.bat` aborta con instrucciones si falta.

**Las pruebas tardan ~60 s en total.** Corrolas en dos grupos para no chocar
con límites de tiempo:

```
python manage.py test core catalogo inventario        # 116
python manage.py test ventas caja compras contabilidad # 119
```

## Documentos del proyecto

| Archivo | Para qué |
|---|---|
| `HALLAZGOS.md` | **Estado de los 42 hallazgos de auditoría. Empezá por acá.** |
| `README.md` | Historia del desarrollo por sprints |
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

1. **Confirmar la cédula jurídica real.** La documentada (`3-102-999999`)
   termina en `999999`, igual que la que el auditor marcó como falsa en el
   sitio. Bloquea publicar el sitio web.
2. Programar `manage.py reconciliar` semanalmente en el Programador de tareas.
3. Sacar los respaldos de OneDrive (`ALLPETCR_RESPALDOS`) y probar una
   restauración completa.
4. Decidir sobre monitoreo en producción (Sentry u otro).

Ver `HALLAZGOS.md` para la lista completa y las variables de entorno nuevas.
