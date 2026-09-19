@echo off
chcp 65001 >nul
title AllPetCR - Ver las ventas del servidor
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No encontre el entorno .venv en esta carpeta.
    echo Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _ver_ventas_en_servidor.py
pause
