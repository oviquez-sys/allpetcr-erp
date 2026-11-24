/* Catálogo de WhatsApp (24/11/2026): copiar el enlace para Meta y confirmar
 * antes de cambiarlo. Vive en /static y sin onclick= en la plantilla, para no
 * sumar trabajo el día que la CSP pase a modo estricto (core/seguridad.py).
 */
(function () {
  'use strict';

  document.querySelectorAll('[data-copiar]').forEach(function (b) {
    b.addEventListener('click', function () {
      var campo = document.getElementById(b.getAttribute('data-copiar'));
      if (!campo) return;
      var listo = function () {
        b.textContent = 'Copiado';
        setTimeout(function () { b.textContent = 'Copiar'; }, 1600);
      };
      var seleccionar = function () {
        campo.focus();
        campo.select();
        b.textContent = 'Seleccionado: Ctrl+C';
      };
      try {
        navigator.clipboard.writeText(campo.value).then(listo, seleccionar);
      } catch (err) {
        seleccionar();
      }
    });
  });

  document.querySelectorAll('form[data-confirmar]').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (!window.confirm(f.getAttribute('data-confirmar'))) e.preventDefault();
    });
  });
})();
