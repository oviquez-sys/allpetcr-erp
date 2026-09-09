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

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_programar_respaldos.ps1"

echo.
echo   ------------------------------------------------------------
echo   Copiale a Claude TODO lo que salio arriba.
echo   ------------------------------------------------------------
echo.
pause
