# Auditoría UX/UI — ALLPETCR ERP

**Fecha:** 22 de julio de 2026
**Rol:** diseñador UX/UI senior, ERP moderno 2026
**Método:** lectura directa del HTML/CSS real de cada pantalla del sistema — no capturas, no supuestos. Cada hallazgo cita el archivo. No se tocó código en esta fase.

> Nota de honestidad: no puedo tomar capturas de pantalla reales del sistema corriendo en tu computadora (no tengo acceso visual a tu navegador). Todo lo que sigue está basado en leer el código fuente de cada pantalla — HTML, CSS, JS — que es exactamente lo que el navegador renderiza. Es una fuente confiable, pero si algo se ve distinto en tu pantalla a lo que describo, avisame.

---

## 0. El hallazgo más importante, antes que nada

El sistema **no tiene un solo nivel de calidad — tiene dos.** Y la brecha entre ambos es grande.

**Nivel A (excelente, ERP SaaS moderno):** Inicio, Vender (POS), Recibir mercadería, Actividad y reversas.
**Nivel B (aceptable, con estilo propio pero inconsistente):** Balance, Estado de resultados, IVA trimestral, Libro diario, Cierres.
**Nivel C (crudo, formulario de Django sin ningún diseño):** Abrir caja, Cerrar caja, Ajuste de inventario, Precios, **Estado de cuenta de crédito (fiado)**.

Esto no es un detalle menor: un cajero pasa del POS —pulido, con tarjetas, gradientes, animaciones— a "Abrir caja" —una tabla HTML gris sin ningún estilo— **en el mismo flujo, con un clic de diferencia**. Ese contraste es lo primero que un usuario nota, aunque no sepa explicar por qué. Es el patrón "una empresa construyó esto con cuidado, pero se quedó a mitad de camino" — y es precisamente lo que un ERP comercial (Odoo, Dynamics) nunca deja ver.

---

## 1. Primera impresión

**¿Parece profesional?** En las pantallas de Nivel A, sí — mucho. El Inicio en particular (`core/dashboard.html`) tiene un tablero tipo bento con degradés de marca, tarjetas con sombra en capas, un gráfico de tendencia con Chart.js, y microinteracciones (hover que levanta las tarjetas, animaciones suaves). Esto compite visualmente con un SaaS moderno real.

**¿Genera confianza?** Sí, en las pantallas buenas — los indicadores del dashboard, el monitor de RTS, las alertas automáticas transmiten "este sistema sabe lo que hace". En las pantallas de Nivel C, no — una tabla gris con `<input type="submit" class="default">` genera la sensación opuesta: "esto se rompió a medio hacer" o "es un sistema viejo".

**¿Moderno o antiguo?** Depende literalmente de qué botón tocaste. Y ese "depende" es el problema central de esta auditoría.

---

## 2. Diseño visual

