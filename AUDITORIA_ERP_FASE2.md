# Auditoría del ERP de AllPetCR — Fases 1 y 2 (26/09/2026)

Rama de trabajo: `auditoria-erp-fase2`. No se tocó `main`, no se tocó la base de producción, no se borró ningún dato.

---

## 0. Fase 2: qué quedó hecho (léase primero)

Oscar aprobó aplicar todo sin consultarle. Todo está hecho y probado en la rama `auditoria-erp-fase2`, **pero
todavía no está publicado en la tienda**. Publicar lo decide usted (ver "Lo que le toca a usted").

**Pruebas automáticas:** 702 pruebas, todas en verde (antes eran 636, con 16 que fallaban siempre en su
computadora). Configuración de producción revisada sin advertencias. También se probó en un navegador, con una base
de prueba: venta con escáner y vuelto, venta con pago mixto, tiquete, historial, cierre de caja, carga desde
Excel, reportes y Excel para el contador.

| Etapa | Qué cambió para usted |
|---|---|
| 0. Limpieza y datos | Las copias de la base y los Excel con costos se sacaron del repositorio público. Siguen en su computadora. |
| 1. La plata cuadra | Ya no se puede anular una venta que tuvo devolución. Se acabó el doble cobro. El tiquete sale con la hora de Costa Rica. Si el tiquete no sale, el POS avisa. Los productos nuevos reciben un código corto que empieza con 2. La misma factura de proveedor no entra dos veces. |
| 2. Mostrador | Cobro en efectivo con vuelto (F1, escribir con cuánto paga, Enter). Pago mixto (F4). Reimprimir y mandar por correo desde la misma pantalla. Historial de ventas con buscador (también para cajeros). Cliente nuevo sin salir de la venta. El tiquete muestra quién atendió, los pagos y el vuelto. |
| 3. Mercadería | **Cargar mercadería desde Excel** con vista previa de errores. Etiquetas de toda una compra con un clic. Tipo de ajuste obligatorio (daño, vencido, conteo…). Escaneo con la cámara del celular. |
| 4. Caja y contador | Una sola caja compartida. El cierre compara datáfono y SINPE. **Excel para el contador**. Reporte de ventas por día/semana/mes y por categoría, con utilidad, y lo que menos se vende. |
| 5. Factura electrónica | Campos para los datos de la empresa y de los clientes. Cada venta guarda su IVA y su CABYS. Pantalla "Preparación para factura electrónica" con lo que falta. **No se emite nada todavía.** |
| Extra | Tres textos internos que se veían en pantalla (en el tiquete, en la ficha de precio y en Recibir) ya no se ven. |

### Decisiones que tomé por usted (me pidió "haga lo mejor")

1. **Anular:** solo se bloquea si la venta ya tiene una devolución. No puse límite de "solo el mismo día":
   no protegía más la plata y sí estorbaba para corregir errores del día anterior.
2. **Vuelto:** con Enter solo, se entiende que pagó exacto. Así no agrega un paso a la venta.
3. **Pago mixto:** efectivo + tarjeta + SINPE. **No se mezcla con fiado**: una venta a medias fiada complica los
   abonos y los reembolsos. Si pasa, se hacen dos ventas.
4. **Caja compartida:** una sola caja abierta a la vez. Quien llegue vende en ella y cada venta queda con su
   nombre. Si algún día quiere una caja por persona, se cambia con una variable (`CAJA_COMPARTIDA=0`).
5. **Descuentos:** se mantiene el tope de 15 % para cajeros. No agregué descuento sobre el total: con el
   descuento por producto alcanza y así hay un control menos que revisar.
6. **Vencimientos (INV-06):** no los agregué. Solo sirven si venden alimento o medicamento con fecha. Dígame
   si sí y se agregan.
7. **Agotados en la web (UX-01):** no lo cambié. Es del sitio web y contradice su decisión, así que usted decide.
   El cambio es de una línea en el sitio.
8. **Correo:** dejé listo un servicio de correo por internet (Resend) que se activa con una llave. Mientras no
   se active, el ERP ya no dice "enviado" si no mandó nada.

### Lo que le toca a usted (en este orden)

1. **Poner el repositorio en privado. Hoy.** GitHub → `oviquez-sys/allpetcr-erp` → Settings → General → abajo
   de todo, "Danger Zone" → Change visibility → Private. Las copias de la base siguen en el historial público
   hasta que haga esto.
2. **Cambiar las contraseñas** de todos los usuarios del ERP (Admin → Usuarios). Así las copias que ya se
   hayan descargado no sirven para entrar.
3. **Decirme si limpio el historial de GitHub.** Borra las copias del historial para siempre y no se puede
   deshacer en GitHub. Las copias siguen en su computadora. Lo hago yo cuando usted diga "sí".
4. **Generar una llave nueva para el sitio web** (Admin → Tokens) y ponerla en DigitalOcean, en la variable del
   sitio. La que estaba en las copias de la base es pública. Si quiere, lo hacemos juntos.
5. **Publicar:** primero doble clic en `TRAER_RESPALDOS_NUBE.bat` y ver que termine bien. Después, doble clic en
   `PUBLICAR_AUDITORIA.bat`, en un momento sin clientes.
6. **Probar el correo en la tienda:** después de publicar, cobre una venta y mándese el recibo a usted mismo.
   Si dice que no está configurado o no le llega, abra una cuenta en Resend (verifique el precio vigente), y
   ponga `RESEND_API_KEY` y `DEFAULT_FROM_EMAIL` en DigitalOcean.
