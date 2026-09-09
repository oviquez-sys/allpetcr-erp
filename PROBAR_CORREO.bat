@echo off
chcp 65001 >nul
title AllPetCR - Probar el correo
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_correo.txt
set PY=.\.venv\Scripts\python.exe

REM Manda un correo de prueba y explica que paso. Nunca muestra la clave.

echo.
echo   Probando el envio de correos del ERP...
echo.

echo ===== PRUEBA DE CORREO ===== > "%LOG%"
%PY% manage.py probar_correo >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

type "%LOG%"
echo.
echo   El resultado tambien quedo en %LOG%
echo.
pause
