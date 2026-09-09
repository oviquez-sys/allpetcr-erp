@echo off
chcp 65001 >nul
setlocal
title AllPetCR - Probar el aviso por correo
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY=.\.venv\Scripts\python.exe
set SALIDA=resultado_aviso.txt

echo.
echo   ============================================================
echo     PROBAR EL AVISO POR CORREO DEL RESPALDO
echo   ============================================================
echo.
echo   Manda un correo de prueba por el MISMO camino que usaria
echo   un fallo real del respaldo.
echo.
echo   Es la ultima pieza sin probar: si el aviso no llega, un
echo   respaldo que deje de correr vuelve a pasar inadvertido.
echo.

if exist "%SALIDA%" del "%SALIDA%"

%PY% _probar_aviso_respaldo.py > "%SALIDA%" 2>&1

type "%SALIDA%"
echo.
echo   ------------------------------------------------------------
echo   Revisa tu bandeja y copiale a Claude lo que salio arriba.
echo   ------------------------------------------------------------
echo.
pause
