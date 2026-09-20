/* Fotos de producto en todo el ERP (20/09/2026).
 *
 * 1. Si una miniatura no carga, se pide al respaldo /foto/<id>/, que la
 *    genera y redirige. Si eso también falla, queda la huella 🐾 en vez de
 *    un ícono de imagen rota.
 * 2. Clic en una foto con clase "clickable-product-img" → se amplía con la
 *    foto GRANDE (data-grande), no con la miniatura.
 * 3. window.fotoHTML(p, tam, clase): la misma foto para las pantallas que
 *    se dibujan en JavaScript (POS, Recibir, Etiquetas, chat). `p` trae
 *    {miniatura, imagen, respaldo, nombre} — ver core/imagenes.datos_foto.
 */
(function () {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function vacia(tam, clase) {
    var r = Math.max(6, Math.floor(tam / 5));
    return '<span class="foto-prod vacia ' + esc(clase || '') + '" style="width:' + tam + 'px;height:' + tam +
      'px;border-radius:' + r + 'px;font-size:' + Math.max(12, Math.floor(tam / 2)) + 'px" title="Sin foto">🐾</span>';
  }

  // tam = número (px) o null para que ocupe el contenedor (tarjetas del POS).
  window.fotoHTML = function (p, tam, clase) {
    clase = clase || '';
    var fluida = !tam;
    var t = tam || 64;
    if (!p || !p.miniatura) {
      if (fluida) return '<span class="foto-prod vacia ' + esc(clase) + '" style="width:100%;height:100%;font-size:40px" title="Sin foto">🐾</span>';
      return vacia(t, clase);
    }
    var estilo = fluida ? 'width:100%;height:100%;border-radius:inherit'
      : 'width:' + t + 'px;height:' + t + 'px;border-radius:' + Math.max(6, Math.floor(t / 5)) + 'px';
    return '<img class="foto-prod ' + esc(clase) + '" src="' + esc(p.miniatura) + '" data-grande="' + esc(p.imagen) +
      '" data-respaldo="' + esc(p.respaldo) + '" alt="' + esc(p.nombre) + '" loading="lazy" decoding="async" style="' + estilo + '">';
  };

  // Los errores de <img> no burbujean: se escuchan en fase de captura.
  document.addEventListener('error', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG' || !img.classList.contains('foto-prod')) return;
    if (img.dataset.respaldo && !img.dataset.reintento) {
      img.dataset.reintento = '1';
      img.src = img.dataset.respaldo;
      return;
    }
    var span = document.createElement('span');
    span.className = 'foto-prod vacia';
    span.title = 'La foto no se pudo cargar';
    span.textContent = '🐾';
    span.style.cssText = img.style.cssText + ';font-size:' + Math.max(12, Math.floor((img.clientWidth || 40) / 2)) + 'px';
    img.replaceWith(span);
  }, true);

  function modal() {
    var m = document.getElementById('productImgModal');
    if (m) return m;
    m = document.createElement('div');
    m.id = 'productImgModal';
    m.className = 'product-img-modal';
    m.innerHTML = '<button type="button" class="product-img-modal-close" aria-label="Cerrar">×</button>' +
      '<img id="productImgModalContent" alt=""><div class="cap"></div>';
    m.addEventListener('click', function (ev) {
      if (ev.target === m || ev.target.classList.contains('product-img-modal-close')) m.classList.remove('open');
    });
    document.body.appendChild(m);
    return m;
  }

  document.addEventListener('click', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG' || !img.classList.contains('clickable-product-img')) return;
    e.preventDefault();
    e.stopPropagation();
    var m = modal();
    var grande = m.querySelector('img');
    grande.src = img.dataset.grande || img.src;
    var cap = m.querySelector('.cap');
    if (cap) cap.textContent = img.alt || '';
    m.classList.add('open');
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      var m = document.getElementById('productImgModal');
      if (m) m.classList.remove('open');
    }
  });
})();
