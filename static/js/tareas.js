/* Tareas del día (23/11/2026): marcar sin recargar la página.
 *
 * Cada marca es un formulario normal que funciona solo. Este archivo lo manda
 * en segundo plano y pinta el resultado. Si el envío en segundo plano falla
 * (sin señal, sesión vencida), manda el formulario de la forma normal: la
 * página se recarga, pero la marca no se pierde.
 *
 * Vive en /static y sin onclick= en la plantilla, para no sumar trabajo al día
 * que la CSP pase a modo estricto (ver core/seguridad.py).
 */
(function () {
  'use strict';

  var ultimoBoton = null;
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button[type="submit"]') : null;
    if (b) ultimoBoton = b;
  }, true);

  function poner(el, texto) {
    if (el) el.textContent = texto;
  }

  function pintarFila(li, datos) {
    li.setAttribute('data-estado', datos.estado);

    var circ = li.querySelector('.ta-circ');
    var alterno = li.querySelector('.ta-check input[name="estado"]');
    var hecha = datos.estado === 'HEC';
    if (circ) {
      circ.setAttribute('aria-pressed', hecha ? 'true' : 'false');
      circ.setAttribute('aria-label', (hecha ? 'Quitar la marca de hecha: ' : 'Marcar como hecha: ') +
        (circ.getAttribute('data-titulo') || ''));
    }
    if (alterno) alterno.value = hecha ? 'PEN' : 'HEC';

    li.querySelectorAll('.ta-estados button[name="estado"]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.value === datos.estado ? 'true' : 'false');
    });

    var linea = '';
    if (datos.estado !== 'PEN') {
      linea = datos.estado_texto + (datos.quien ? ' por ' + datos.quien : '') + (datos.cuando ? ' · ' + datos.cuando : '');
    }
    poner(li.querySelector('.ta-m-est'), linea);
  }

  function pintarDia(c) {
    if (!c) return;
    var texto = document.getElementById('ta-avance-texto');
    if (texto) {
      var b = texto.querySelector('b');
      var previo = '';
      // Conserva el «Oscar: » del filtro, si lo hay: es texto antes del <b>.
      if (b && b.previousSibling && b.previousSibling.nodeType === 3) previo = b.previousSibling.textContent;
      texto.textContent = '';
      if (previo) texto.appendChild(document.createTextNode(previo));
      var fuerte = document.createElement('b');
      fuerte.textContent = c.hechas + ' de ' + c.total;
      texto.appendChild(fuerte);
      var resto = c.total === 1 ? ' hecha' : ' hechas';
      if (c.no) resto += ' · ' + c.no + (c.no === 1 ? ' no se hizo' : ' no se hicieron');
      texto.appendChild(document.createTextNode(resto));
    }
    var ok = document.getElementById('ta-bar-ok');
    var no = document.getElementById('ta-bar-no');
    var pct = function (n) { return c.total ? Math.round(n * 100 / c.total) : 0; };
    if (ok) ok.style.width = pct(c.hechas) + '%';
    if (no) no.style.width = pct(c.no) + '%';
    var mini = document.querySelector('.ta-dia[aria-current="page"] .ta-mini i');
    if (mini) mini.style.width = pct(c.hechas) + '%';
  }

  function enviarNormal(form, boton) {
    if (boton && boton.name) {
      var oculto = document.createElement('input');
      oculto.type = 'hidden';
      oculto.name = boton.name;
      oculto.value = boton.value;
      form.appendChild(oculto);
    }
    form.submit();
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.hasAttribute('data-borrar')) {
      if (!window.confirm('¿Borrar esta tarea? No se puede deshacer.')) e.preventDefault();
      return;
    }
    if (!form.hasAttribute('data-marcar') || !window.fetch || !window.FormData) return;

    e.preventDefault();
    var boton = e.submitter || ultimoBoton;
    var li = form.closest('.ta-t');
    var datos = new FormData(form);
    if (boton && boton.name && form.contains(boton)) datos.set(boton.name, boton.value);
    if (li) li.classList.add('ta-enviando');

    fetch(form.action, {
      method: 'POST', body: datos, credentials: 'same-origin',
      headers: { 'X-Requested-With': 'fetch' }
    }).then(function (r) {
      var tipo = r.headers.get('content-type') || '';
      if (!r.ok || tipo.indexOf('application/json') === -1) throw new Error('respuesta inesperada');
      return r.json();
    }).then(function (res) {
      if (!res.ok) throw new Error('no se guardó');
      if (li) {
        li.classList.remove('ta-enviando');
        pintarFila(li, res);
      }
      pintarDia(res.dia);
    }).catch(function () {
      if (li) li.classList.remove('ta-enviando');
      enviarNormal(form, form.contains(boton) ? boton : null);
    });
  });

  // «Copiar» al lado de cada enlace del detalle (el de la biografía de
  // Instagram, los de los anuncios): en el celular copiar un enlace largo
  // a mano es donde más se equivoca uno.
  document.querySelectorAll('.ta-detalle a[href^="https://"]').forEach(function (a) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'ta-copiar';
    b.textContent = 'Copiar';
    b.addEventListener('click', function () {
      var listo = function () {
        b.textContent = 'Copiado';
        setTimeout(function () { b.textContent = 'Copiar'; }, 1600);
      };
      var seleccionar = function () {
        var rango = document.createRange();
        rango.selectNodeContents(a);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(rango);
        b.textContent = 'Seleccionado';
      };
      try {
        navigator.clipboard.writeText(a.href).then(listo, seleccionar);
      } catch (err) {
        seleccionar();
      }
    });
    a.insertAdjacentElement('afterend', b);
  });
})();
