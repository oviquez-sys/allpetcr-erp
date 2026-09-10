@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AllPetCR - Revisar productos sin existencia

echo.
echo   Esto SOLO REVISA y genera un Excel. No borra nada.
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo   No encontre el entorno .venv en esta carpeta.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _productos_sin_existencia.py

echo.
pause
