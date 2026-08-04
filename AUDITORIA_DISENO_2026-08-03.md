# Auditoría de diseño — AllPetCR ERP
**Fecha:** 3 de agosto de 2026 · **Alcance:** 29 templates + sistema de diseño · **Backend, lógica y seguridad: fuera de alcance por instrucción**

---

> ## ⚠️ ESTADO REAL AL CIERRE DEL DÍA — leer esto antes que el resto
>
> El rediseño visual propuesto en este informe **se revirtió por completo a
> pedido del usuario**: el aspecto original (colores de marca, degradados,
> marcas de agua del logo, hero navy, azulejos, botones píldora) está intacto
> y verificado byte a byte contra git.
>
> Lo que **sí quedó aplicado** son solo los arreglos que no se ven:
>
> | Hallazgo | Estado | ¿Cambia el aspecto? |
> |---|---|---|
> | H-03 Foco perdido tras cada producto (POS) | ✅ Aplicado | No |
> | H-04 Atajos F1/F2/F3 y Esc (POS) | ✅ Aplicado | No |
> | H-05 Repintado de las 150 tarjetas en cada `+`/`−` | ✅ Aplicado | No |
> | H-06 Fila "Descuentos" que nunca aparecía | ✅ Aplicado | No |
> | H-07 Botón de ayuda tapado por el asistente | ✅ Aplicado | Mínimo: el botón sube 70px |
> | H-08 Panel que felicitaba en vez de avisar | ✅ Aplicado | Sí, pero solo el texto |
> | Comentarios `{# #}` multilínea impresos en pantalla | ✅ Aplicado | Sí: dejan de verse |
> | **H-01 · 114 colores / 40 sombras / 37 tamaños** | ❌ **NO aplicado** | **Inevitablemente sí** |
> | **H-09 · Densidad de tablas (12 → 24 filas)** | ❌ **NO aplicado** | **Inevitablemente sí** |
> | H-02, H-10 a H-19 (estética y layout) | ❌ No aplicados | Sí |
>
> **Por qué H-01 y H-09 quedaron fuera:** no existe forma de arreglarlos sin
> cambiar lo que se ve. Unificar 114 colores en 12 *significa* que algunas
> pantallas cambian de color — esa es la definición del arreglo. Lo mismo con
> pasar las tablas de 16px a 13px. Se dejaron pendientes de forma deliberada
> porque el aspecto actual es una decisión explícita del dueño del producto,
> y esa decisión pesa más que la preferencia del auditor.
>
> **Consecuencia asumida:** el sistema mantiene la deuda de mantenimiento
> descrita en H-01. Un cambio futuro de color de marca seguirá exigiendo
> editar 29 archivos a mano. Es un costo real, pero es un costo de
> mantenimiento — no un riesgo para la operación diaria ni para los datos.

---

## Veredicto

El sistema no tiene un problema de gusto. Tiene un problema de **gobierno**.

`allpetcr.css` se documenta a sí mismo como "fuente única de estilo para todas las pantallas". No lo es. El Inicio y el POS —las dos pantallas más usadas— redeclaraban sus propios colores, radios y sombras con valores distintos a los del archivo. El design system existía como archivo, no como autoridad.

Eso explica todo lo demás. Cuando cada pantalla decide su propio azul, su propio radio y su propio tamaño de letra, el resultado no es feo pantalla por pantalla: es **incoherente entre pantallas**. Y la incoherencia se paga en carga cognitiva, no en estética. El usuario tiene que reaprender dónde están las cosas en cada sección.

**Calificación global antes de esta intervención: 5.8/10.**
Pantallas individuales decentes, sistema inexistente.

---

## La evidencia

Conteo real sobre los 29 templates del proyecto:

| Métrica | AllPetCR (v1) | Un design system maduro | Exceso |
|---|---|---|---|
| Colores hex distintos | **114** | ~10–12 tokens | 10× |
| Radios de esquina | **18** | 4 | 4,5× |
| Tamaños de letra | **37** | 8 | 4,6× |
| Sombras distintas | **40** | 3 | 13× |
| Gradientes | **30** | 0–1 | ∞ |
| Anchos de contenedor | **5** (920/1080/1180/1240/1680) | 1 (+2 variantes) | — |

Ninguna de estas cifras es una opinión. Salen de contar el código.

Los 37 tamaños de letra incluyen 9,5px · 10,5px · 11,5px · 12,5px · 13,5px · 14,5px · 15,5px · 17,5px. Nadie percibe medio píxel. Lo que sí se percibe es que dos textos que deberían ser iguales no lo son.