7. **Convertir los códigos "NP…"** de los productos creados antes de hoy: Inventario → Códigos (la pantalla ya
   existía).
8. **Con el contador:** llenar los "Datos del emisor" (Admin → Empresas), revisar los CABYS dudosos
   (VEN-09) y confirmar desde cuándo hay que emitir factura electrónica.
9. **Probar una restauración** del respaldo de la nube en una base de ensayo (se la preparo cuando quiera).

### Cómo probarlo usted mismo (en la pantalla, después de publicar)

**Venta y tiquete**
1. Vender → escanee un producto dos veces: la cantidad tiene que quedar en 2.
2. Presione F1, escriba 20000 y Enter. El vuelto se ve en grande y el tiquete sale con la hora correcta y su nombre.
3. En el panel "Venta …" que queda abajo, toque "Reimprimir" y "Enviar por correo".
4. Toque "Mixto": ponga una parte en Efectivo y otra en SINPE. El botón Cobrar solo se activa cuando dice "Cuadra".
5. Apague la impresora de recibos y cobre algo. En unos segundos el POS tiene que decir que el tiquete NO salió.
6. Toque F1 dos veces seguidas muy rápido: tiene que quedar una sola venta en el Historial.

**Devoluciones**
7. Historial de ventas → busque una venta → Devolver una unidad. Vuelva al Historial: esa venta ya no tiene "Anular".

**Mercadería**
8. Recibir → "Cargar desde Excel" → descargue la plantilla, llene 2 filas (una con un error a propósito) y súbala.
   Tiene que marcar el error en rojo y no dejar confirmar. Corríjalo, súbalo de nuevo y confirme.
9. Al terminar, toque "Imprimir las etiquetas de esta compra".
10. Desde el celular de Francisco, en Chrome: Recibir → botón 📷 → apunte a un código de barras.

**Caja y contador**
11. Cerrar caja: además del efectivo, anote el total del datáfono y el SINPE. El mensaje final dice si cuadran.
12. Reportes → "Excel para el contador" → descargue el mes pasado y ábralo.
13. Reportes → "Ventas por período y categoría" → cambie a "Por semana".

---

## 1. Resumen para Oscar (una página)

El ERP está bien construido en lo básico: **una venta nunca queda a medias** (factura, inventario, caja y
contabilidad se guardan juntos o no se guarda nada), **dos cajas no pueden vender la misma última unidad**
(lo probé con dos ventas simultáneas: una pasa, la otra se rechaza) y **los números cuadran** (probé ventas en
efectivo, tarjeta, SINPE, una anulación y una devolución: ventas = caja = inventario = contabilidad).

Pero encontré 5 cosas urgentes:

1. **Copias completas de la base de datos están publicadas en internet.** El repositorio del ERP en GitHub es
   **público** y contiene la carpeta `_respaldo_traslado` con 5 copias de la base del 09/09/2026: usuarios con sus
   contraseñas (cifradas, pero se pueden intentar adivinar), la llave con la que el sitio web entra al ERP,
   clientes, ventas y pedidos. También hay Excel con costos. Cualquiera puede descargarlas. **Esto es lo primero.**
2. **Anular una venta que ya tuvo una devolución devuelve la plata dos veces.** Probado: venta de 2 unidades por
   ₡10.600, el cliente devuelve 1, y después se anula la venta: el sistema saca de caja **₡15.900** y el inventario
   queda con **una unidad de más** que no existe.
3. **Se puede cobrar dos veces la misma venta.** Los botones se bloquean al hacer clic, pero las teclas F1/F2/F3
   no; y el servidor no reconoce una venta repetida. Probado: dos envíos iguales = dos ventas.
4. **El tiquete impreso tiene la hora mal: sale 6 horas adelantada.** Probado: una venta de las 8:30 a. m. imprime
   "02:30 PM". Es la hora de Londres, no la de Costa Rica. (En la pantalla y en los reportes la hora está bien; el
   error es solo en el papel.)
5. **Falta la carga masiva de mercadería desde Excel en la pantalla.** Hoy solo se puede hacer con comandos
   técnicos. Con tanta mercadería pendiente de ingresar, esto le cuesta horas a Francisco y a usted. Además, los
   productos nuevos creados en "Recibir mercadería" reciben un código de barras largo ("NP2609…", 20 caracteres) y
   no el código interno corto que empieza con 2 que usted decidió: la pistola no lo lee bien en la etiqueta.

Y una advertencia que no es de código sino legal: el ERP está configurado como **régimen tradicional**, y cada
tiquete dice "no constituye comprobante electrónico". Confirme con el contador **desde qué fecha** el negocio debe
entregar comprobantes electrónicos y cómo hacerlo mientras el ERP no los emite (ver sección 5, FE-01).

**Tiempo de una venta típica de 3 productos** (estimado leyendo el código, no medido con cronómetro en la tienda):
escanear 3 veces + tecla F1 = 4 acciones, 0 clics con el mouse, unos 6 a 10 segundos. El tiquete sale solo. Ya
está cerca de la meta "escanear, cobrar, listo". Lo que falta para el mostrador: **calcular el vuelto**, **pago
mixto** y un botón de **reimprimir / enviar por correo** en la misma pantalla.

---

## 2. Tabla de hallazgos

Severidad: **Crítica** (pierde plata o datos hoy) · **Alta** · **Media** · **Baja**.
Esfuerzo: **S** = menos de medio día · **M** = 1 a 2 días · **L** = 3 a 5 días.
"Verificado" = lo comprobé con una prueba; si no dice, es por lectura del código.

### A. Venta

