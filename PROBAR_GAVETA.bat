@echo off
setlocal
cd /d "%~dp0"
echo ===== PRUEBA DE LA GAVETA DE DINERO =====
echo.
echo Antes de seguir: el cable de la gaveta tiene que estar en la IMPRESORA DE RECIBOS,
echo en el puerto que dice DK o CASH DRAWER (no en la computadora).
echo La impresora tiene que estar encendida y con su cable USB en esta computadora.
echo.
pause
.\.venv\Scripts\python.exe _probar_gaveta.py
echo.
echo Listo. El resultado quedo en resultado_gaveta.txt
pause