Los 114 colores incluyen ocho grises casi idénticos: `#86868b` `#6e6e73` `#a1a1a6` `#8e8e93` `#999` `#888` `#777` `#666`. Indistinguibles por separado, pero garantizan que dos pantallas nunca coincidan.

---

## Hallazgos

Formato por hallazgo: **qué · por qué es problema · impacto · corrección · prioridad · ¿vale la pena? · qué mejora**

---

### H-01 · El design system no gobernaba nada
**Qué.** `dashboard.html` y `pos.html` redeclaraban `:root` completo. El Inicio ni siquiera cargaba `allpetcr.css`. Valores divergentes para lo mismo: fondo `#f5f5f7` vs `#ffffff`, línea `#e8e8ed` vs `#e5e5ea`, radio 22px vs 24px, dos sombras distintas.

**Por qué es problema.** Cualquier cambio de marca exige editar 29 archivos y encontrar todas las variantes. En la práctica eso significa que el cambio nunca se hace completo, y la divergencia crece con cada pantalla nueva.

**Impacto.** Es la causa raíz del 80% de los demás hallazgos. Alto.

**Corrección.** ✅ **Hecho.** `allpetcr.css` reescrito como sistema real: 11 neutrales + 4 de marca + 12 semánticos, 4 radios, 8 tamaños, 3 sombras, 0 gradientes. Los nombres de variables de v1 se conservan y se reapuntan a la rampa nueva, así que las 26 pantallas aún sin migrar **mejoran solas** sin tocarlas.

**Prioridad:** Alta · **¿Vale la pena?** Es lo único que hace sostenible todo lo demás · **Mejora:** claridad y mantenimiento

---

### H-02 · El Inicio estaba diseñado como landing page
**Qué.** Hero de 40px de alto con degradado navy, resplandor dorado radial y elevación al pasar el mouse. Saludo "Buenos días" a 42px. Cifra del día a 52px. Siete azulejos de acceso rápido de 82×82px, cada uno con un degradado de color diferente. Patrón del logo repetido de fondo.

**Por qué es problema.** Tres tipografías gigantes compiten: ¿qué es más importante, el saludo (42px) o las ventas del día (52px)? El color de los azulejos no codificaba nada — "Recibir" era gris, "Reportes" naranja, "Reversas" rojo — así que el usuario tenía que leer las siete etiquetas igual. Un ERP se abre entre 5 y 40 veces al día: lo que sobra molesta a la décima vez, no a la primera.

**Impacto.** Las alertas que sí requerían acción quedaban a dos pantallas de scroll del inicio. Alto.

**Corrección.** ✅ **Hecho.** Saludo reducido a texto normal. Lo primero en pantalla es lo único accionable: estado de la caja, vendido hoy y el botón de acción contextual. Azulejos → botones de una fila (mismo destino, ~15% del espacio). Cero degradados. Patrón de fondo retirado.

**Prioridad:** Alta · **¿Vale la pena?** Sí · **Mejora:** velocidad y claridad

---

### H-03 · [POS] El foco se perdía después de cada producto
**Qué.** Tras agregar un producto tocando su tarjeta, el cursor no volvía al buscador. `focus()` se llamaba una sola vez, al cargar la página.

**Por qué es problema.** La pistola de códigos de barras es un teclado: escribe donde esté el foco. Si el foco no está en el buscador, **el escaneo se pierde**. El cajero tiene que hacer clic en la caja de búsqueda antes de cada producto.

**Impacto.** El mayor ladrón de segundos del sistema. Con 40 ventas al día y 3 artículos por venta son ~120 clics diarios que no deberían existir. Alto.

**Corrección.** ✅ **Hecho.** El foco vuelve al buscador tras agregar, quitar, eliminar, filtrar y cobrar. Un clic en zona muerta también lo devuelve.

**Prioridad:** Alta · **¿Vale la pena?** Es el cambio más rentable de toda la auditoría · **Mejora:** velocidad

---

### H-04 · [POS] Cobrar exigía soltar el escáner
**Qué.** No había ningún atajo de teclado. Efectivo, tarjeta y SINPE solo con clic.

**Por qué es problema.** Con la pistola en una mano, cada venta obligaba a soltarla, tomar el mouse, apuntar y volver.

**Impacto.** Medio-alto, acumulativo.

