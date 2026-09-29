/* Búsqueda de producto por palabras sueltas, del lado del navegador.
 * ---------------------------------------------------------------------------
 * Antes cada pantalla (POS, Recibir mercadería, Etiquetas) comparaba la
 * frase completa, tal como se escribe, contra cada campo por separado. Eso
 * fallaba con dos palabras sueltas: "balance 10kg" no aparece como texto
 * seguido en "Balance Adulto Raza Pequeña 10kg" (28/09/2026, pedido de
 * Oscar — le costaba etiquetar el alimento Balance y Nutri por esto mismo).
 *
 * Ahora cada palabra que se escribe se busca por separado, y puede caer en
 * CUALQUIERA de los campos del producto (no todas en el mismo campo), pero
 * TODAS las palabras escritas tienen que aparecer en alguno. Es el mismo
 * criterio que ya usa el chat de ayuda para "buscar_producto"
 * (core/chat_tools.py) — se llevó ese mismo criterio a estas tres pantallas
 * para que buscar se sienta igual en todas partes.
 *
 * SEGUNDO PROBLEMA, DISTINTO (mismo día): ni siquiera UNA sola palabra como
 * "10kg" encontraba nada, porque al cargar una compra el nombre del
 * producto se arma pegando marca + nombre de factura + presentación, y la
 * presentación siempre lleva un espacio entre el número y la unidad
 * ("Balance Ad Cat Chicken" + "10 kg"). "10kg" nunca es una subcadena de
 * "10 kg". `normalizarPeso` le saca ese espacio a ambos lados de la
 * comparación (al texto del producto y a lo que se escribió), así "10kg" y
 * "10 kg" se comparan como si fueran lo mismo, sin importar cuál de los dos
 * lo escribió con espacio.
 */
var UNIDADES_DE_PESO = ["kg", "g", "lb", "oz", "ml", "l"];
var ESPACIO_ENTRE_NUMERO_Y_UNIDAD = new RegExp("(\\d)\\s+(" + UNIDADES_DE_PESO.join("|") + ")\\b", "gi");

function normalizarPeso(texto) {
  return (texto || "").replace(ESPACIO_ENTRE_NUMERO_Y_UNIDAD, "$1$2");
}

function coincideTodasLasPalabras(texto, campos) {
  const palabras = normalizarPeso(texto).toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (!palabras.length) return true;
  const valores = campos.map((c) => normalizarPeso(c || "").toLowerCase());
  return palabras.every((palabra) => valores.some((v) => v.includes(palabra)));
}
