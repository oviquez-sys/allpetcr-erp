@echo off
chcp 65001 >nul
title AllPetCR - Instalar el PDF de los recibos
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_pdf.txt
set PY=.\.venv\Scripts\python.exe

echo.
echo   Instalando lo necesario para que el recibo salga en PDF.
echo.
echo   AVISO: descarga unos 150 MB la primera vez (Chromium).
echo   Puede tardar varios minutos segun tu internet. No cierres la ventana.
echo.
pause

echo ===== 1. LIBRERIA ===== > "%LOG%"
echo   [1 de 3] Instalando la libreria...
%PY% -m pip install "playwright>=1.47" >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 2. CHROMIUM ===== >> "%LOG%"
echo   [2 de 3] Descargando Chromium (esto es lo que tarda)...
%PY% -m playwright install chromium >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 3. PRUEBA ===== >> "%LOG%"
echo   [3 de 3] Probando que genere un PDF...
%PY% -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); pg=b.new_page(); pg.set_content(\"<h1>AllPetCR</h1><p>Prueba de PDF</p>\"); d=pg.pdf(format=\"Letter\"); b.close(); p.stop(); print(\"PDF generado:\", len(d), \"bytes\")" >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

type "%LOG%"
echo.
echo   Si la ultima linea dice PDF generado, quedo listo.
echo   Reinicia el ERP y proba enviar un recibo.
echo.
pause
