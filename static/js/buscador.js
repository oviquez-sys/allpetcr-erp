/* Búsqueda de producto por palabras sueltas, del lado del navegador.
 * ---------------------------------------------------------------------------
 * Antes cada pantalla (POS, Recibir mercadería, Etiquetas) comparaba la
 * frase completa, tal como se escribe, contra cada campo por separado. Eso
 * funciona para "tazón" o "10kg", pero no para dos palabras: "balance 10kg"
 * no aparece como texto seguido en "Balance Adulto Raza Pequeña 10kg", así
 * que la búsqueda no encontraba nada (28/09/2026, pedido de Oscar — le
 * costaba etiquetar el alimento Balance y Nutri por esto mismo).
 *
 * Ahora cada palabra que se escribe se busca por separado, y puede caer en
 * CUALQUIERA de los campos del producto (no todas en el mismo campo), pero
 * TODAS las palabras escritas tienen que aparecer en alguno. Es el mismo
 * criterio que ya usa el chat de ayuda para "buscar_producto"
 * (core/chat_tools.py) — se llevó ese mismo criterio a estas tres pantallas
 * para que buscar se sienta igual en todas partes.
 *
 * Ejemplo: escribir "balance 10kg" encuentra "Balance Adulto Raza Pequeña
 * 10kg" (las dos palabras están en el nombre, en cualquier orden) y también
 * encontraría un producto donde "balance" esté en el nombre y "10kg" solo
 * en la descripción.
 */
function coincideTodasLasPalabras(texto, campos) {
  const palabras = (texto || "").toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (!palabras.length) return true;
  const valores = campos.map((c) => (c || "").toLowerCase());
  return palabras.every((palabra) => valores.some((v) => v.includes(palabra)));
}
