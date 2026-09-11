@echo off
chcp 65001 >nul
title AllPetCR - Agente de impresion
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

REM ============================================================================
REM  AGENTE DE IMPRESION
REM ----------------------------------------------------------------------------
REM  Este es el programa que imprime los tiquetes y las etiquetas.
REM
REM  Desde que el ERP vive en internet (DigitalOcean), el servidor no ve las
REM  impresoras del mostrador. Este programa corre ACA, en la computadora de
REM  la tienda, le pregunta al ERP que hay para imprimir y lo manda al rollo.
REM
REM  Dejalo abierto mientras la tienda este abierta. Si se cierra, el ERP
REM  sigue funcionando: solo deja de salir papel.
REM
REM  La carpeta va fija y no con %~dp0, por lo mismo que SUBIR_CAMBIOS.bat:
REM  si alguien deja una copia de este archivo en el Escritorio, tiene que
REM  seguir encontrando el ERP.
REM ============================================================================

if not exist ".venv\Scripts\activate.bat" (
    echo   No encontre el entorno .venv en la carpeta del ERP.
    echo   Avisale a Claude.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python _agente_impresion.py

echo.
echo   El agente se detuvo. Mientras este cerrado no sale papel.
pause
