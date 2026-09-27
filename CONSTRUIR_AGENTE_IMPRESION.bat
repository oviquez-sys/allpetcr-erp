@echo off
chcp 65001 >nul
title AllPetCR - Construir el instalador de impresion
cd /d "C:\Users\Usuario\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

REM ============================================================================
REM  ARMA AllPetCR-Impresion.exe (queda en AllPet\INSTALADORES)
REM ----------------------------------------------------------------------------
REM  Solo hace falta si cambia la llave o la direccion del ERP, o el codigo del
REM  agente. Cambiar el tiquete o la etiqueta NO obliga a rearmarlo: eso se
REM  dibuja en el servidor. Ver _construir_agente_impresion.py.
REM
REM  El .exe lleva la llave adentro: NO se sube a GitHub ni se publica.
REM ============================================================================

.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q pyinstaller pystray
.\.venv\Scripts\python.exe _construir_agente_impresion.py
pause