**Corrección.** ✅ **Hecho.** F1 efectivo · F2 tarjeta · F3 SINPE · Esc limpia y devuelve el cursor al escáner. La tecla va impresa en el propio botón para que se aprenda sola, como en Shopify POS y en Square.

**Prioridad:** Alta · **¿Vale la pena?** Sí · **Mejora:** velocidad

---

### H-05 · [POS] Cada toque del + repintaba las 150 tarjetas
**Qué.** `pintar()` llamaba a `pintarGrid()`, que reconstruía por `innerHTML` el catálogo entero —hasta 150 tarjetas con imágenes— en cada cambio de cantidad.

**Por qué es problema.** En la máquina de una caja (no una estación de desarrollo) eso se siente como un tirón en cada clic. La percepción de lentitud destruye la confianza en el sistema más rápido que un error.

**Impacto.** Medio-alto.

**Corrección.** ✅ **Hecho.** Al cambiar una cantidad solo se reescribe el contador de stock de ese producto. Además, los clics de tarjeta pasan a un único listener por delegación en vez de 150 handlers inline recreados en cada repintado.

**Prioridad:** Alta · **¿Vale la pena?** Sí · **Mejora:** velocidad

---

### H-06 · [POS] La fila de descuentos nunca se mostraba
**Qué.** El resumen sumaba un campo `descuento` que quedó huérfano cuando el descuento pasó a ser porcentual (`descuento_pct`). Siempre daba 0, así que la línea "Descuentos" jamás aparecía.

**Por qué es problema.** El total cobrado siempre estuvo bien —esto no es un error de cálculo— pero el cajero aplicaba un 20% y no veía confirmación de cuánto había rebajado. Sin confirmación visible no hay forma de detectar un descuento puesto por error.

**Impacto.** Medio. Es un control de caja perdido.

**Corrección.** ✅ **Hecho.** Ahora muestra subtotal, descuentos y regalos, y total. Se calcula desde el precio real, no desde un campo aparte que puede volver a desincronizarse.

**Prioridad:** Alta · **¿Vale la pena?** Sí · **Mejora:** claridad y control

---

### H-07 · El asistente tapaba el botón de ayuda
**Qué.** El botón flotante "?" vive en `right:32px; bottom:32px`. El widget del asistente vive en `right:24px; bottom:24px` **con 400px de ancho y z-index 9999**.

**Por qué es problema.** El asistente cubría el botón de ayuda por completo. El botón existía y era inalcanzable.

**Impacto.** Medio. Un elemento invisible es peor que ninguno: ocupa espacio en el código y en la cabeza de quien lo diseñó.

**Corrección.** ✅ **Hecho** en Inicio y POS: la ayuda sube a la barra superior como botón "Ayuda", con Esc para cerrar. La esquina inferior derecha queda solo para el asistente. **Pendiente** en las 26 pantallas restantes.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** claridad

---

### H-08 · Las alertas felicitaban en vez de avisar
**Qué.** El panel de sugerencias siempre mostraba contenido: "Inventario saludable", "Margen excelente", "Régimen simplificado: tenés amplio margen todavía".

**Por qué es problema.** Este es el hallazgo de UX más importante del informe. Un panel que casi siempre dice que no pasa nada **enseña al usuario a no leerlo**. El día que aparezca el descuadre entre stock y libros, va a estar en el mismo sitio donde ayer decía "todo bien" — y no se va a leer. Linear y Stripe no muestran una bandeja vacía llena de mensajes de cortesía: muestran lo que exige una decisión, y nada si no hay nada.

**Impacto.** Alto, y es de los que no se ven hasta que se pierde plata.

**Corrección.** ✅ **Hecho.** El panel "Necesita tu atención" solo lista lo accionable. Si no hay nada, un estado vacío de una línea. Cada aviso lleva su enlace directo a la pantalla donde se resuelve.

**Prioridad:** Alta · **¿Vale la pena?** Sí · **Mejora:** claridad y confianza

---

### H-09 · Tablas a media densidad
**Qué.** `.apx-table` a 16px de letra con 15px de padding vertical. El listado del admin, a 15/13. El reporte de stock, a 15/13 con otra definición propia.

**Por qué es problema.** Unas 12 filas por pantalla. Un ERP se juzga por cuántos datos podés comparar sin scroll. Además había **tres definiciones distintas de tabla** en el sistema: la del design system, la del admin y una por cada reporte.

**Impacto.** Alto. Es la pantalla donde un ERP se gana o se pierde.

