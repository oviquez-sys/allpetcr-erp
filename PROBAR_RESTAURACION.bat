@echo off
chcp 65001 >nul
title AllPetCR - Ensayo de restauracion
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY=.\.venv\Scripts\python.exe
set LOG=resultado_restauracion.txt

echo.
echo   ============================================================
echo     ENSAYO DE RESTAURACION
echo   ============================================================
echo.
echo   Prueba que el negocio se puede RECUPERAR de verdad:
echo.
echo     1. Agarra el respaldo mas nuevo
echo     2. Crea una base de datos de prueba, aparte
echo     3. Restaura el respaldo ahi adentro
echo     4. Cuenta productos, ventas y movimientos
echo     5. Borra la base de prueba
echo.
echo   La base REAL no se toca. Puede tardar varios minutos.
echo.

if exist "%LOG%" del "%LOG%"

%PY% _prueba_restauracion.py > "%LOG%" 2>&1

type "%LOG%"
echo.
echo   ------------------------------------------------------------
echo   Copiale a Claude TODO lo que salio arriba.
echo   ------------------------------------------------------------
echo.
pause
