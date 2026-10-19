@echo off
chcp 65001 >nul
title AllPetCR - Corregir precios Wellsbi
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No encontre el entorno .venv en esta carpeta.
    echo Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _corregir_precios_wellsbi_en_servidor.py
pause
