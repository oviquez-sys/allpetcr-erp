@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AllPetCR - BORRAR productos sin existencia

echo.
echo  ==================================================================
echo    ATENCION: ESTO BORRA PRODUCTOS Y NO SE PUEDE DESHACER
echo  ==================================================================
echo.
echo    Antes de seguir:
echo      1. Corriste REVISAR_SIN_EXISTENCIA.bat
echo      2. Abriste PRODUCTOS_SIN_EXISTENCIA.xlsx y lo revisaste
echo      3. Estas de acuerdo con borrar los que dicen "Si" en la
echo         columna "Se puede borrar"
echo.
echo    Si no hiciste los tres pasos, cerra esta ventana.
echo.
set /p RESP="   Escribi BORRAR para continuar: "
if /i not "%RESP%"=="BORRAR" (
    echo.
    echo   Cancelado. No se toco nada.
    pause
    exit /b 0
)

if not exist ".venv\Scripts\activate.bat" (
    echo   No encontre el entorno .venv.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo.
echo   Sacando un respaldo antes de borrar...
python manage.py respaldar --sin-fotos
if errorlevel 1 (
    echo.
    echo   El respaldo fallo. NO se borra nada sin respaldo previo.
    pause
    exit /b 1
)

python _productos_sin_existencia.py --borrar --confirmar

echo.
pause
