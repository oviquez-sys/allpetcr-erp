@echo off
chcp 65001 >nul
title AllPetCR - Arreglar el envio de correos
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_correo.txt
set PY=.\.venv\Scripts\python.exe

REM Instala truststore para que Python valide los certificados contra el
REM almacen de Windows, y vuelve a probar el envio. No desactiva ninguna
REM verificacion: solo usa la lista de confianza que Windows ya tiene.

echo.
echo   Paso 1: instalando el arreglo (necesita internet)...
echo.

echo ===== INSTALACION ===== > "%LOG%"
%PY% -m pip install "truststore>=0.9" >> "%LOG%" 2>&1

echo   Paso 2: probando el envio otra vez...
echo.

echo. >> "%LOG%"
echo ===== PRUEBA DE CORREO ===== >> "%LOG%"
%PY% manage.py probar_correo >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

type "%LOG%"
echo.
echo   El resultado tambien quedo en %LOG%
echo   Si dice ENVIADO, revisa la bandeja de entrada.
echo.
pause
