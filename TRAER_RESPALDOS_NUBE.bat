@echo off
chcp 65001 >nul
title AllPetCR - Traer los respaldos del servidor
cd /d "%~dp0"

REM Lo corre la tarea programada "AllPetCR - Traer respaldos del servidor", y
REM tambien sirve para darle doble clic. Sin pause al final: si la hubiera, la
REM tarea quedaria colgada esperando una tecla que nadie aprieta.

REM OJO AL TOCAR ESTE ARCHIVO (13/09/2026): tiene que guardarse con saltos de
REM linea de Windows (CRLF) y sin bloques "if (...)" de varias lineas. Con
REM saltos de linea de Linux, cmd.exe cierra la ventana sin ejecutar nada y sin
REM dejar registro: parece que el .bat "no hace nada" y se pierde media hora
REM buscando el error en el lugar equivocado.

set LOG=respaldos\log_traer_respaldos.txt
if not exist "respaldos" mkdir "respaldos"

REM El registro se acumula. Cuando pasa de 1 MB se guarda como .old y se
REM empieza uno nuevo: queda historia reciente sin que el archivo crezca solo.
if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 1000000 move /y "%LOG%" "%LOG%.old" >nul

if exist ".venv\Scripts\python.exe" goto :hay_python
echo No encontre el entorno .venv en esta carpeta. Avisale a Claude. >> "%LOG%"
exit /b 1

:hay_python
REM boto3 viene en requirements.txt, pero el entorno de esta computadora es mas
REM viejo que esa linea. Si ya esta, pip no hace nada y tarda un segundo.
.\.venv\Scripts\python.exe -c "import boto3" 2>nul
if errorlevel 1 .\.venv\Scripts\python.exe -m pip install --quiet boto3 >> "%LOG%" 2>&1

echo. >> "%LOG%"
.\.venv\Scripts\python.exe _traer_respaldos_nube.py >> "%LOG%" 2>&1

REM El codigo de salida se lo lleva el Programador de tareas: si es distinto de
REM cero, la tarea aparece como fallida en su historial. Eso es a proposito: es
REM la unica senal de que el respaldo del servidor dejo de llegar.
exit /b %ERRORLEVEL%