| Código | Qué falla | Por qué importa | Sev. | Esf. | Evidencia |
|---|---|---|---|---|---|
| VEN-01 | Anular una venta que ya tuvo devolución parcial vuelve a devolver todo: inventario y efectivo se duplican. La pantalla Actividad muestra "Anular" aunque haya devoluciones. | Plata que sale de caja sin razón; inventario inflado que después no aparece en el conteo. **Verificado:** stock 11 en vez de 10; ₡15.900 devueltos de ₡10.600 cobrados. | **Crítica** | S | `ventas/services.py:217-255` (no revisa devoluciones previas); `templates/core/actividad.html:103-106` |
| VEN-02 | Doble cobro: F1/F2/F3 llaman a `cobrar()` aunque los botones estén bloqueados; el servidor no detecta un envío repetido. | Venta duplicada: inventario rebajado de más y caja que no cuadra. **Verificado:** 2 envíos iguales = 2 ventas (FV-1 y FV-2). | **Alta** | S | `templates/ventas/pos.html:477, 537-538`; `ventas/views.py:80-100` |
| VEN-03 | No hay campo "con cuánto paga" ni cálculo de vuelto; tampoco se guarda el efectivo recibido. | Errores de vuelto se pagan de la caja; el cajero calcula de cabeza con el cliente esperando. | **Alta** | M | `templates/ventas/pos.html:197-210, 462-509`; `ventas/models.py:81` (sin campo) |
| VEN-04 | Un solo medio de pago por venta: no existe pago mixto (efectivo + SINPE, etc.). | Hoy un pago mixto obliga a partir la venta en dos o a anotarlo mal, y el arqueo no cuadra. También lo va a pedir la factura electrónica. | **Alta** | M | `ventas/models.py:81` (`medio_pago` único) |
| VEN-05 | El POS carga la lista de productos al abrir la pantalla y no la vuelve a pedir. Lo que se ingresa después, o lo que el sistema tiene en 0, no se puede escanear: sale "No encontré ese producto", aunque el producto sí exista. | Con mucha mercadería sin ingresar, el cajero no puede vender lo que tiene en la mano y el mensaje lo confunde. | Media | S-M | `ventas/views.py:45-51`; `templates/ventas/pos.html:521-524` |
| VEN-06 | Descuentos: solo por línea y en %, sin descuento al total. Cajero hasta 15 % y regalía hasta ₡5.000 sin autorización; el gerente sin tope. Queda registrado (%, monto y quién vendió), pero si vende un gerente no queda separado "quién autorizó". | Regla de negocio por confirmar (pregunta 8). El registro existe. | Media | S | `ventas/services.py:34, 42, 145-174`; `ventas/models.py:136-141` |
| VEN-07 | La ayuda del POS dice "descuento en colones", pero el campo es un porcentaje. | Un cajero que escribe 500 pensando en ₡500 tendría un rechazo o un descuento del 100 %. | Baja | S | `templates/ventas/pos.html:224` vs `:436` |
| VEN-08 | IVA: el precio incluye IVA y se desglosa por línea con redondeo a 2 decimales. Si un producto no tiene tarifa se usa 13 %. **La tarifa aplicada no se guarda en la línea de venta**: solo se guardan los totales de la factura. | Si mañana cambia la tarifa de un producto, las ventas viejas ya no se pueden desglosar por tarifa (el contador y la factura electrónica lo necesitan). | Media | M | `ventas/services.py:45-54`; `ventas/models.py:131-143` |
| VEN-09 | Tarifas: según `data/CABYS_PARA_EL_CONTADOR.xlsx` (298 productos), **todos están al 13 %**. Hay asignaciones CABYS dudosas: "Collares isabelinos" como *collar con insecticida*; "Salud y cuidado › Entrenamiento / Higiene dental / Accesorios" como *medicamentos de uso veterinario*. 31 con confianza baja y 169 media. | Si una tarifa o un CABYS está mal, se cobra y se declara mal. **Por confirmar con el contador** (no supongo tarifas). | Media | S (revisión) | `data/CABYS_PARA_EL_CONTADOR.xlsx`; `catalogo/cabys.py` |
| — | ✅ Venta atómica: factura + inventario + caja + asiento se guardan juntos o nada. | — | OK | — | `ventas/services.py:57` (`@transaction.atomic`); prueba `test_venta_sin_stock_revienta_completa` |
| — | ✅ Última unidad con dos cajas a la vez: bloqueo por fila; nunca queda negativo. **Verificado en PostgreSQL** con dos ventas simultáneas. | — | OK | — | `inventario/services.py:41`; restricción `stock_no_negativo` en `catalogo/models.py:152` |
| — | ✅ Anulaciones y devoluciones: solo gerente, motivo obligatorio, queda quién y cuándo. | — | OK | — | `ventas/views.py:234-288`; `ventas/models.py:89-92, 189-192` |

### B. Tiquete

