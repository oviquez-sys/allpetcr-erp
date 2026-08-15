# Pendientes de la auditoría de Fase 1 (seguridad)

Estado al 2026-08-15. Fuente de verdad complementaria a `HALLAZGOS.md` —
esto es solo el checklist de la sesión de auditoría en curso.

## 1. Commitear SEC-001
**Hecho.** Commit `a4d3008`, pusheado a `origin/main` junto con `b768b39`
(SEC-002 + AUD-001).

## 2. Implementar SEC-006
**Pendiente.** Decisión de negocio ya tomada:
- Cajero puede seguir marcando `es_regalia`, pero con **motivo obligatorio**
  y **tope de ₡5,000** por línea (calculado sobre `precio_venta * cantidad`).
- Por encima del tope, requiere autorización de Gerente (mismo patrón que
  `permitir_bajo_costo` / `permitir_descuento_alto` de SEC-001).

Archivos a tocar:
- `ventas/services.py` — nueva constante `REGALIA_MAXIMA_SIN_AUTORIZACION`,
  parámetro `permitir_regalia_alta`, validación de motivo dentro de la rama
  `if es_regalia:` de `registrar_venta`.
- `ventas/views.py` — pasar `permitir_regalia_alta=es_gerente(request.user)`
  en `vender()`.
- `templates/ventas/pos.html` — input de motivo en el toggle de "Regalo",
  incluirlo en el payload de `cobrar()`.
- `ventas/tests.py` — clase de tests nueva, mismo patrón que
  `VentaDescuentoAlto`.

Workflow acordado: un cambio a la vez, mostrar diff, correr tests de
`ventas`, esperar aprobación antes de seguir. Commit aparte al cerrar.

## 3. Actualizar `auditoria/hallazgos_v1.json` y `01_seguridad.md`
**Pendiente.** SEC-001, AUD-001 y SEC-002 siguen con `"estado": "abierto"`
aunque ya están corregidos y pusheados. Actualizar a `"cerrado"` (o el valor
que corresponda) en ambos archivos. SEC-006 se queda en `"abierto"` hasta
que el punto 2 esté implementado y commiteado.

## 4. SEC-005 (crítico, no es código)
**Pendiente de respuesta del usuario.** No se corrige con código — es una
acción de infraestructura/SO. Falta confirmar: ¿la cuenta de Windows que usan
los cajeros en la máquina del POS está restringida (sin acceso a terminal/
PowerShell)? Si no lo está, `asignar_rol --dueno` da superusuario instantáneo
a cualquiera con acceso físico al mostrador.

## 5. SEC-003 y SEC-004
**En pausa**, sin tocar salvo pedido explícito del usuario. Ambos son 🟢 bajo:
- SEC-003: `ProductoAdmin.entrada_view` no pasa por `documento_de_empresa`.
- SEC-004: sin 2FA, sin límite de sesiones concurrentes, sin flujo propio de
  recuperación de contraseña.
