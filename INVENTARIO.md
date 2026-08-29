# Inventario previo — noche 2026-08-28

Relevado antes de tocar código, para no duplicar lo que ya existe. Fuente:
lectura directa del código, no de los `.md` de auditoría (pueden estar
desactualizados — ver regla en `CLAUDE.md`).

## allpetcr-erp

**Apps instaladas:** `core`, `catalogo`, `inventario`, `caja`, `ventas`,
`contabilidad`, `compras`. Django 5.2, PostgreSQL local (`POSTGRES_HOST=localhost`,
db `allpetcr`), 330 pruebas en verde antes de empezar (ver más abajo).

### Modelos existentes relevantes a la misión de esta noche

- **`core.Empresa`**: `identificacion` (CharField, texto — ya listo para
  cédula alfanumérica), `regimen` (`RTS` / `TRAD`, con comentario explícito
  "Régimen tradicional (IVA + FE v4.4)" — **el cambio de régimen ya estaba
  previsto en el diseño**), `factor_rts`, `moneda`. `identificacion` está
  **vacía** en la base real ahora mismo.
- **`core.AuditLog`**, `core.ChequeoIntegridad`, `core.ChatMensaje`: bitácora,
  resultado de `reconciliar`, y chat de ayuda. Nada que tocar.
- **`catalogo.Producto`**: `sku`, `nombre`, `categoria`, `categoria_original`,
  `codigo_barras`, `presentacion`, `descripcion`, **`mascota`** (¡ya existe! —
  Bloque 6 ítem 38 ya tiene campo), **`imagen`** (CharField con ruta relativa
  a `media/`, ej. `productos/75564.png` — **no** es `ImageField`, es texto
  libre que los comandos llenan a mano), `impuesto` (FK a `Impuesto`),
  `costo_promedio`, `precio_venta`, `stock_actual`, `stock_minimo`, `activo`.
  **NO tiene**: `marca`, `peso_valor`, `peso_unidad`, `cabys`. → Bloque 1.
- **`catalogo.Impuesto`**: `tarifa`, vigencia. Ya soporta tarifas reducidas
  (es un modelo, no una constante).
- **`catalogo.CambioPrecio`**: bitácora de cambios de precio manual. Ya existe
  (parte de lo que pedía el punto de "historial", aunque es de precio, no de
  compras — ver más abajo).
- **`inventario.Bodega`**, **`inventario.MovimientoInventario`** (kardex
  inmutable, fuente de verdad del stock). `registrar_movimiento()`
  (`inventario/services.py`) ya usa `select_for_update()` dentro de
  `transaction.atomic()` — el patrón de concurrencia que pedía la tarea ya
  existe para las ventas normales. Lo reutilizo para la reserva de stock.
- **`ventas.Consecutivo`**: numerador genérico por `(empresa, tipo)`, con
  `select_for_update()` + `get_or_create()` dentro de `atomic()`. Ya lo usan
  `FacturaVenta` (tipo `FV`) y `Compra` (tipo `OC`). **Es exactamente el
  mecanismo que pedía el Bloque 4 para el consecutivo de factura
  electrónica** — lo reutilizo en vez de inventar uno nuevo.
- **`ventas.FacturaVenta`**, **`ventas.Cliente`** (con `limite_credito`,
  `saldo`, `identificacion` ya en texto), **`ventas.DocumentoCxC`**. Cálculo
  de IVA centralizado en **`ventas/services.py::_desglose_fiscal()`** — ya es
  la "única función" que pedía la regla técnica, y ya decide RTS vs.
  tradicional según `Empresa.regimen`.
- **`caja.SesionCaja`**, **`caja.MovimientoCaja`**: ya existen, sin cambios
  necesarios para esta noche.
- **`compras.Proveedor`**, **`compras.Compra`**, **`compras.LineaCompra`**:
  ya existe historial de compras (por proveedor). **No hay historial de
  compras por CLIENTE** (Bloque 1 ítem 6) — eso sí falta.
- **`contabilidad`**: partida doble completa, `CuentaContable`, `Asiento`,
  `LineaAsiento`, `CierrePeriodo`. Sin cambios previstos esta noche.

### Comandos de gestión ya existentes