| Código | Qué falla | Por qué importa | Sev. | Esf. | Evidencia |
|---|---|---|---|---|---|
| TIQ-01 | El tiquete térmico imprime la hora en UTC (hora de Londres): 6 horas adelantada. La prueba existente usa una fecha "sin zona", por eso no lo detectó. | Comprobante con hora falsa frente al cliente y ante un reclamo. **Verificado:** 08:30 a. m. → imprime "02:30 PM". | **Alta** | S | `impresion/tiquete.py:152`; `impresion/tests.py:79` |
| TIQ-02 | Si el agente de impresión falla, el cajero no se entera: el POS dice "Tiquete enviado a la impresora". | Pasó de verdad: el 24/09 los tiquetes **FV-00000048 y FV-00000049** no salieron (impresora "sin conexión") y la pantalla dijo que sí. | **Alta** | M | `ventas/views.py:116-133`; `templates/ventas/pos.html:492-497`; `logs/agente_impresion.txt` (24/09 14:16 y 14:25) |
| TIQ-03 | No hay "Reimprimir" ni "Enviar por correo" en la pantalla de cobro después de vender. En el historial (Actividad) tampoco hay enlace al tiquete; solo el gerente la ve y muestra las últimas 40 ventas, sin buscador. | Para reimprimir hay que saber la dirección web del tiquete. Pierde tiempo con el cliente enfrente. | Media | S-M | `templates/ventas/pos.html:485-505`; `templates/core/actividad.html:86-107`; `core/views.py:64-67` |
| TIQ-04 | Formato: el tiquete no muestra el cajero, el efectivo recibido ni el vuelto, ni la tarifa de IVA. La versión en pantalla muestra montos sin formato ("₡5300.00"). Sí tiene: logo, nombre, cédula jurídica, sucursal, fecha, número, medio de pago, detalle, descuentos, IVA y total. | Datos que usted pidió y que ayudan en reclamos y arqueos. | Media | S | `impresion/tiquete.py:140-199`; `templates/ventas/tiquete.html:24-47` |
| TIQ-05 | 58 mm: se puede configurar (`ANCHO_TIQUETE=32`, `TIQUETE_PAPEL_PUNTOS=384`), pero no hay prueba para ese ancho. | Solo importa si compran una de 58 mm. | Baja | S | `config/settings.py:474, 501-504` |
| TIQ-06 | Correo del recibo: se manda por SMTP a Office 365 (puerto 587). **No pude verificar que funcione en DigitalOcean**: DigitalOcean suele bloquear el correo tradicional (SMTP) y la imagen del servidor no instala Chromium, así que en la nube el recibo sale sin PDF. Si el servidor no tiene la clave del correo configurada, la pantalla dice "enviado" **sin mandar nada**. Lo bueno: el correo va en otra pantalla, así que **no bloquea la venta**. | Cliente sin recibo y nadie se entera. **Por confirmar:** mándese un recibo a usted mismo desde el ERP en la nube. Recomiendo un servicio de correo transaccional que envíe por internet normal (no SMTP), en segundo plano. El precio de cada servicio está por confirmar. | Media | M | `config/settings.py:423-444`; `Dockerfile` (sin Chromium); `ventas/views.py:186-231`; `core/pdf.py` |
| — | ✅ Impresión automática sin cuadro de diálogo: ya está resuelta con el **agente de impresión** que corre en la computadora de la tienda (no depende del navegador). No hace falta el modo kiosco de Chrome. | — | OK | — | `impresion/servicio.py`; `_agente_impresion.py` |
| — | ✅ Numeración consecutiva: se toma con bloqueo y dentro de la misma operación de la venta. Si la venta falla, el número no se gasta (sin huecos ni repetidos). | — | OK | — | `ventas/models.py:51-58`; `ventas/services.py:96` |

### C. Inventario

| Código | Qué falla | Por qué importa | Sev. | Esf. | Evidencia |
|---|---|---|---|---|---|
| INV-01 | No hay **carga masiva de mercadería** (Excel/CSV con vista previa de errores) desde la pantalla. Solo existen comandos técnicos (`cargar_compra_19_09`, `importar_inventario`, `sincronizar_inventario`) que se corren con `.bat` y la contraseña de la base. Ya existe en el ERP un modelo que se puede reutilizar: "Completar catálogo" (sube Excel, muestra cada cambio y guarda solo al confirmar). | Es la prioridad de ustedes: mucha mercadería pendiente. Hoy depende de un técnico. | **Alta** | M-L | `catalogo/management/commands/`; patrón en `catalogo/views.py:152-195` y `catalogo/completar.py` |
| INV-02 | Productos creados en "Recibir mercadería" reciben código de barras "NP…" de 20 caracteres en vez del EAN-8 interno que empieza con 2. **Contradice su decisión.** (Los creados desde el admin sí reciben el código correcto.) | Según la prueba en papel del 06/09, un código tan largo no lo lee la pistola en la etiqueta de 35 mm. **Verificado:** "NP260926143018718065" contra "20000035" desde el admin. | **Alta** | S | `compras/views.py:300-304`; `catalogo/models.py:171-176` |
| INV-03 | "Recibir mercadería" guarda la compra en dos pasos separados (crear y después recibir). Si el segundo falla, queda una compra "borrador" suelta con número gastado. | Compras fantasma y números salteados en compras. | Media | S | `compras/views.py:214-223` |
| INV-04 | Nada impide ingresar **dos veces la misma factura de proveedor** (por ejemplo, Francisco desde el celular y usted desde la computadora). | Stock y deuda con el proveedor duplicados. | Media | S | `compras/models.py:47`; `compras/services.py:29-76` |
| INV-05 | Ajustes: el motivo es obligatorio y queda quién lo hizo (bien), pero es texto libre: no hay tipo (merma, daño, vencido, conteo). No hay conteo físico por lote. | Sin tipo no se puede sumar "cuánto perdimos por daño este mes". | Media | S-M | `inventario/forms.py:35-38`; `inventario/views.py:28-63` |
| INV-06 | No existe fecha de vencimiento ni lote: no hay alertas de productos por vencer. | Solo importa si venden alimento o medicamento con vencimiento (pregunta 9). | Media | M-L | no hay campo en `catalogo/models.py` ni en `inventario/models.py` |
| INV-07 | Kárdex por producto: existe, pero solo las últimas 50 filas, dentro de "Precios" (solo gerente) y con el título "Historial de costo". La lista completa está en el admin. | Buscar un movimiento viejo cuesta. | Baja | S | `catalogo/views.py:85-88`; `inventario/admin.py:14-33` |
| INV-08 | Etiquetas: se imprimen por producto o por hoja de categoría, pero después de "Recibir mercadería" no hay botón "imprimir etiquetas de esta compra". | Al ingresar una compra grande hay que buscar producto por producto. | Media | S | `templates/compras/nueva.html:708-712` |
| INV-09 | No hay escaneo con la cámara del celular. | Francisco ingresa inventario fuera de la tienda sin pistola. | Media | M | ninguna plantilla usa la cámara |
| INV-10 | El código de barras no tiene restricción de "único". Si dos productos terminan con el mismo código (por una importación), el POS toma el primero. | Venta del producto equivocado a otro precio. | Baja | S | `catalogo/models.py:96` |
| INV-11 | Stock mínimo = 2 para todo el catálogo. Existe además el reporte de reposición por velocidad de venta (bien) y la alerta en el Inicio. | Poco útil sin ajustar; el reporte de reposición ya lo compensa. | Baja | S | `catalogo/models.py:143`; `core/dashboard.py:150` |
| — | ✅ Costo: promedio ponderado, recalculado solo con entradas con costo; el margen se calcula sin IVA. Correcto. Pendiente con el contador (ya anotado en HALLAZGOS.md): si el costo de compras viejas se anotó con o sin IVA. | — | OK | — | `inventario/services.py:51-57`; `catalogo/models.py:209-243` |
| — | ✅ Crear/editar producto con marca, peso, foto, precio y código: existe (admin y "Recibir mercadería"); ambas pantallas se adaptan al celular. El costo no se edita a mano (solo por entradas), a propósito. | — | OK | — | `catalogo/models.py:90-143`; `templates/compras/nueva.html:99, 145` |

