@echo off
chcp 65001 >nul
title AllPetCR - Programar los respaldos
cd /d "%~dp0"

echo.
echo   ============================================================
echo     DEJAR LOS RESPALDOS CORRIENDO SOLOS
echo   ============================================================
echo.
echo   Esto programa dos tareas en Windows:
echo.
echo     - Todos los dias a las 21:00 : solo la base de datos
echo     - Domingos a las 21:30       : base + todas las fotos
echo.
echo   Las dos guardan en OneDrive y avisan por correo si fallan.
echo.
echo   Al final corre el respaldo diario UNA VEZ para comprobar que
echo   la tarea funciona de verdad, no solo que quedo escrita.
echo.

REM Toda la salida va tambien a un archivo (13/09/2026). Si la ventana se
REM cierra sola —porque Windows la mata, porque el .ps1 revienta al arrancar o
REM porque se abrio con doble clic sobre el archivo equivocado— sin esto no
REM queda rastro de que paso y hay que adivinar. Con el archivo, se lee.
set LOG=resultado_programar.txt

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_programar_respaldos.ps1" > "%LOG%" 2>&1
type "%LOG%"

echo.
echo   ------------------------------------------------------------
echo   Si la ventana se cerro antes de que leyeras esto, abri el
echo   archivo resultado_programar.txt que quedo en esta carpeta.
echo   ------------------------------------------------------------
echo.
pause