`asignar_codigos_barras`, `exportar_catalogo_web` (puente ERP→web: escribe
`productos.json`/`categorias.json` y **copia** fotos a
`allpetcr-web/public/productos/` leyendo directo de `MEDIA_ROOT` — ver nota
de riesgo abajo), `importar_imagenes` (extrae fotos EMBEBIDAS en el Excel de
inventario, las mapea por posición de fila → SKU — **no** es "carpeta de
archivos nombrados por SKU", que es lo que pide el Bloque 1 ítem 4: hay que
escribir un comando nuevo, distinto), `importar_inventario`,
`sincronizar_inventario`, `registrar_compra_inicial`, `asignar_rol`,
`endurecer_auditlog`, `endurecer_documentos`, `reconciliar`, `reporte_diario`,
`respaldar`, `restaurar`.

### Almacenamiento de imágenes — estado real

`Producto.imagen` es texto libre; los archivos viven físicamente en
`MEDIA_ROOT` (disco local) y **tres puntos del código escriben ahí
directamente con `Path`**, sin pasar por la API de storage de Django:
`importar_imagenes.py`, `compras/views.py` (subida al recibir mercadería) y
`exportar_catalogo_web.py::_copiar_imagenes` (que además **lee** de
`MEDIA_ROOT` para copiar a la web). Volver esto configurable por variable de
entorno (Bloque 1 ítem 3) implica tocar los tres, no solo `settings.py`.
`boto3` ya está en `requirements.txt` (lo usa el respaldo a Backblaze B2), así
que un backend S3-compatible no agrega dependencia pesada nueva —
`django-storages` sí es nueva pero liviana.

### Dinero, régimen fiscal y CABYS — contexto importante

`catalogo.Impuesto` trae el comentario *"En régimen simplificado la venta no
desglosa impuesto: el motor fiscal decide"*, y `Empresa.Regimen.TRADICIONAL`
ya dice explícitamente *"IVA + FE v4.4"*. **El régimen tradicional y la
factura electrónica v4.4 ya estaban en la hoja de ruta del propio ERP antes
de esta noche** — no es una tarea que contradiga el negocio real, es
justamente la pieza que faltaba. Hoy la empresa real está en `RTS` (ver
`HALLAZGOS.md` y la base: `regimen='RTS'`), así que todo lo del Bloque 4 se
construye **apagado por defecto** y sin tocar el flujo de venta actual.

### Pruebas — línea base (antes de tocar nada)

```
python manage.py test core catalogo inventario        → 185 OK
python manage.py test ventas caja compras contabilidad → 145 OK
```

Total: **330 pruebas, todas en verde.** (Sube de las 240 que menciona
`HALLAZGOS.md` del 28/07 — hay trabajo posterior no reflejado ahí; coherente
con la regla del propio archivo de verificar contra el código.)

## allpetcr-web

**No se pudo inventariar en profundidad ni tocar código: el repositorio git
está corrupto (ver Alertas en `REPORTE-NOCHE.md`).** Por inspección de
archivos (sin git):

- Next.js 16 / React 19 / TypeScript, Tailwind 3, Vitest.
- `app/`: ya tiene `carrito`, `checkout`, `catalogo`, `producto/[sku]`,
  `contacto`, `sobre-nosotros`, `recompra`. **No hay páginas legales**
  (términos/privacidad/devoluciones) — Bloque 5 ítem 36 sigue pendiente.
- `lib/negocio.ts`: **contrario a lo que decía la misión, NO tiene
  marcadores `PENDIENTE` activos.** Cédula jurídica `3-102-969361`, WhatsApp,
  dirección, horario, todo lleno. Solo `redes.facebook/instagram` (vacíos,
  aceptable) y `direccion.lat/lng` (`null` — pendiente de pin en mapa, que es
  justo lo que pide el ítem 33). **Discrepancia real encontrada:** la base
  del ERP tiene `Empresa.identificacion` **vacía**, pero el comentario del
  archivo dice que la cédula "proviene de Empresa.identificacion en el ERP".
  Los dos sistemas no coinciden hoy. No se tocó ningún valor — se reporta
  para que Oscar confirme cuál es la cédula real y la ponga en el ERP (fuente
  de verdad según el propio comentario del archivo).
- `data/productos.json` y `categorias.json`: alimentados por
  `exportar_catalogo_web` del ERP (184 productos según lo último corrido;
  el ERP ya tiene 532 — desactualizado, coherente con lo que ya advertía
  `CLAUDE.md` del ERP).
- `package.json`: sin dependencias de pago ni servicios externos nuevos.