### D. Caja y contabilidad

| Código | Qué falla | Por qué importa | Sev. | Esf. | Evidencia |
|---|---|---|---|---|---|
| CAJ-01 | No hay **exportación a Excel** para el contador (ventas, compras, libro diario, IVA). Solo se exportan el catálogo y los CABYS. | El contador tiene que copiar a mano desde la pantalla, o pedirle a usted. | **Alta** | M | búsqueda de `openpyxl`: solo `catalogo/` |
| CAJ-02 | El arqueo cuenta solo el efectivo. Tarjeta y SINPE no se comparan contra el cierre del datáfono ni contra el estado de SINPE. | Un SINPE que "dijeron que mandaron" y no llegó no se detecta. | Media | M | `caja/services.py:49-70`; `caja/views.py:31-53` |
| CAJ-03 | Cada usuario abre **su propia** caja. Si usted y Francisco venden desde el mismo cajón de dinero, hay dos arqueos sobre una misma gaveta y ninguno cuadra. | Diferencias de caja que no son robo ni error, pero lo parecen (pregunta 7). | Media | S-M | `caja/services.py:12-33` |
| CAJ-04 | Reportes que faltan: ventas por día/semana/mes con gráfico, ventas por categoría, productos menos vendidos. **Ya existen:** más vendidos, stock, valor del inventario, reposición, diferencias de arqueo, medios de pago del día, estado de resultados (utilidad bruta) e IVA mensual. | Decisiones de compra sin datos por categoría. | Media | M | `core/urls.py:10-20`; `core/reportes.py`; `contabilidad/urls.py` |
| — | ✅ **Cuadre verificado** con datos de ejemplo (3 ventas en efectivo, tarjeta y SINPE con descuento, 1 anulación, 1 devolución): efectivo en caja = ventas en efectivo − devoluciones (₡8.290 = ₡8.290); unidades vendidas = salidas del kárdex; contabilidad debe = haber (₡54.140). | — | OK | — | prueba de verificación (fuera del repositorio) |

### E. Usuarios, control y seguridad