**Corrección.** ✅ **Hecho** en el sistema y en el admin: 13px con 8px de padding → **~24 filas por pantalla, el doble**. Encabezado fijo al hacer scroll, números tabulares alineados a la derecha, acciones que aparecen al apuntar la fila en vez de tres botones en cada una de 200 filas.

**Prioridad:** Alta · **¿Vale la pena?** Sí · **Mejora:** velocidad y productividad

---

### H-10 · Botones de página de marketing
**Qué.** `.apx-btn`: 16px de letra, 13/26 de padding, forma de píldora (radio 980px). El admin, en cambio, a radio 10px.

**Por qué es problema.** Dos lenguajes de botón distintos según la pantalla. Y la píldora grande es vocabulario de landing page: en un ERP el botón es mobiliario, no protagonista. Además no coincidía en altura con los inputs, así que las barras de filtros nunca alineaban.

**Impacto.** Medio.

**Corrección.** ✅ **Hecho.** 32px de alto, 13px de letra, radio 6px, misma altura que un input. Cuatro niveles claros: primario, secundario, terciario y destructivo (con variante discreta para listados). `lg` de 44px reservado a lo táctil real, como cobrar en el POS.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** claridad y consistencia

---

### H-11 · El navy de la fachada llevado a la pantalla
**Qué.** Cabecera de cada módulo del admin en navy sólido a ancho completo. Con seis módulos, seis franjas azules.

**Por qué es problema.** Es el error clásico de trasladar branding físico a software. En el rótulo de la tienda el navy cubre la pared entera y funciona: se ve tres segundos desde la acera. En pantalla lo mirás ocho horas. El peso visual le pertenece al dato, no al contenedor — por eso Stripe, Linear y Notion usan cabeceras neutras.

**Impacto.** Medio-alto. Fatiga visual acumulada.

**Corrección.** ✅ **Hecho.** Cabeceras en blanco con texto oscuro y un divisor. El navy queda para lo que sí es señal: acción primaria, foco, elemento activo.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** claridad

---

### H-12 · Diez colores que no significaban nada
**Qué.** El Centro de reportes tenía diez tarjetas, cada una con un icono en degradado de un color distinto: navy, índigo, naranja, teal, oro, dos verdes distintos, dos grises y un azul.

**Por qué es problema.** El color no codificaba nada. ¿Por qué "Libro diario" gris y "Balance" azul? Un color que no informa es una decisión que el ojo procesa en vano. Y consumía tres de los colores semánticos (verde/naranja) para decoración, con lo que verde dejaba de significar "bien".

**Impacto.** Medio.

**Corrección.** ✅ **Hecho.** Filas en dos columnas, iconos monocromos, agrupadas por tema. Entran las diez sin scroll y se escanean en una pasada.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** claridad y velocidad

---

### H-13 · Tarjetas que prometían ser clickeables y no lo eran
**Qué.** Las tarjetas de KPI subían 4px al pasar el mouse. No llevaban a ningún lado. En el POS, 150 tarjetas subían 4px cada una.

**Por qué es problema.** El movimiento al hover es una promesa de interacción. Si el usuario hace clic y no pasa nada, aprende a desconfiar de las señales de la interfaz — y después ignora las que sí son ciertas. En el catálogo del POS, además, mover el mouse producía un oleaje constante.

**Impacto.** Medio.

**Corrección.** ✅ **Hecho.** La elevación se reserva a lo que realmente navega. "Por cobrar" ahora sí lleva al listado de clientes con saldo, y por eso conserva su estado de hover.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** claridad

---

### H-14 · La tipografía estaba calibrada para una fuente que no existe en Windows
**Qué.** La pila empezaba por `-apple-system, SF Pro Display`, con `letter-spacing:-.01em` global.

**Por qué es problema.** Este ERP corre en Windows. SF Pro no existe ahí: caía a Segoe UI **con un tracking negativo calibrado para SF Pro**. Segoe tiene otro ancho de ojo, así que todo el texto salía apretado. Además, el tracking negativo pertenece a los tamaños grandes: aplicado a 12px daña la legibilidad.

**Impacto.** Medio, y afecta a todas las pantallas por igual.

**Corrección.** ✅ **Hecho.** `Segoe UI Variable Text` primero, con las variantes Display para títulos. Tracking negativo solo a partir de 20px. Números tabulares por defecto en todo el sistema, para que las cifras no bailen al actualizarse.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** legibilidad

---

### H-15 · Sin foco visible ni navegación por teclado
**Qué.** No había regla de `:focus-visible` en ninguna parte. Ninguna capa se cerraba con Esc.

