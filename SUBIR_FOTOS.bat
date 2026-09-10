@echo off
chcp 65001 >nul
title AllPetCR - Subir fotos al bucket
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo No encontre el entorno .venv en esta carpeta.
    echo Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

REM boto3 esta en requirements.txt, pero el entorno de esta computadora es
REM mas viejo que esa linea y no lo tenia instalado (10/09/2026). Se instala
REM aca en vez de pedirle a Oscar que corra pip a mano; si ya esta, pip no
REM hace nada y tarda un segundo.
python -c "import boto3" 2>nul
if errorlevel 1 (
    echo.
    echo   Falta una pieza ^(boto3^). La instalo, tarda unos segundos...
    echo.
    python -m pip install --quiet boto3
    if errorlevel 1 (
        echo.
        echo   ERROR: no se pudo instalar boto3. Copiale la pantalla a Claude.
        pause
        exit /b 1
    )
)

python _subir_fotos_a_s3.py
