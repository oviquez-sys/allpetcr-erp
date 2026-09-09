@echo off
chcp 65001 >nul
title AllPetCR - Recibir mercaderia v3
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_recibir.txt
set PY=.\.venv\Scripts\python.exe

echo.
echo   Probando los cambios de Recibir mercaderia.
echo   Tarda un par de minutos. No cierres esta ventana.
echo.

echo ===== PRUEBAS DE COMPRAS ===== > "%LOG%"
echo   [1 de 2] Probando compras...
%PY% manage.py test compras >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== PRUEBAS DE ARQUITECTURA Y CATALOGO ===== >> "%LOG%"
echo   [2 de 2] Probando reglas del proyecto y catalogo...
%PY% manage.py test core catalogo >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

echo.
echo   LISTO. Ya podes cerrar esta ventana y avisarle a Claude.
echo.
pause