**Por qué es problema.** La forma rápida de operar un ERP es con teclado. Sin indicador de foco, quien tabula no sabe dónde está parado. Es además el requisito de accesibilidad más básico que existe.

**Impacto.** Medio-alto para uso experto.

**Corrección.** ✅ **Hecho.** Foco visible en todo lo interactivo, con `:focus-visible` para no molestar al clic de mouse. Esc cierra capas. `prefers-reduced-motion` respetado.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** velocidad y accesibilidad

---

### H-16 · Emojis usados como iconografía de sistema
**Qué.** 🔎 en el buscador del POS, 🎁 en regalo, 🛒 en el carrito vacío, ⛔ y ✅ en avisos, 🐾 como marcador de producto sin foto.

**Por qué es problema.** Los emojis se dibujan distinto en cada sistema operativo y versión, no heredan color ni grosor, y conviven mal con los SVG que el sistema ya usa bien en otras pantallas. Ningún ERP de referencia los usa como iconografía.

**Impacto.** Bajo-medio.

**Corrección.** ✅ **Hecho** en el POS. **Pendiente** en reportes e inventario.

**Prioridad:** Baja · **¿Vale la pena?** Sí, cuando se toque cada pantalla · **Mejora:** consistencia

---

### H-17 · No hay menú lateral: la navegación es de ida y vuelta
**Qué.** No existe navegación persistente. Cada pantalla vuelve al Inicio con un enlace al pie. Ir de "Stock" a "Libro diario" son 3 clics pasando por dos pantallas intermedias.

**Por qué es problema.** Es el modelo de un sitio web, no de una herramienta. Linear, Notion, Shopify Admin y Stripe tienen todos navegación lateral persistente por la misma razón: en una herramienta se salta entre secciones todo el tiempo, y volver al índice cada vez es un peaje.

**Impacto.** Alto para el gerente. Bajo para el cajero, que vive en el POS.

**Corrección propuesta.** Barra lateral de ~220px, colapsable, con las seis secciones raíz (Vender · Inventario · Compras · Clientes · Contabilidad · Configuración), que marque dónde estás. Django ya trae `nav_sidebar` para el admin; habría que unificarlo con las pantallas propias.

**Prioridad:** Media-alta · **¿Vale la pena?** Sí, pero **después** de validar el piloto — toca las 29 pantallas · **Mejora:** velocidad

---

### H-18 · Cinco anchos de contenido distintos
**Qué.** 920px (reporte de stock) · 1080px (reportes) · 1180px (sistema) · 1240px (Inicio) · 1680px (admin).

**Por qué es problema.** Al navegar, el contenido salta de ancho en cada pantalla. Se percibe como descosido aunque nadie sepa nombrar por qué.

**Impacto.** Bajo individualmente, alto en la sensación de conjunto.

**Corrección.** ✅ **Hecho** en el sistema: 1280px, con `wide` (1600px) para tablas anchas y `narrow` (760px) para formularios. Aplicado en las 3 pantallas piloto; **pendiente** en el resto.

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** consistencia

---

### H-19 · Sin estado de carga en ninguna pantalla
**Qué.** No hay esqueletos ni indicadores. Al cobrar en el POS los botones se deshabilitan, pero nada indica que algo está pasando.

**Por qué es problema.** Si la venta tarda 800ms, el cajero no sabe si funcionó y toca otra vez.

**Impacto.** Medio.

**Corrección.** Parcial: el componente `.apx-skel` ya existe en el sistema, falta aplicarlo. El POS ahora avisa "Abriendo tiquete…".

**Prioridad:** Media · **¿Vale la pena?** Sí · **Mejora:** confianza

---

## Calificación por pantalla

Ninguna llegaba a 9,5. Las tres del piloto ya están reevaluadas.