**Colores de marca:** bien resueltos donde se aplicaron — el azul marino (#0B3161) y el dorado (#CD963A/#E0B24E) están en variables CSS reutilizadas (`--brand`, `--gold`) en el sistema de diseño compartido (`allpetcr.css`) y en el Inicio. El problema no es que falten los colores de marca; es que **cada pantalla define su propia paleta por separado** en vez de compartir una sola fuente. Encontré `--brand:#0B3161` declarado de forma independiente en al menos 5 archivos distintos (`dashboard.html`, `pos.html`, `compras/nueva.html`, `actividad.html`, y otra vez dentro de `allpetcr.css`). Si mañana cambiás el azul de marca, hay que tocarlo en cinco lugares, no en uno — y es fácil que alguno quede desactualizado.

**Tipografía:** consistente donde se aplicó (SF Pro / -apple-system, buena elección, se ve nativa y limpia). En las pantallas de Nivel C no hay tipografía definida — heredan la fuente por defecto del admin de Django, que es una sans-serif genérica, notablemente distinta.

**Espaciados:** generosos y con buen "aire" en el Nivel A (paddings de 24-40px, gaps de 14-20px). En el Nivel C, el espaciado es el que Django trae de fábrica para formularios de admin — apretado, sin jerarquía.

**Tamaños de botones:** en el POS, los botones de cobro son grandes y táctiles (`padding:17px 6px`), pensados para dedo/mouse rápido — correcto para un punto de venta. En Nivel C, los botones son el `<input class="default">` estándar de Django — chicos, sin considerar que un cajero los toca muchas veces al día.

**Jerarquía visual:** fuerte en Nivel A (títulos grandes, subtítulos discretos, tarjetas que agrupan información relacionada). En Nivel C, todo tiene el mismo peso visual — un `<h1>` de admin, texto plano, sin agrupación.

**Consistencia entre pantallas: esta es la calificación más baja de toda la auditoría.** No es que falte una buena base de diseño — existe, y es buena (`allpetcr.css`). El problema es que no se aplicó de forma pareja: unas pantallas la usan, otras la reinventan con su propio `<style>` inline, y otras no tienen ningún estilo.

---

## 3. Dashboard principal (Inicio)

Esta es la joya del sistema, y con razón — es donde más esfuerzo de diseño se invirtió.

**¿La información importante está visible?** Sí. En un solo vistazo (sin scroll en pantallas grandes): estado de caja, ventas de hoy, ganancia del mes con margen, ventas del mes vs. mes anterior, efectivo en caja, total por cobrar (fiado), gráfico de tendencia de 7 días, top 5 productos vendidos, accesos rápidos a las 11 funciones principales.

**¿Los indicadores son útiles?** Muy. Especialmente el monitor del Régimen Simplificado (RTS) — es un indicador que **ningún ERP genérico traería de fábrica**, porque es específico de la ley costarricense. Eso es una ventaja competitiva real frente a Odoo o cualquier ERP importado: le está diciendo al dueño, en su propio idioma fiscal, cuándo se acerca a un límite legal.

**Qué cambiaría para decisiones más rápidas:**
- El "Margen del mes" y "Ganancia del mes" están en tarjetas separadas del gráfico de ventas; un administrador que quiere ver "¿estoy ganando o perdiendo terreno?" tiene que conectar mentalmente 3-4 números distintos. Una sola tarjeta con ambas cifras superpuestas (ventas vs. costo, con el margen como resultado) sería más rápida de leer.
- No hay comparación visual entre sucursales (aplica solo si en el futuro hay más de una).
- Las "Sugerencias" (consejos automáticos) son textuales — funcionan, pero en un ERP 2026 moderno normalmente se resuelven con un solo botón de acción directo desde la alerta (ej.: "Stock bajo" → botón "Generar orden de compra" ahí mismo), no solo texto descriptivo.
- No hay forma de personalizar qué tarjetas ve cada usuario (el dashboard es fijo). Los ERP modernos (2026) tienden a dashboards configurables por rol o por preferencia.

---

## 4. Catálogo de productos

Acá hay una división clara según dónde se edite el producto:

**Desde el POS (para vender):** presentación excelente — tarjetas cuadradas con imagen real del producto, categoría como chip de color, precio grande y legible, indicador de "quedan X" en tiempo real, y las que no tienen stock se ven atenuadas y no son clickeables. Búsqueda instantánea (filtra mientras escribís, sin recargar) y chips de categoría para explorar sin escribir. Esto es del nivel de un POS comercial real.

**Desde "Precios" (`catalogo/precios.html`), para revisar/ajustar precio:** el contraste no podría ser mayor. Es una tabla HTML sin ningún estilo de tarjeta — bordes grises (`#ddd`, `#eee`), un `<h1>Precios</h1>` plano, sin agrupación visual, sin filtros más allá de un buscador de texto simple. No hay miniatura destacada, no hay indicador de margen (¿este precio deja buena ganancia o mala?), no hay ordenar por columna.

**Facilidad para editar información:** el flujo de edición completa de un producto pasa por el panel de administración de Django (`/admin/catalogo/producto/`), que ya mejoramos visualmente en la sesión anterior (tarjetas, chips). Es funcional pero sigue siendo, en esencia, un formulario de administración técnica — no una "ficha de producto" pensada para un dueño de tienda sin conocimientos técnicos.

**Lo que falta, comparado con un catálogo ERP 2026:** vista de cuadrícula con miniaturas en la lista de administración (hoy es una tabla con columnas de texto), edición rápida de precio sin entrar al formulario completo, indicador visual de margen por producto, y una búsqueda con autocompletado/sugerencias en "Precios" como sí existe en el POS.

---

## 5. Inventario

**Claridad de existencias:** buena en el Inicio (tabla de "stock bajo" con miniatura de producto, cantidad actual vs. mínimo, en un chip rojo bien visible) y en el POS (el número "quedan X" en cada tarjeta se actualiza al vender). Pero el **kardex completo** (historial de movimientos) vive dentro del panel de administración estándar de Django — una tabla de datos técnica, sin gráfico de tendencia de stock, sin filtro visual rápido por tipo de movimiento.

**Alertas de bajo inventario:** presentes y bien resueltas — aparecen en el Inicio automáticamente, con conteo (`{{ num_stock_bajo }}`) y detalle. Punto a favor real.

**Movimientos:** el registro es sólido a nivel de datos (lo confirmé en la auditoría técnica: kardex inmutable, trazable), pero la pantalla para **hacer un ajuste manual** (`inventario/ajuste.html`) es la definición de Nivel C — literalmente `{{ form.as_table }}` sin ningún estilo, la tabla de campos de Django por defecto. Es la pantalla que un gerente usaría para corregir un error de conteo — un momento donde la claridad importa, y es la más pobre visualmente de todo el sistema junto con "Abrir caja".

**Facilidad de uso diario:** la entrada rápida de mercadería desde la ficha de producto (`+ Registrar entrada / compra`) está muy bien resuelta — formulario corto, tarjeta redondeada, foto del producto, mismo lenguaje visual de marca. Es la prueba de que cuando se invirtió el esfuerzo, el resultado es muy bueno; el problema es que no se invirtió parejo en todas las pantallas.

---

## 6. Ventas / POS

**Velocidad para vender:** alta. Flujo típico: escanear código de barras (o buscar) → el producto se agrega solo, con Enter → tocar el medio de pago → listo, tiquete se abre automático. Para un producto ya conocido por código de barras, son literalmente **2 acciones** (escanear + tocar el botón de pago). Eso es excelente para un punto de venta de alto tráfico.

**Cantidad de clics:** para una venta simple en efectivo con productos conocidos por código de barras: escanear (Enter automático) × N productos, + 1 clic en "Efectivo". Muy competitivo — a la par de un POS comercial dedicado.

**Facilidad para un empleado nuevo:** hay una ayuda contextual (botón flotante "?" con los 4 pasos básicos) directamente en la pantalla de venta, y otra en el Inicio explicando el flujo completo del día. Es una buena práctica de onboarding que muchos ERP no tienen — reduce la dependencia de que alguien "enseñe" al nuevo empleado.

**Lo que le falta a un POS 2026:** no vi soporte de teclado numérico en pantalla para dispositivos táctiles sin teclado físico, no hay modo "oscuro" para ambientes de poca luz, y — el hallazgo más serio de esta sección — **el layout está fijo en dos columnas con un ancho fijo de 440px para el carrito**, sin ninguna adaptación para pantallas angostas (ver sección 8, Móvil). En una tablet chica o un teléfono, esta pantalla se rompe.

---

## 7. Módulos administrativos

**Compras:** la recepción de mercadería (`compras/nueva.html`) está en Nivel A — muy bien resuelta, mismo lenguaje visual que el POS. Buena noticia porque es una pantalla de uso frecuente.

**Caja:** aquí está el contraste más incómodo del sistema. Abrir caja y Cerrar caja —las dos acciones que **todo cajero hace todos los días, sin excepción**— son ambas Nivel C: formularios crudos de Django, sin ningún diseño. Es, literalmente, la peor experiencia visual del sistema aplicada a la tarea más repetida. Cerrar caja además tiene una responsabilidad importante (el arqueo ciego, comparar el conteo físico contra el esperado) que merecería una interfaz que transmita "este número importa", no una tabla gris.

**Contabilidad:** aquí el nivel es más parejo y bueno — Balance de comprobación, Estado de resultados, IVA trimestral y Libro diario tienen todos su propia tarjeta con sombra, tipografía numérica alineada (`font-variant-numeric:tabular-nums`, un detalle correcto y poco común de ver en sistemas caseros), y mensajes de estado con color (verde si cuadra, rojo si no). Es un módulo bien cuidado, aunque cada reporte reinventa su propia clase CSS (`.bal-card`, `.er-card`, etc.) en vez de compartir un componente común — otra vez el problema de consistencia, aunque acá el resultado visual final sí es aceptable.

**Reportes:** cubiertos por los mismos módulos contables de arriba. No encontré un "centro de reportes" unificado — cada reporte es una URL separada que hay que conocer o llegar por el menú de accesos rápidos del Inicio.

**El más urgente de arreglar en esta sección:** **Estado de cuenta del cliente** (`ventas/estado_cuenta.html`) — la pantalla donde se cobra el fiado (crédito) a un cliente. Es HTML absolutamente sin estilo: ni siquiera tiene su propio bloque `<style>`, cosa que ninguna otra pantalla del sistema comparte al 100%. Un formulario de cobro de dinero real, sin ningún cuidado visual, es la señal más contradictoria de todo el sistema — porque es dinero, y el resto del sistema sí cuida mucho el dinero (el diseño del POS y el dashboard lo demuestran).

---

## 8. Experiencia móvil

Este es un hallazgo objetivo, no de opinión: **busqué `@media` (la técnica estándar para adaptar diseño a pantallas chicas) en las 24 plantillas del sistema. Solo 3 la usan**, y de esas 3, dos son para impresión (etiquetas de código de barras y el tiquete de venta), no para celular.

**La única pantalla con adaptación real a celular es el Inicio** (`core/dashboard.html`, con un `@media(max-width:768px)` que reduce el tablero a menos columnas). El sistema de diseño compartido (`allpetcr.css`) — la fuente que en teoría debería garantizar consistencia — **no tiene ni un solo `@media`**, así que cualquier pantalla nueva construida sobre él tampoco se adaptará a menos que alguien lo agregue a mano cada vez.

**Las pantallas de mayor uso diario tienen el problema más serio:**
- **POS** (`pos.html`): `main{display:grid;grid-template-columns:1fr 440px}` — un ancho fijo de 440px para el carrito. En un celular de 375-414px de ancho (el tamaño típico), **la columna del carrito sola ya no cabe en la pantalla**. No es una cuestión de "se ve apretado" — literalmente se corta o exige scroll horizontal.
- **Recibir mercadería** (`compras/nueva.html`): mismo patrón, `1fr 400px` fijo, mismo problema.

**Conclusión de esta sección:** hoy el sistema es, en la práctica, **de escritorio/tablet grande únicamente**. Si algún empleado quisiera vender desde un celular como caja de respaldo, o el dueño quisiera revisar el Inicio desde el teléfono en la calle, el Inicio funcionaría razonablemente bien — pero el POS, la pantalla más importante del negocio día a día, no.

---

## A) Lo que está bien actualmente

El sistema de diseño base (`allpetcr.css` + el estilo del Inicio) es genuinamente de nivel profesional — paleta de marca real (muestreada del logo, no aproximada), tipografía tipo Apple, sombras en capas, animaciones sutiles de hover, gradientes de marca bien ejecutados. El Inicio, el POS y Recibir mercadería están al nivel de un SaaS moderno y podrían mostrarse sin vergüenza junto a un ERP comercial. La velocidad de venta en el POS es excelente — pocos clics, escaneo directo, ayuda contextual incorporada. El monitor de régimen fiscal (RTS) es un diferenciador real frente a ERP genéricos importados. Los reportes contables tienen buen cuidado tipográfico (números alineados, colores de estado). Los colores de marca son reales, extraídos del logo, no inventados.

## B) Problemas visuales encontrados

Inconsistencia severa entre pantallas — tres niveles de acabado visual conviviendo en el mismo sistema. Cinco pantallas (Abrir caja, Cerrar caja, Ajuste de inventario, Precios, Estado de cuenta/fiado) usan el formulario crudo de Django sin ningún diseño, incluyendo dos de las tareas más repetidas del día (abrir y cerrar caja) y una que maneja cobro de dinero real. El sistema de diseño compartido se reinventa parcialmente en cada pantalla en vez de reutilizarse (colores de marca duplicados en al menos 5 archivos). Cero adaptación móvil real fuera del Inicio; el POS específicamente se rompe en pantallas angostas por un ancho fijo de 440px. El catálogo de precios no muestra margen ni permite edición rápida. No hay un centro de reportes unificado — cada reporte contable vive en su propia URL sin un índice visual común.

## C) Cambios recomendados priorizados

**Críticos (afectan el uso diario, alta visibilidad, bajo riesgo técnico):**
Rediseñar Abrir caja y Cerrar caja con el mismo lenguaje visual del POS/Recibir mercadería — son las pantallas de mayor frecuencia de uso. Rediseñar Estado de cuenta (cobro de fiado) — maneja dinero real y hoy es la más pobre del sistema. Arreglar el POS para que no se rompa en pantallas angostas (al menos un layout de una sola columna en móvil).

**Importantes (elevan la percepción profesional, esfuerzo moderado):**
Rediseñar Ajuste de inventario y Precios con tarjetas y mejor jerarquía. Consolidar los colores de marca en un solo lugar (que `allpetcr.css` sea la única fuente, y que las demás pantallas lo importen en vez de redeclarar variables). Agregar indicador de margen en la vista de Precios. Unificar las clases de "tarjeta de reporte" (`.bal-card`, `.er-card`, etc.) en un solo componente reutilizable del sistema de diseño.

**Mejoras futuras (pulido, no urgente):**
Dashboard configurable por rol/preferencia. Botones de acción directa desde las alertas del Inicio (no solo texto). Centro de reportes unificado con índice visual. Modo oscuro para el POS. Vista de cuadrícula con miniaturas en la lista de productos del panel de administración.

## D) Propuesta de rediseño visual — ERP SaaS moderno 2026

La dirección de diseño ya existe y es correcta — no hay que inventar un estilo nuevo, hay que **terminar de aplicar el que ya se construyó** a las pantallas que quedaron atrás, y resolver los tres problemas estructurales (inconsistencia de fuente de diseño, ausencia de móvil, y la brecha de "dinero sin cuidado visual" en Estado de cuenta).

Concretamente, para verse como un ERP SaaS de 2026 de punta a punta: cada pantalla dentro de una tarjeta con sombra en capas y esquinas redondeadas (ya definido en `allpetcr.css` como `--radius-lg` y `--shadow`) en vez de tablas planas; formularios con inputs grandes, con foco resaltado en azul de marca (ya existe como patrón, solo falta aplicarlo en Caja/Ajuste/Estado de cuenta); botones tipo píldora consistentes en todo el sistema (ya existen en `.apx-btn`, faltan en Nivel C); una sola fuente de verdad para colores y tipografía en vez de variables repetidas; y un layout responsivo real — al menos que ninguna pantalla crítica (POS incluido) se rompa por debajo de 768px de ancho.

No hace falta un cambio de identidad visual — el logo, los colores de marca, la tipografía y el tono ya están bien definidos y ejecutados donde se aplicaron. El trabajo que sigue es de **nivelación**, no de reinvención.

---

*Este es el diagnóstico. No se modificó ningún archivo del sistema durante esta auditoría. Cuando definas qué priorizar, lo implementamos por partes — empezando por lo que marcaste como crítico, con verificación antes de cada cambio, igual que hicimos con el panel de administración.*
