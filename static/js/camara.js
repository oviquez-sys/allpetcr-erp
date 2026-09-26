/* Escanear códigos de barras con la cámara del celular (auditoría 26/09/2026, INV-09).
 *
 * Francisco ingresa mercadería fuera de la tienda, sin la pistola. Chrome en
 * Android trae `BarcodeDetector`, que lee EAN-13, EAN-8 y Code128 sin
 * instalar nada. Donde no existe (la computadora de la caja, Safari), el botón
 * simplemente no aparece: ahí se usa la pistola, como siempre.
 *
 * Uso: activarCamara(inputDeBusqueda). Por defecto escribe el código en el campo y
 * simula el Enter de la pistola: la pantalla lo procesa igual que un escaneo.
 * Crea el botón 📷 al lado del campo y un <dialog> modal (Esc lo cierra).
 */
function activarCamara(input, alDetectar) {
  alDetectar = alDetectar || (codigo => {
    input.value = codigo;
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  });
  if (!('BarcodeDetector' in window) || !navigator.mediaDevices || !input) return;
  const boton = document.createElement('button');
  boton.type = 'button';
  boton.textContent = '📷';
  boton.title = 'Escanear con la cámara';
  boton.setAttribute('aria-label', 'Escanear con la cámara');
  boton.style.cssText = 'margin-left:8px;padding:0 14px;border-radius:12px;border:1px solid #d9d9de;background:#fff;font-size:22px;cursor:pointer;min-height:44px';
  input.insertAdjacentElement('afterend', boton);
  if (input.parentElement && getComputedStyle(input.parentElement).display !== 'flex') {
    const fila = document.createElement('div');
    fila.style.cssText = 'display:flex;align-items:stretch';
    input.parentElement.insertBefore(fila, input);
    fila.append(input, boton);
    input.style.flex = '1';
  }

  const dlg = document.createElement('dialog');
  dlg.style.cssText = 'border:none;border-radius:20px;padding:20px;max-width:420px;width:calc(100% - 32px)';
  dlg.innerHTML = '<h2 style="font-size:18px;margin:0 0 6px">Escanear con la cámara</h2>' +
    '<p style="font-size:13px;color:#6e6e73;margin:0 0 10px">Apunte al código de barras.</p>' +
    '<video playsinline muted style="width:100%;border-radius:12px;background:#000;aspect-ratio:4/3;object-fit:cover"></video>' +
    '<p class="err" style="color:#b5231a;font-size:13px;min-height:18px"></p>' +
    '<button type="button" style="width:100%;padding:12px;border-radius:12px;border:1px solid #d9d9de;background:#fff;font-size:15px">Cerrar</button>';
  document.body.appendChild(dlg);
  const video = dlg.querySelector('video');
  let stream = null, activa = false;
  dlg.querySelector('button').addEventListener('click', () => dlg.close());
  dlg.addEventListener('close', () => {
    activa = false;
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    input.focus();
  });

  boton.addEventListener('click', async () => {
    dlg.querySelector('.err').textContent = '';
    dlg.showModal();
    try {
      const detector = new BarcodeDetector({ formats: ['ean_13', 'ean_8', 'code_128', 'upc_a', 'upc_e'] });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      video.srcObject = stream;
      await video.play();
      activa = true;
      while (activa) {
        const hallados = await detector.detect(video).catch(() => []);
        if (hallados.length) { dlg.close(); alDetectar(hallados[0].rawValue.trim()); return; }
        await new Promise(r => setTimeout(r, 250));
      }
    } catch (_) {
      dlg.querySelector('.err').textContent = 'No se pudo usar la cámara. Revise el permiso del navegador.';
    }
  });
}