| Código | Qué falla | Por qué importa | Sev. | Esf. | Evidencia |
|---|---|---|---|---|---|
| USU-01 | **El repositorio de GitHub `oviquez-sys/allpetcr-erp` es público** (verificado hoy con GitHub) y tiene la carpeta `_respaldo_traslado` (735 MB, 9.162 archivos): 2 copias `db.dump` y 3 `.zip` de la base del 09/09/2026. El índice de las copias incluye las tablas de usuarios (`auth_user`), llaves de la API (`authtoken_token`), sesiones, clientes, ventas, pedidos y chat. También están `data/INVENTARIO REAL AL 6-7-2026 2.0.xlsx` y `PRODUCTOS_SIN_EXISTENCIA.xlsx`, con costos. Subido en el commit `fddc5a1` (09/09). **No abrí los datos**, solo la lista de tablas. | Datos personales de clientes (Ley 8968, por confirmar con asesoría legal), contraseñas que se pueden intentar adivinar y la llave del sitio web → alguien podría entrar al ERP o crear pedidos falsos. Los costos quedan a la vista de la competencia. | **Crítica** | S (cerrar) + M (limpiar historial) | `git ls-files _respaldo_traslado`; consulta a la API de GitHub: `visibility=public` |
| USU-02 | Respaldos: la documentación describe 3 capas (DigitalOcean 7 días, copia diaria al bucket, copia a su OneDrive). **Desde el código no se puede confirmar** que el respaldo automático de DigitalOcean esté encendido. La última prueba de restauración documentada es del **02/09/2026, en la base local, antes de mudarse a la nube**. No hay evidencia de una restauración probada de un respaldo de la nube. | Un respaldo que nunca se restauró es una suposición. | **Alta** | S (proceso) | `resultado_restauracion.txt`; `CLAUDE.md` (sección Respaldos) |
| USU-03 | Roles: Gerente, Cajero y Contador existen. Cajero no anula, no devuelve, no ajusta, no recibe mercadería; descuento hasta 15 %. Pero si usted y Francisco son superusuarios (no lo puedo ver sin entrar a producción), no tienen ningún tope ni control cruzado. | Para dos socios está bien; para el primer empleado hay que crearle usuario "Cajero", no de gerente. | Media | S | `core/roles.py:28-44`; `ventas/views.py:97-99` |
| USU-04 | Sesión de 12 horas que se renueva con cada acción: no hay cierre por inactividad corta. Varios dispositivos a la vez sí se permiten. | Una computadora de la tienda desatendida queda abierta. **Relacionado con SEC-004, que está en pausa: no lo toco sin su permiso.** | Baja | S | `config/settings.py:68-69` |
| — | ✅ Configuración de producción: `check --deploy` sin advertencias en modo producción; DEBUG se apaga solo; HTTPS obligatorio, cookies seguras, HSTS; la llave secreta, la base y el correo se leen de variables, no del código. **No puedo ver** las variables reales cargadas en DigitalOcean. | — | OK | — | `config/settings.py:17-51` |
| — | ✅ Bitácora: ventas, anulaciones, devoluciones, caja, compras, productos, precios y asientos quedan con usuario, IP y fecha. Cada cambio de precio queda firmado. | — | OK | — | `core/signals.py:47-64`; `catalogo/models.py:246-269` |

### F. Facilidad de uso, calidad y pruebas

| Código | Qué falla | Por qué importa | Sev. | Esf. | Evidencia |
|---|---|---|---|---|---|
| UX-01 | **La web esconde los agotados** de las listas y del menú. Solo se ven como "Sin existencias" si alguien entra con el enlace directo del producto. **Contradice su decisión** ("un agotado sigue visible como agotado"). No lo cambié. | Clientes que buscan un producto que se agotó creen que no lo venden. | Media | S | `api/views.py:70-71` (esconde por defecto); `allpetcr-web/lib/data.ts:110` (no pide los agotados) |
| UX-02 | Pruebas automáticas: **636 pruebas**. Las 186 de ventas, caja, compras y contabilidad pasan. De las otras 450, **16 fallan en su computadora** porque dan por hecho una máquina sin impresoras; aquí hay impresoras instaladas. No es un fallo del ERP, pero la suite nunca queda "en verde" en la PC de la tienda. | Una suite que siempre tiene fallos "normales" enseña a ignorarlos. | Baja | S | `impresion/tests.py` (clases `ColaDeImpresion` y `PuertasDelAgente`) |
| UX-03 | Pruebas que faltan justo donde encontré fallos: anular después de una devolución, doble envío, hora real del tiquete, código de barras de un producto nuevo, dos cajas a la vez (funciona, pero no hay prueba permanente). | Sin esas pruebas, los mismos errores pueden volver. | Media | S | `ventas/tests.py`, `impresion/tests.py`, `compras/tests.py` |
| UX-04 | En esta computadora faltaba instalar `whitenoise` (está en `requirements.txt` desde el 09/09): 171 pruebas fallaban por eso. **Lo instalé hoy** en el entorno local (no toca código). | Probar localmente daba un resultado falso. | Baja | — | `requirements.txt` |
| UX-05 | Celular y tablet: el POS y "Recibir mercadería" se reacomodan debajo de 900 px. Anular usa ventanas del navegador (`prompt`/`alert`): funciona, pero se ve rústico. | — | Baja | S | `templates/ventas/pos.html:146-166`; `templates/core/actividad.html:221-229` |
| UX-06 | Mensajes de error: en general son claros y en español ("Stock insuficiente de…", "Toda regalía necesita un motivo"). Excepciones: "No encontré ese producto" cuando el producto sí existe (VEN-05) y "Datos de venta inválidos" cuando el producto se desactivó. | — | Baja | S | `ventas/views.py:103-104` |
| — | Velocidad: el POS carga en la página todo lo que tiene existencia (~200 a 530 productos) y dibuja como máximo 150 tarjetas con miniaturas livianas. Con el tamaño actual del catálogo está bien. | — | OK | — | `templates/ventas/pos.html:333-353` |

---

## 3. Preparación para la factura electrónica (no se implementa ahora)

Lo que hoy impediría emitir comprobantes electrónicos. Los requisitos exactos de Hacienda están **por confirmar**
con el contador y con el Anexo de Estructuras oficial.

