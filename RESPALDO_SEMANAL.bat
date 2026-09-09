@echo off
chcp 65001 >nul
title AllPetCR - Respaldo semanal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY=.\.venv\Scripts\python.exe
set LOG=respaldos\log_respaldo_semanal.txt

REM Lo corre el Programador de tareas de Windows. Sin pausa al final: si la
REM hubiera, la tarea quedaria colgada esperando una tecla que nadie aprieta.

if not exist "respaldos" mkdir "respaldos"

if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 1000000 move /y "%LOG%" "%LOG%.old" >nul

echo. >> "%LOG%"
%PY% _respaldo_programado.py semanal >> "%LOG%" 2>&1

exit /b %ERRORLEVEL%
