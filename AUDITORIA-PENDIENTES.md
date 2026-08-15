# Pendientes de la auditoría de Fase 1 (seguridad)

Estado al 2026-08-15. Fuente de verdad complementaria a `HALLAZGOS.md` —
esto es solo el checklist de la sesión de auditoría en curso.

## 1. Commitear SEC-001
**Hecho.** Commit `a4d3008`, pusheado a `origin/main` junto con `b768b39`
(SEC-002 + AUD-001).

## 2. Implementar SEC-006
**Hecho.** Commit `307a024`, pusheado. Motivo obligatorio y tope de ₡5,000
por línea (`REGALIA_MAXIMA_SIN_AUTORIZACION`), autorización de Gerente vía
`permitir_regalia_alta`, mismo patrón que `permitir_bajo_costo` /
`permitir_descuento_alto` de SEC-001. Tocados: `ventas/services.py`,
`ventas/views.py`, `templates/ventas/pos.html`, `ventas/tests.py` (7 tests
nuevos en `VentaRegaliaAlta` + 6 ajustados). 151/151 en verde
(`ventas caja compras contabilidad inventario`).

## 3. Actualizar `auditoria/hallazgos_v1.json` y `01_seguridad.md`
**Hecho.** SEC-001 (`a4d3008`), AUD-001 (`b768b39`), SEC-002 (`b768b39`) y
SEC-006 (`307a024`) quedan `"estado": "cerrado"` con su commit en ambos
archivos.

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
