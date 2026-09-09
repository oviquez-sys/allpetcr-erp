@echo off
chcp 65001 >nul
title AllPetCR - Pruebas del sistema de respaldos
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY=.\.venv\Scripts\python.exe
set LOG=resultado_pruebas_respaldos.txt

echo.
echo   ============================================================
echo     PRUEBAS DEL SISTEMA DE RESPALDOS
echo   ============================================================
echo.
echo   Comprueba dos cosas:
echo.
echo     1. Que respaldar y restaurar funcionen (ciclo completo)
echo     2. Que los comandos escritos en RESPALDOS.txt existan
echo        de verdad, con las opciones que dice el manual
echo.
echo   Tarda un minuto. No cierres la ventana.
echo.

if exist "%LOG%" del "%LOG%"

echo ===== PRUEBAS DE RESPALDO Y RESTAURACION ===== > "%LOG%"
%PY% manage.py test core.test_respaldos -v 2 >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== EL MANUAL COINCIDE CON EL SISTEMA ===== >> "%LOG%"
%PY% manage.py test core.test_manual_respaldos -v 2 >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

type "%LOG%"
echo.
echo   ------------------------------------------------------------
echo   Copiale a Claude TODO lo que salio arriba.
echo   ------------------------------------------------------------
echo.
pause
