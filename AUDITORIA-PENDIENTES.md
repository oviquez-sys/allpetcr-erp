# Pendientes de la auditoría de Fase 1 (seguridad)

Estado al 2026-08-15. Fuente de verdad complementaria a `HALLAZGOS.md` —
esto es solo el checklist de la sesión de auditoría en curso. Fuente
autoritativa de cada hallazgo: `auditoria/hallazgos_v1.json`.

**12 hallazgos — 8 cerrados / 1 implementado pendiente de verificación / 3 abiertos.**

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

## Implementado, pendiente de verificación

**FRA-005** ⏳ (🟠 alto, commit `bac4bec`). `manage.py respaldar` sube el
zip a Backblaze B2 (Object Lock modo Compliance, 30 días de retención,
Application Key "Write Only") cuando están definidas las 4 variables de
entorno — código y 3 tests con `boto3` mockeado, en verde. El diseño se
verificó contra la documentación oficial de B2, **no contra una cuenta
real todavía**. Reemplaza la versión barata que se había evaluado antes
(mandarle una copia al otro socio): con el servidor en DigitalOcean
administrado por ambos socios, esa idea dejó de tener sentido — los dos
ya tienen el mismo nivel de acceso.

**Condición de cierre** (falta hacer, no es código):
1. Crear el bucket real en B2 con Object Lock, retención por defecto
   Compliance 30 días, y la Application Key Write Only — paso a paso en
   `PRODUCCION.txt`, sección "5c) RESPALDO INMUTABLE A BACKBLAZE B2".
2. Correr `python manage.py respaldar` con las 4 variables apuntando a
   esa cuenta real y confirmar en el panel de B2 que el archivo llegó con
   "Retention: Compliance, expira en 30 días".
3. Confirmar que la llave Write Only efectivamente rechaza un intento de
   borrado (no alcanza con que el panel diga "Write Only" — probarlo).

## Abiertos

**SEC-005** (🔴 crítico, no es código). Confirmado abierto: `cmd.exe` abre
sin restricción desde la sesión del cajero en el POS real. Plan de
remediación propuesto (sin implementar) en `auditoria/01_seguridad.md`,
sección "SEC-005 — plan de remediación": cuenta Estándar forzada, bloqueo
de `cmd`/PowerShell vía Directiva de grupo o AppLocker, revisar que
`Iniciar_AllPetCR_ERP.bat` siga arrancando, permisos NTFS de la carpeta
del proyecto. Nada de esto es código — son pasos de configuración de la
máquina del POS, a decidir y aplicar por el usuario.

**SEC-003** (🟢 bajo, en pausa). `ProductoAdmin.entrada_view` no pasa por
`documento_de_empresa` — no explotable hoy (una sola empresa).

**SEC-004** (🟢 bajo, en pausa). Sin 2FA, sin límite de sesiones
concurrentes, sin flujo propio de recuperación de contraseña.

SEC-003 y SEC-004 quedan sin tocar salvo pedido explícito del usuario.
