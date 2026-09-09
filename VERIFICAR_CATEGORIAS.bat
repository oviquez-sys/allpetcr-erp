@echo off
chcp 65001 >nul
title AllPetCR - Verificar categorias
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

REM chcp 65001 + PYTHONIOENCODING: la consola de Windows escribe en cp1252 y
REM revienta con acentos y flechas. Con esto Python escribe UTF-8 y no falla.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=resultado_categorias.txt
set PY=.\.venv\Scripts\python.exe

echo.
echo   Revisando el arbol de categorias. Solo lee, no modifica nada.
echo.

echo ===== ARBOL SEGUN EL COMANDO ===== > "%LOG%"
%PY% manage.py asegurar_categorias --dry-run >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== ESTADO REAL DE LA BASE ===== >> "%LOG%"
%PY% _verificar_categorias.py >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo ===== FIN ===== >> "%LOG%"

echo.
echo   LISTO. Ya podes cerrar esta ventana y avisarle a Claude.
echo.
pause