| Código | Qué falta | Evidencia |
|---|---|---|
| FE-01 | **Legal, no técnico:** la empresa está como régimen tradicional y hoy no emite comprobante electrónico en ninguna venta. Confirmar con el contador la obligación y la fecha, y cómo cumplir mientras tanto. | `HALLAZGOS.md` (20/09/2026); `templates/ventas/tiquete.html:54-55` |
| FE-02 | Datos de la empresa: faltan código de actividad económica, dirección por provincia/cantón/distrito, teléfono y correo del emisor, y número de establecimiento y terminal. | `core/models.py:6-35` |
| FE-03 | Cliente: falta el tipo de identificación (física, jurídica, DIMEX…) y la ubicación. En el POS no se puede crear un cliente rápido (cédula + correo) al cobrar: la lista solo trae los existentes. | `ventas/models.py:9-25`; `templates/ventas/pos.html:194` |
| FE-04 | Línea de venta: no guarda tarifa ni código de impuesto, CABYS ni unidad de medida **al momento de la venta** (ver VEN-08). | `ventas/models.py:131-143` |
| FE-05 | Un solo medio de pago por venta (ver VEN-04). | `ventas/models.py:81` |
| FE-06 | Anulación y devolución no generan el equivalente a una nota de crédito. Con factura electrónica, un comprobante aceptado no se "anula": se corrige con una nota de crédito. El modelo ya existe en `facturacion_electronica`, pero no está conectado. | `ventas/services.py:217`; `ventas/devoluciones.py`; `facturacion_electronica/models.py:142` |
| FE-07 | Numeración: hoy "FV-00000001". Hacienda usa una numeración propia (con establecimiento y terminal). Ya existe `numero_interno` para relacionarlas; falta armar esa relación. | `facturacion_electronica/models.py:69` |
| FE-08 | CABYS: 297 de 298 asignados, varios dudosos (ver VEN-09). Falta que el contador los revise. | `data/CABYS_PARA_EL_CONTADOR.xlsx` |
| FE-09 | Llave criptográfica (.p12), usuario de la API de Hacienda y XSD oficiales: pendientes (ya anotado en `CLAUDE.md`, pendiente 5). | `CLAUDE.md` |

---

## 4. Preguntas de negocio para Oscar

Van en orden de urgencia. Cada una tiene mi recomendación.

1. **Repositorio público (USU-01).** ¿Lo pone privado hoy? Son 2 clics en GitHub (Settings → Danger Zone →
   Change visibility) y tiene que hacerlo usted, porque es su cuenta. Después hay que cambiar la contraseña de todos
   los usuarios del ERP y generar una llave nueva para el sitio web; eso lo hago yo con su permiso.
   *Recomendación: sí, hoy mismo, antes que cualquier otra cosa.*
2. **Borrar esas copias del historial de GitHub.** Ponerlo privado no borra lo que alguien ya haya descargado, pero
   sí evita nuevas descargas. Para quitarlas del historial hay que reescribirlo (no se puede deshacer en GitHub; en
   su computadora las copias se conservan y además se sacan de Git para que no se vuelvan a subir).
   *Recomendación: sí, después de ponerlo privado.*
3. **Factura electrónica (FE-01).** ¿El contador le dijo desde qué fecha tienen que entregar comprobante electrónico,
   y cómo lo están haciendo mientras tanto? *Recomendación: preguntarle esta semana; eso define si la Etapa 5 se
   adelanta.*
4. **Anular vs. devolver (VEN-01).** ¿Quién puede anular y hasta cuándo? *Recomendación: anular solo el mismo día y
   solo si la venta no tiene devoluciones; todo lo demás, como devolución.*
5. **Vuelto (VEN-03).** ¿Quiere que el cajero escriba con cuánto paga el cliente y el sistema calcule el vuelto (y
   lo imprima en el tiquete)? *Recomendación: sí, con Enter = "pagó exacto", para no agregar pasos.*
6. **Pago mixto (VEN-04).** ¿Pasa seguido que un cliente pague parte en efectivo y parte por SINPE o tarjeta?
   *Recomendación: sí implementarlo, con hasta 3 medios por venta.*
7. **Cajón de dinero (CAJ-03).** ¿Usted y Francisco usan el mismo cajón cuando venden en la tienda?
   *Recomendación: una caja por cajón físico, compartida por quien esté vendiendo, y cada venta sigue firmada con
   el usuario que la hizo.*
8. **Descuentos (VEN-06).** ¿Le sirve el tope de 15 % para un cajero? ¿Quiere descuento al total de la venta (por
   ejemplo, "10 % a cliente frecuente")? *Recomendación: mantener 15 % y agregar el descuento al total con el mismo
   tope.*
9. **Vencimientos (INV-06).** ¿Venden o van a vender alimento o medicamentos con fecha de vencimiento?
   *Recomendación: si la respuesta es sí, pedir la fecha solo en esos productos al recibir mercadería; si es no,
   no agregarlo.*
10. **Agotados en la web (UX-01).** Hoy la web los esconde de las listas. ¿Mantiene su decisión original de
    mostrarlos como "agotado"? *Recomendación: mostrarlos al final de cada categoría, con el botón "avisarme cuando
    llegue" que ya existe.*

---

## 5. Plan por etapas

Una etapa a la vez. Cada cambio lleva su prueba automática. Al final de cada etapa le entrego una lista de "cómo
probarlo usted mismo" y espero su confirmación.

**Etapa 0 — Limpieza y proteger los datos (inmediata).**
Limpieza de archivos sin uso (primera tarea que usted pidió para la Fase 2). Sacar de Git `_respaldo_traslado` y
los Excel con costos **sin borrarlos de su computadora**, y agregarlos a `.gitignore`. Con su permiso (preguntas 1
y 2): cambiar contraseñas, generar una llave nueva para la API y limpiar el historial. Probar una restauración de un
respaldo de la nube en una base de ensayo (USU-02).

**Etapa 1 — Que la plata y el inventario no se descuadren.**
VEN-01 (anular con devoluciones), VEN-02 (doble cobro), TIQ-01 (hora del tiquete), INV-02 (código de barras de
productos nuevos, y convertir los que ya tengan código "NP…"), INV-03 (compra en dos pasos), INV-04 (factura de
proveedor duplicada), TIQ-02 (avisar en el POS si el tiquete no salió) y las pruebas de UX-02/UX-03.

