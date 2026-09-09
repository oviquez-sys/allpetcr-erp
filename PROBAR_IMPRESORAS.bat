@echo off
setlocal
cd /d "%~dp0"
set LOG=%~dp0resultado_prueba_impresoras.txt
echo ===== PRUEBA EN PAPEL %DATE% %TIME% ===== > "%LOG%"
echo Enviando una prueba a cada impresora...
.\.venv\Scripts\python.exe manage.py probar_impresoras --imprimir >> "%LOG%" 2>&1
echo.
echo Listo. Revise el papel y el archivo resultado_prueba_impresoras.txt
timeout /t 4 >nul
