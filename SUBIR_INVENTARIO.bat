@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AllPetCR - Subir inventario al servidor

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo   No encontre el entorno .venv en esta carpeta.
    echo   Corre primero SINCRONIZAR_TODO.bat, que lo crea.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _subir_al_servidor.py
