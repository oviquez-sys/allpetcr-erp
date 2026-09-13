@echo off
chcp 65001 >nul
title AllPetCR - Traer los respaldos del servidor
cd /d "%~dp0"

REM Lo corre la tarea programada "AllPetCR - Traer respaldos del servidor", y
REM tambien sirve para darle doble clic. Sin pause al final: si la hubiera, la
REM tarea quedaria colgada esperando una tecla que nadie aprieta.

set LOG=respaldos\log_traer_respaldos.txt
if not exist "respaldos" mkdir "respaldos"

REM El registro se acumula. Cuando pasa de 1 MB se guarda como .old y se
REM empieza uno nuevo: queda historia reciente sin que el archivo crezca solo.
if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 1000000 move /y "%LOG%" "%LOG%.old" >nul

if not exist ".venv\Scripts\python.exe" (
    echo No encontre el entorno .venv en esta carpeta. Avisale a Claude. >> "%LOG%"
    exit /b 1
)

REM boto3 viene en requirements.txt, pero el entorno de esta computadora es
REM mas viejo que esa linea. Si ya esta, pip no hace nada y tarda un segundo.
.\.venv\Scripts\python.exe -c "import boto3" 2>nul
if errorlevel 1 .\.venv\Scripts\python.exe -m pip install --quiet boto3 >> "%LOG%" 2>&1

echo. >> "%LOG%"
.\.venv\Scripts\python.exe _traer_respaldos_nube.py >> "%LOG%" 2>&1

REM El codigo de salida se lo lleva el Programador de tareas: si es distinto de
REM cero, la tarea aparece como fallida en su historial. Eso es a proposito —
REM es la unica senal de que el respaldo del servidor dejo de llegar.
exit /b %ERRORLEVEL%