**Etapa 2 — Mostrador más rápido.**
VEN-03 (vuelto), VEN-04 (pago mixto), TIQ-03 (reimprimir y enviar desde la misma pantalla y desde el historial,
con buscador), TIQ-04 (cajero, vuelto e IVA en el tiquete), VEN-05 (catálogo del POS al día y mensaje claro),
TIQ-06 (correo por un servicio transaccional, en segundo plano), VEN-07.

**Etapa 3 — Ingreso de mercadería.**
INV-01 (carga masiva desde Excel con vista previa), INV-08 (etiquetas de la compra recién ingresada), INV-05
(tipos de ajuste), INV-09 (cámara del celular), INV-06 (solo si la pregunta 9 es "sí"), INV-10.

**Etapa 4 — El contador y los reportes.**
CAJ-01 (exportar a Excel), CAJ-04 (reportes por período y por categoría), CAJ-02 (arqueo de tarjeta y SINPE),
CAJ-03 (según la pregunta 7).

**Etapa 5 — Dejar listos los datos para la factura electrónica (sin emitir todavía).**
FE-02 a FE-07 y VEN-08. Antes de cualquier migración que toque datos existentes, confirmo que hay un respaldo
reciente.

---

## 6. Limpieza

Hecha como primera tarea de la Fase 2. Después de la limpieza se corrieron las 636 pruebas: el resultado fue el
mismo que antes (solo las 16 de impresión que dependían de la computadora, arregladas después en la Etapa 1).

**Eliminados de Git** (commit `3a69622`, "limpieza: archivos sin uso"; se recuperan con Git):

| Archivo | Por qué |
|---|---|
| `manta_3x2.html` | Diseño de la manta publicitaria de 3×2 m. Ninguna vista, plantilla ni comando del ERP lo usa. |
| `_comparar_etiqueta.py` | Script de una sola vez (08/09). Ningún `.bat` ni módulo lo llama. |

**Sacados de Git pero conservados en su computadora** (commit `78d3af6`; se agregaron a `.gitignore`). No son
basura: son respaldos y datos. Salieron del repositorio porque es **público**:

| Archivo | Qué es |
|---|---|
| `_respaldo_traslado/` (735 MB) | Copias completas de la base del 09/09 (`db.dump`, `.zip`) |
| `db.sqlite3.DESCARTADA-vacia-20260722` | Base vieja: tiene 1 usuario y los costos de 184 productos |
| `data/INVENTARIO REAL AL 6-7-2026 2.0.xlsx` | Excel del inventario inicial, con costos |
| `data/DEPURACION_NOMBRES.xlsx`, `PRODUCTOS_SIN_EXISTENCIA.xlsx` | Listas de trabajo con datos del inventario |

**Movidos a `_PAPELERA_REVISAR/`** (no estaban en Git; ya está en `.gitignore`). Bórrela usted cuando confirme
que todo funciona:

| Archivo | Por qué |
|---|---|
| 26 × `resultado_*.txt` | Salidas viejas de los `.bat`. Cada `.bat` las vuelve a crear cuando se usa. |
| `Recibo-prueba.html`, `Recibo-prueba.pdf` | Pruebas del recibo en PDF (01/09) |
| `ziP6XwC3` | ZIP con archivos de imprenta de la manta publicitaria |
| `_to_delete/APLICAR.txt` | Instrucciones viejas (16/08) que ya se aplicaron |
| `data/.fuse_hidden0000000e00000001` | Copia temporal que dejó un programa al guardar un Excel |

**Dudosos, no se tocaron.** ¿Los borro o se quedan?

| Archivo | Duda |
|---|---|
| `_respaldo_20260825_2333/`, `_respaldo_previo_claude/` | Son respaldos de código (regla: no se tocan). Ya no están en Git. |
| `db.sqlite3` (vacío) | Lo usa el ERP si se arranca sin PostgreSQL. |
| `CARGAR_COMPRA_19_09.bat`, `CORREGIR_CATEGORIAS*.bat`, `BORRAR_SIN_EXISTENCIA.bat`, `aplicar_mejoras.bat`, `SINCRONIZAR_TODO.bat`, `INSTALAR_ARREGLO_CORREO.bat` | Parecen de una sola vez, pero son `.bat` suyos (regla: no se tocan). |
| `AUDITORIA_*.md`, `AUDITORIA-PENDIENTES.md`, `prompt_maestro_auditoria_v2.md` | Documentos viejos de auditoría. Sirven de historia. |
| Carpetas `__pycache__` | Caché de Python: se regenera sola, no molesta. |

Nota: `resultado_restauracion.txt`, citado en USU-02, ahora está en `_PAPELERA_REVISAR/`.

---

## 7. Cómo se hizo esta auditoría y sus límites

- Leí modelos, servicios, vistas, plantillas, URLs, configuración y pruebas de `allpetcr-erp`, y la llamada del
  sitio web a la API (`allpetcr-web/lib/data.ts`). El resto del sitio web no se auditó.
- Corrí las 636 pruebas del proyecto contra una base PostgreSQL **temporal** en esta computadora.
- Escribí 6 pruebas de verificación **fuera del repositorio** (carpeta temporal) para confirmar VEN-01, VEN-02,
  TIQ-01, INV-02, la concurrencia y el cuadre. No quedaron en el proyecto.
- **No entré a producción** ni a DigitalOcean: todo lo que depende de allá (variables, respaldos automáticos,
  correo, usuarios reales) está marcado "por confirmar".
- El tiempo de venta es un estimado leyendo el código, no una medición en la tienda.
- Único cambio en la computadora: instalé `whitenoise` en el entorno local de Python (ya estaba en
  `requirements.txt`).
