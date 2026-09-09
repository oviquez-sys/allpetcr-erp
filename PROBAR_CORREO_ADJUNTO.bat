@echo off
chcp 65001 >nul
title AllPetCR - Probar correo con adjunto
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_correo_adjunto.txt
set PY=.\.venv\Scripts\python.exe

REM Reproduce el envio de una factura: mismo camino, con un adjunto del
REM tamano de un PDF. Es lo que fallaba cuando el envio simple funcionaba.

echo.
echo   Probando con un adjunto, como una factura real...
echo.

echo ===== SIN ADJUNTO ===== > "%LOG%"
%PY% manage.py probar_correo >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== CON ADJUNTO DE 200 KB ===== >> "%LOG%"
%PY% manage.py probar_correo --adjunto 200 >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== CON ADJUNTO DE 1000 KB ===== >> "%LOG%"
%PY% manage.py probar_correo --adjunto 1000 >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

type "%LOG%"
echo.
pause
