@echo off
chcp 65001 >nul
title AllPetCR - RESPALDO AHORA
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_respaldo.txt
set PY=.\.venv\Scripts\python.exe

echo.
echo   ============================================
echo     RESPALDO DE ALLPETCR
echo   ============================================
echo.
echo   Paso 1: revisar el respaldo que hay hoy
echo   Paso 2: crear uno nuevo
echo   Paso 3: revisar el nuevo
echo.
echo   Tarda un par de minutos. No cierres la ventana.
echo.

echo ===== 1. COMO ESTABA ANTES ===== > "%LOG%"
echo   [1 de 3] Revisando el respaldo actual...
%PY% _verificar_respaldo.py >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 2. RESPALDO NUEVO ===== >> "%LOG%"
echo   [2 de 3] Creando el respaldo nuevo (puede tardar)...
%PY% manage.py respaldar >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 3. REVISION DEL NUEVO ===== >> "%LOG%"
echo   [3 de 3] Revisando el respaldo nuevo...
%PY% _verificar_respaldo.py >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

type "%LOG%"
echo.
echo   Abriendo la carpeta de respaldos...
start "" "respaldos"
echo.
pause
