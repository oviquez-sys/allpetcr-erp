@echo off
chcp 65001 >nul
title AllPetCR - Respaldo diario
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY=.\.venv\Scripts\python.exe
set LOG=respaldos\log_respaldo_diario.txt

REM Lo corre el Programador de tareas de Windows. Sin pausa al final: si la
REM hubiera, la tarea quedaria colgada esperando una tecla que nadie aprieta.

if not exist "respaldos" mkdir "respaldos"

REM El registro se acumula todos los dias. Cuando pasa de 1 MB se guarda como
REM .old y se empieza uno nuevo: asi queda historia reciente sin que el archivo
REM crezca sin freno durante anos.
if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 1000000 move /y "%LOG%" "%LOG%.old" >nul

echo. >> "%LOG%"
%PY% _respaldo_programado.py diario >> "%LOG%" 2>&1

REM El codigo de salida se lo lleva el Programador: si es distinto de 0, la
REM tarea aparece como fallida en su historial.
exit /b %ERRORLEVEL%
