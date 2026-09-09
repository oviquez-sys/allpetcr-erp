@echo off
chcp 65001 >nul
title AllPetCR - Corregir categorias
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_correccion.txt
set PY=.\.venv\Scripts\python.exe

echo.
echo   Corrigiendo el arbol de categorias y revisando los dos sistemas.
echo   Tarda unos cinco minutos. No cierres esta ventana.
echo.

echo ===== 1. SIMULACION (que se va a borrar y ordenar) ===== > "%LOG%"
echo   [1 de 5] Simulando...
%PY% manage.py asegurar_categorias --borrar-vacias --dry-run >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 2. APLICADO ===== >> "%LOG%"
echo   [2 de 5] Aplicando la correccion...
%PY% manage.py asegurar_categorias --borrar-vacias >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 3. ESTADO REAL DE LA BASE ===== >> "%LOG%"
echo   [3 de 5] Verificando contra la base...
%PY% _verificar_categorias.py >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 4. PUBLICAR EL CATALOGO AL SITIO ===== >> "%LOG%"
echo   [4 de 5] Publicando el catalogo al sitio...
%PY% manage.py exportar_catalogo_web >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== 5. PRUEBAS DE LOS DOS SISTEMAS ===== >> "%LOG%"
echo   [5 de 5] Probando el ERP y el sitio...
%PY% manage.py test catalogo compras api >> "%LOG%" 2>&1
pushd "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-web"
call npm run revisar >> "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp\%LOG%" 2>&1
popd

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

echo.
echo   LISTO. Ya podes cerrar esta ventana y avisarle a Claude.
echo.
pause
