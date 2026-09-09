@echo off
title AllPetCR ERP - Verificacion
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

REM Comprueba contra la base REAL que el campo nuevo quedo creado.
REM No modifica nada: solo lee y reporta.

set LOG=resultado_verificacion.txt

echo.
echo   Verificando la base de datos real. Tarda unos segundos.
echo.

echo ===== ESTADO DE MIGRACIONES ===== > "%LOG%"
.\.venv\Scripts\python.exe manage.py showmigrations compras >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== QUE FALTA POR APLICAR ===== >> "%LOG%"
.\.venv\Scripts\python.exe manage.py migrate --plan >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== BASE REAL Y COLUMNAS ===== >> "%LOG%"
.\.venv\Scripts\python.exe _verificar_bonificacion.py >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

echo.
echo   LISTO. Ya podes cerrar esta ventana y avisarle a Claude.
echo.
pause
