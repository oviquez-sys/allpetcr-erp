@echo off
REM ============================================================
REM   RESPALDO AUTOMATICO - ALLPETCR ERP
REM   Doble clic para respaldar ahora, o agendalo en el
REM   Programador de tareas de Windows para que corra solo.
REM   (ver RESPALDOS.txt, seccion "Que corra solo cada dia").
REM ============================================================

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

echo Creando respaldo, un momento...
python manage.py respaldar

echo.
echo Listo. Los respaldos quedan en la carpeta "respaldos".
REM Si lo corres a mano, esta pausa te deja leer el resultado.
REM El Programador de tareas la ignora.
timeout /t 8 >nul
