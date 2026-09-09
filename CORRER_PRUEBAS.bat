@echo off
title AllPetCR ERP - Migracion y pruebas
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

REM Corre la migracion y las pruebas, y deja TODA la salida en un archivo de
REM texto que Claude puede leer directo de la carpeta. Asi Oscar no tiene que
REM copiar ni pegar nada: solo hace doble clic y avisa.

set LOG=resultado_pruebas.txt

echo.
echo   Corriendo migracion y pruebas del ERP.
echo   Esto tarda entre uno y tres minutos. No cierres esta ventana.
echo.

echo ===== INICIO ===== > "%LOG%"
date /t >> "%LOG%"
time /t >> "%LOG%"

echo. >> "%LOG%"
echo ===== MIGRATE ===== >> "%LOG%"
echo   [1 de 3] Aplicando el campo nuevo a la base...
.\.venv\Scripts\python.exe manage.py migrate >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== TEST COMPRAS ===== >> "%LOG%"
echo   [2 de 3] Probando compras (bonificaciones 12+1)...
.\.venv\Scripts\python.exe manage.py test compras >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== TEST CATALOGO ===== >> "%LOG%"
echo   [3 de 3] Probando catalogo (bandera --sin-stock)...
.\.venv\Scripts\python.exe manage.py test catalogo >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

echo.
echo   LISTO. El resultado quedo guardado en:
echo      %CD%\%LOG%
echo.
echo   Ya podes cerrar esta ventana y avisarle a Claude.
echo.
pause