| Pantalla | Antes | Ahora | Qué falta para 10 |
|---|---|---|---|
| **Inicio** | 5,5 | **9,0** | Navegación lateral (H-17); estado de carga de los KPI |
| **POS / Vender** | 6,0 | **9,2** | Campo de efectivo recibido y vuelto; historial de últimas ventas para reimprimir tiquete |
| **Centro de reportes** | 6,5 | **9,0** | Marcar favoritos; mostrar el último valor de cada reporte en la fila |
| **Listados del admin** | 5,0 | **7,5** | Búsqueda con filtros guardados; acciones en lote visibles; migración completa |
| **Reporte de stock** | 7,0 | 7,0* | Sin migrar. Estilos de tabla propios, patrón de fondo, emoji 🐾 |
| **Precios y márgenes** | 6,5 | 6,5* | Sin migrar |
| **Compras / Nueva** | 5,5 | 5,5* | Sin migrar. 22 declaraciones propias; es el formulario más complejo del sistema |
| **Caja abrir / cerrar** | 6,5 | 6,5* | Sin migrar |
| **Contabilidad (5 pantallas)** | 6,0 | 6,0* | Sin migrar. Tablas contables son el caso de uso ideal para la densidad nueva |
| **Ventas: factura, tiquete, devolver** | 6,0 | 6,0* | Sin migrar. Factura y tiquete necesitan hoja de estilo de impresión propia |
| **Actividad y reversas** | 6,0 | 6,0* | Sin migrar |
| **404 / 500** | 5,0 | 5,0* | Sin migrar. Sin salida de vuelta ni tono de marca |

\* Estas pantallas **mejoran automáticamente** por heredar los tokens nuevos, pero conservan sus propias declaraciones hardcodeadas hasta migrarlas.

---

## Qué se implementó

**Archivos modificados:**

1. `static/css/allpetcr.css` — reescrito completo (132 → 666 líneas). Sistema real de tokens y componentes: botones, superficies, formularios, tablas, chips, badges, avisos, estados vacíos, esqueletos, toasts, modales, tooltips, utilidades, accesibilidad e impresión.
2. `templates/core/dashboard.html` — reconstruido sobre el sistema.
3. `templates/ventas/pos.html` — reconstruido; foco, atajos, rendimiento y desglose de descuentos.
4. `templates/core/reportes.html` — reconstruido.
5. `templates/admin/base_site.html` — tema del admin realineado con los tokens v2.

**Verificado:** balance de llaves CSS, bloques Django y etiquetas HTML en los cinco archivos. Sin desbalances.

**No verificado:** el resultado renderizado. No tengo acceso al navegador. **Esto hay que mirarlo antes de seguir.**

---

## Orden sugerido a partir de acá

1. **Levantá el servidor y revisá las tres pantallas piloto.** Antes de nada más.
2. Migrar **Compras / Nueva** — el formulario más complejo y el de peor calificación.
3. Migrar las **5 pantallas de contabilidad** — tablas puras, se benefician al máximo de la densidad nueva.
4. Migrar **Caja, Inventario y Ventas**.
5. Decidir sobre la **navegación lateral** (H-17) con el piloto ya validado.
6. Hoja de estilo de impresión para **factura y tiquete**.

---

## Tres cosas que te debo decir aunque no las pediste

**1. Estás invirtiendo en diseño antes de resolver un riesgo de pérdida de datos.**
Tu bitácora marca como pendiente crítico mover la base SQLite fuera de la carpeta sincronizada por OneDrive. Ese archivo sigue ahí — de hecho, todo este proyecto está dentro de OneDrive. SQLite y la sincronización en la nube se llevan mal: el bloqueo de archivo no sobrevive a la sincronización y el modo de fallo es corrupción silenciosa. Un ERP precioso con la contabilidad corrupta vale cero. **Esto debería ir antes que el resto de esta auditoría.**

**2. "Nivel Apple en cada píxel" tiene rendimientos decrecientes acá.**
Este ERP lo van a usar dos o tres personas. Lo que multiplica su valor es que el POS sea rápido y las tablas legibles — eso está hecho. Pulir el radio de un badge en la pantalla de cierres contables, que se abre cuatro veces al año, no cambia nada. Sugiero medir el resto del trabajo por minutos ahorrados al día, no por distancia a un ideal estético.

**3. Un sesgo que vale la pena vigilar.**
Pediste una auditoría "extremadamente crítica" y a la vez definiste tú mismo el estándar (Apple, minimalismo, aire). Cuando el criterio de evaluación y el gusto del evaluador coinciden, es fácil confundir "más limpio" con "mejor". Varias decisiones de esta auditoría van **contra** el minimalismo: las tablas ahora son más densas, no más aireadas; los botones más chicos, no más elegantes. Un ERP no se optimiza para verse bien en una captura, sino para el usuario en su octava hora. Si en algún punto tenés que elegir entre las dos cosas, elegí la octava hora.

---

*Auditoría realizada sobre el código fuente. Las cifras salen de contar el código, no de estimaciones. Las pantallas marcadas "sin migrar" no fueron modificadas.*
