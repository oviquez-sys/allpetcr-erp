@echo off
chcp 65001 >nul
title AllPetCR - Cargar fotos editadas al servidor
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No encontre el entorno .venv en esta carpeta.
    echo Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

python -c "import boto3" 2>nul
if errorlevel 1 (
    echo.
    echo   Falta una pieza ^(boto3^). La instalo, tarda unos segundos...
    echo.
    python -m pip install --quiet boto3
)

python _cargar_fotos_editadas_en_servidor.py
pause
