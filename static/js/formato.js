/* Formato de moneda de Costa Rica, del lado del navegador.
 * ---------------------------------------------------------------------------
 * Espejo exacto del filtro `crc` de core/templatetags/formato.py: punto para
 * los miles, coma para los decimales. Existe para que el mismo monto se vea
 * igual lo dibuje el servidor o lo dibuje JavaScript.
 *
 * POR QUÉ NO SE USA toLocaleString
 * --------------------------------
 * El POS y la pantalla de compras usaban `n.toLocaleString('es-ES')`, y por eso
 * un arnés de ₡4000 se veía "₡4000" mientras que uno de ₡12.500 sí llevaba
 * punto. No era un bug del código: el español de España define
 * `minimumGroupingDigits = 2` en el CLDR, o sea que sólo agrupa a partir de
 * cinco dígitos. 4000 se escribe "4000" y 12500 se escribe "12.500".
 *
 * Las salidas obvias tampoco sirven:
 *
 *   - 'es-CR' separa los miles con ESPACIO: "4 000". No es lo que se usa acá.
 *   - 'de-DE' sí da "4.000", pero apoyar el formato de la tienda en que el
 *     alemán casualmente se escribe igual es una coincidencia, no una regla:
 *     el día que cambie el CLDR o el navegador, cambian los precios del
 *     mostrador y nadie sabe por qué.
 *
 * Así que se formatea explícitamente. Son diez líneas, no dependen de la
 * configuración regional del equipo donde corra el navegador —que en una
 * tienda puede ser cualquiera— y hacen lo mismo que el servidor.
 */
(function (global) {
  "use strict";

  /* Agrupa la parte entera de miles en miles con punto. */
  function agruparMiles(entero) {
    return entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }

  /* Número -> "1.234.567,89"  (sin el símbolo de colón).
   *
   * maxDecimales: cuántos decimales COMO MÁXIMO. Los ceros finales no se
   * escriben: ₡4.000 y no ₡4.000,00, que es como se cotiza en el mostrador.
   */
  function numeroCRC(valor, maxDecimales) {
    var n = Number(valor);
    if (!isFinite(n)) return "";
    var d = (maxDecimales === undefined) ? 2 : maxDecimales;

    var negativo = n < 0;
    var texto = Math.abs(n).toFixed(d);

    var partes = texto.split(".");
    var entero = agruparMiles(partes[0]);
    var decimales = partes[1] || "";

    // Se recortan los ceros de la derecha; si no queda nada, no va coma.
    decimales = decimales.replace(/0+$/, "");

    return (negativo ? "-" : "") + entero + (decimales ? "," + decimales : "");
  }

  /* Lo mismo, con el símbolo adelante: "₡1.234.567,89". */
  function crc(valor, maxDecimales) {
    return "₡" + numeroCRC(valor, maxDecimales);
  }

  global.AllPetFormato = { numeroCRC: numeroCRC, crc: crc };
  // Alias corto: las plantillas ya llamaban `fmt` a esta función.
  global.fmt = crc;
})(window);
