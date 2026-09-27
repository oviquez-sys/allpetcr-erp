@echo off
chcp 65001 >nul
title AllPetCR - Correcciones de producto
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No encontre el entorno .venv en esta carpeta.
    echo Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _corregir_en_servidor.py
pause
