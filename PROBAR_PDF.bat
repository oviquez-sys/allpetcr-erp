@echo off
chcp 65001 >nul
title AllPetCR - Ver el recibo en PDF
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_pdf.txt
set PY=.\.venv\Scripts\python.exe

REM Genera el PDF del ultimo recibo y lo abre. No manda ningun correo.

echo.
echo   Generando el PDF del ultimo recibo. Tarda unos segundos.
echo.

echo ===== PRUEBA DE PDF ===== > "%LOG%"
%PY% _probar_pdf_recibo.py >> "%LOG%" 2>&1

type "%LOG%"

if exist "Recibo-prueba.pdf" (
  echo.
  echo   Abriendo el PDF...
  start "" "Recibo-prueba.pdf"
)

echo.
pause
