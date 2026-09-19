@echo off
chcp 65001 >nul
title AllPetCR - Cargar la compra de setiembre (factura 19-09)
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No encontre el entorno .venv en esta carpeta.
    echo Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _cargar_compra_en_servidor.py
pause
