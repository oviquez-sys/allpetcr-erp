# ALLPETCR ERP — núcleo v1

Sistema de gestión para ALLPETCR.COM. Arquitectura aprobada en Fase 2:
monolito modular Django + PostgreSQL, motor fiscal configurable por régimen.

## Estado

### S1 (completada) — base + catálogo + inventario
- Proyecto, empresa (régimen simplificado), sucursal, bodega, multi-empresa vía FK
- 184 productos importados del Excel real (₡1.303.502 a costo)
- Kardex inmutable, costo promedio ponderado, bloqueo de stock negativo

### S2 (completada) — auditoría + ajustes
- Auditoría automática con usuario e IP (antes/después en JSON)
- Pantalla de ajustes `/inventario/ajuste/` (motivo obligatorio)
- `data/DEPURACION_NOMBRES.xlsx` (152 productos por renombrar — pendiente de Oscar,
  pospuesto hasta completar el inventario con `data/PLANTILLA_CAPTURA_INVENTARIO.xlsx`)

### S3 (completada) — POS + caja
- **POS** en `/pos/`: búsqueda por nombre/SKU/código de barras (Enter agrega si hay
  un único resultado — compatible con lector de códigos), carrito, cobro en
  efectivo/tarjeta/SINPE, tiquete imprimible
- **Caja**: apertura con monto contado, movimientos ligados a la sesión, cierre con
  arqueo ciego (esperado vs. contado, diferencia)
- **Ventas**: consecutivo FV con bloqueo (dos cajas nunca repiten número), motor
  fiscal por régimen (RTS: sin desglose de IVA; tradicional: IVA por producto),
  anulación con reversas de inventario y caja (nunca se edita ni borra una factura)
- **27 pruebas automatizadas** (`python manage.py test`) — todas pasan

### S4 (completada) — clientes y cuentas por cobrar
- Cliente con límite de crédito, saldo, contacto, dirección y notas
- Venta a crédito en el POS (selector de cliente + botón CxC): valida el límite
  y revienta la venta completa si no alcanza; no mueve caja
- CxC por factura con abonos parciales/totales; el abono en efectivo entra a la
  caja abierta, otros medios no la tocan
- Estado de cuenta por cliente (`/pos/cliente/<id>/estado-cuenta/`) con abonos
- Anulación de venta a crédito: libera el crédito si no tiene abonos; si ya
  cobró parte, se bloquea (debe gestionarse la devolución primero)
- **40 pruebas** en total, todas pasan

### S5 (completada) — contabilidad automática
- App `contabilidad`: catálogo de cuentas jerárquico (plantilla PYME CR creada
  sola por empresa), asientos con línea débito/crédito y CHECK de integridad
- **Asientos automáticos** en la misma transacción de cada operación (si no
  cuadran, la operación se revierte): venta (por régimen), costo de venta a
  costo promedio, cobro de CxC, y reversas en anulación. Nadie digita asientos.
- Efectivo → Caja; tarjeta/SINPE → Bancos; crédito → CxC
- Libro diario (`/contabilidad/libro-diario/`) y balance de comprobación
  (`/contabilidad/balance/`) que siempre cuadra
- **51 pruebas** en total, todas pasan (incluye "todo asiento cuadra" y
  "el balance global cuadra")

### S6 (completada) — compras, dashboard y monitor RTS
- App `compras`: proveedores, compra en borrador y recepción que entra al
  kardex (recalcula costo promedio) y genera su asiento (Debe Inventario,
  Haber Bancos si contado / CxP si crédito), en la misma transacción
- Dashboard (`/`, página de inicio): ventas hoy/mes, utilidad y margen, efectivo
  en caja, CxC, valor de inventario y stock bajo — todo en vivo desde la BD
- **Monitor del régimen simplificado**: compras del año vs. límite (186 salarios
  base) con alerta al 80%, para avisar antes de salir del RTS
- **59 pruebas** en total, todas pasan

## Núcleo v1 COMPLETO

Ciclo verificado de punta a punta con datos reales: compra → recepción (sube
stock y costo) → venta → asientos automáticos → dashboard, con el libro
contable siempre cuadrado. El núcleo v1 del plan de Fase 2 está terminado.

### Antes de usar en la tienda (tareas de Oscar)
1. Completar el inventario faltante con `data/PLANTILLA_CAPTURA_INVENTARIO.xlsx`
2. Depurar los 152 nombres duplicados (`data/DEPURACION_NOMBRES.xlsx`)
3. Mover el proyecto fuera de OneDrive y definir respaldos diarios verificados
4. Desplegar en el VPS (PostgreSQL vía `docker-compose.yml`)

### Fuera del núcleo v1 (fases futuras, si se justifican)
Facturación electrónica v4.4 (al pasar a régimen tradicional), multi-sucursal
operativo, listas de precios, lotes/vencimientos, estados financieros formales,
IA. La arquitectura ya está lista para incorporarlos sin rediseño.

## Cómo correrlo en Windows

```
cd allpetcr-erp
python -m venv .venv
.venv\Scripts\activate
pip install Django openpyxl
python manage.py migrate
python manage.py importar_inventario "data\INVENTARIO REAL AL 6-7-2026   2.0.xlsx"
python manage.py createsuperuser
python manage.py runserver
```

Rutas: `/pos/` (punto de venta) · `/caja/abrir/` y `/caja/cerrar/` ·
`/inventario/ajuste/` · `/admin/` (catálogo, kardex, facturas, auditoría).

**Nota OneDrive:** si SQLite falla dentro de esta carpeta, use
`set DJANGO_DB_PATH=C:\allpetcr\db.sqlite3` antes de `migrate`. Recomendado
mover el proyecto fuera de OneDrive. Producción: PostgreSQL en VPS
(`docker-compose.yml`) con respaldos diarios verificados.

## Reglas de dominio implementadas

- `inventario/services.registrar_movimiento`: única puerta al stock; transaccional,
  bloqueo de fila, prohíbe stock negativo, recalcula costo promedio en entradas.
- `ventas/services.registrar_venta`: LA transacción central — factura + kardex +
  caja se confirman juntos o nada; relee la sesión de caja con bloqueo.
- `ventas/services.anular_factura`: anulación por movimientos inversos (DEV en
  kardex, egreso en caja si fue efectivo); motivo obligatorio.
- `caja/services.cerrar_caja`: arqueo con esperado/contado/diferencia; sesión
  cerrada queda inmutable y no admite movimientos.
- Auditoría automática (usuario, IP, antes/después) sobre catálogo, inventario,
  caja y ventas. Facturas y kardex de solo lectura en el admin.

## Decisiones registradas

- Motor fiscal por régimen (Fase 2 §6): el cambio RTS → tradicional es
  configuración; ahí se activará el adaptador de facturación electrónica v4.4.
- El tiquete indica "no constituye comprobante electrónico" mientras la empresa
  esté en régimen simplificado.
- Monitor de límites del RTS: llega con compras (S6).
