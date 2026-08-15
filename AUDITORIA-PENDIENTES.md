# Pendientes de la auditoría de Fase 1 (seguridad)

Estado al 2026-08-15. Fuente de verdad complementaria a `HALLAZGOS.md` —
esto es solo el checklist de la sesión de auditoría en curso. Fuente
autoritativa de cada hallazgo: `auditoria/hallazgos_v1.json`.

**12 hallazgos — 8 cerrados / 4 abiertos.**

## Cerrados (con commit)

| ID | Severidad | Commit |
|---|---|---|
| SEC-001 | 🟠 alto | `a4d3008` |
| AUD-001 | 🟠 alto | `b768b39` |
| SEC-002 | 🟠 alto | `b768b39` |
| SEC-006 | 🟠 alto | `307a024` |
| FRA-001 | 🟠 alto | `4106eea` |
| FRA-002 | 🟠 alto | `7ac5c84` |
| FRA-003 | 🟠 alto | `ee36944` |
| FRA-004 | 🟡 medio | `b499198` |

## Abiertos

**SEC-005** (🔴 crítico, no es código). Confirmado abierto: `cmd.exe` abre
sin restricción desde la sesión del cajero en el POS real. Plan de
remediación propuesto (sin implementar) en `auditoria/01_seguridad.md`,
sección "SEC-005 — plan de remediación": cuenta Estándar forzada, bloqueo
de `cmd`/PowerShell vía Directiva de grupo o AppLocker, revisar que
`Iniciar_AllPetCR_ERP.bat` siga arrancando, permisos NTFS de la carpeta
del proyecto. Nada de esto es código — son pasos de configuración de la
máquina del POS, a decidir y aplicar por el usuario.

**FRA-005** (🟠 alto). Los respaldos (`manage.py respaldar`) están en una
carpeta común, escribible y con auto-rotación — el mismo administrador que
podría necesitar cubrir un fraude puede borrar o esperar a que se borren
solos los respaldos que lo probarían. Versión barata propuesta (sin
implementar): que `respaldar` mande automáticamente una copia del respaldo
periódico a una cuenta/correo del otro socio, reutilizando el mecanismo de
FRA-004. Alternativas más robustas (almacenamiento WORM/object-lock)
evaluadas como overkill para un negocio de dos socios en esta etapa.

**SEC-003** (🟢 bajo, en pausa). `ProductoAdmin.entrada_view` no pasa por
`documento_de_empresa` — no explotable hoy (una sola empresa).

**SEC-004** (🟢 bajo, en pausa). Sin 2FA, sin límite de sesiones
concurrentes, sin flujo propio de recuperación de contraseña.

SEC-003 y SEC-004 quedan sin tocar salvo pedido explícito del usuario.
