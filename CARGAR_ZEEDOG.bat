@echo off
chcp 65001 >nul
title AllPetCR - Cargar la compra de ZeeDog (accesorios)
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No encontre el entorno .venv en esta carpeta.
    echo Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _cargar_zeedog_en_servidor.py
pause
