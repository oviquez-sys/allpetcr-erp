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
 *
 * TERCER CAMBIO (20/10/2026, pedido de Oscar: un buscador "inteligente"):
 * "comida perro cachorro" no encontraba nada, porque ningún alimento dice
 * "comida" y la mitad dice "Puppy". Ahora cada producto viaja con
 * `etiquetas`: las palabras que la gente usaría para encontrarlo, en
 * español e inglés, armadas en el servidor (catalogo/palabras_clave.py, la
 * ÚNICA lista de sinónimos). Acá además:
 * - se ignoran tildes y mayúsculas ("pequeño" = "pequeno"),
 * - se ignoran palabras vacías ("comida PARA perro"),
 * - "cachorros" también busca "cachorro",
 * - cada palabra se busca al INICIO de una palabra del producto, para que
 *   "res" no encuentre "fresko" ni "pato" encuentre "zapatos".
 * Misma regla que catalogo/palabras_clave.coincide (chat y Precios).
 */
var UNIDADES_DE_PESO = ["kg", "g", "lb", "oz", "ml", "l"];
var ESPACIO_ENTRE_NUMERO_Y_UNIDAD = new RegExp("(\\d)\\s+(" + UNIDADES_DE_PESO.join("|") + ")\\b", "gi");
var PALABRAS_VACIAS = ["para", "de", "del", "con", "el", "la", "los", "las", "y", "en", "un", "una",
  "unos", "unas", "mi", "su", "al", "que", "por", "o", "a"];

function normalizarPeso(texto) {
  return (texto || "").replace(ESPACIO_ENTRE_NUMERO_Y_UNIDAD, "$1$2");
}

function textoPlano(texto) {
  var t = String(texto || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  return normalizarPeso(t.replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim());
}

function variantes(palabra) {
  var v = [palabra];
  if (palabra.length > 4 && /es$/.test(palabra) && !/ses$/.test(palabra)) v.push(palabra.slice(0, -2));
  if (palabra.length > 3 && /s$/.test(palabra)) v.push(palabra.slice(0, -1));
  return v;
}

function coincideTodasLasPalabras(texto, campos) {
  var palabras = textoPlano(texto).split(" ").filter(function (w) {
    return w && PALABRAS_VACIAS.indexOf(w) === -1;
  });
  if (!palabras.length) return true;
  var todo = " " + textoPlano(campos.join(" "));
  return palabras.every(function (palabra) {
    return variantes(palabra).some(function (v) { return todo.indexOf(" " + v) !== -1; });
  });
}
