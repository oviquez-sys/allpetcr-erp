@echo off
title AllPetCR - Aplicar mejoras de categorias
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

REM Aplica el arbol de categorias nuevo y revisa los dos sistemas.
REM Toda la salida queda en un txt que Claude lee de la carpeta.

set LOG=resultado_mejoras.txt
set PY=.\.venv\Scripts\python.exe

echo.
echo   Aplicando mejoras y revisando los dos sistemas.
echo   Tarda entre tres y cinco minutos. No cierres esta ventana.
echo.

echo ===== 1. MIGRATE (campo orden) ===== > "%LOG%"
echo   [1 de 5] Agregando el campo de orden a la base...
%PY% manage.py migrate >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 2. SIMULACION DEL ARBOL ===== >> "%LOG%"
echo   [2 de 5] Simulando el arbol de categorias...
%PY% manage.py asegurar_categorias --dry-run >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 3. ARBOL APLICADO ===== >> "%LOG%"
echo   [3 de 5] Creando las categorias...
%PY% manage.py asegurar_categorias >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 4. PRUEBAS DEL ERP ===== >> "%LOG%"
echo   [4 de 5] Probando el ERP...
%PY% manage.py test catalogo compras api >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 5. PRUEBAS DEL SITIO WEB ===== >> "%LOG%"
echo   [5 de 5] Probando el sitio web (lint + tipos + pruebas)...
pushd "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-web"
call npm run revisar >> "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp\%LOG%" 2>&1
popd

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

echo.
echo   LISTO. Ya podes cerrar esta ventana y avisarle a Claude.
echo.
pause
