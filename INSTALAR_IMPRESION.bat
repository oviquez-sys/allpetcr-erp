@echo off
setlocal
cd /d "%~dp0"
set LOG=%~dp0resultado_impresion.txt
echo ===== INSTALACION DEL MODULO DE IMPRESION %DATE% %TIME% ===== > "%LOG%"
echo Instalando componentes (pywin32 y Pillow)...
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check pywin32 Pillow >> "%LOG%" 2>&1
echo Registrando pywin32 en Windows... >> "%LOG%"
.\.venv\Scripts\python.exe .\.venv\Scripts\pywin32_postinstall.py -install >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ===== PRUEBAS DEL MODULO DE IMPRESION ===== >> "%LOG%"
.\.venv\Scripts\python.exe manage.py test impresion >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ===== DIAGNOSTICO DE IMPRESORAS ===== >> "%LOG%"
.\.venv\Scripts\python.exe manage.py probar_impresoras >> "%LOG%" 2>&1
echo.
echo Listo. El resultado quedo en resultado_impresion.txt
timeout /t 4 >nul
