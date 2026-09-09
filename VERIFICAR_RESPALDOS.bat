@echo off
chcp 65001 >nul
setlocal
title AllPetCR - Verificar los respaldos automaticos
cd /d "%~dp0"

REM La variable NO se llama LOG a proposito (02/09/2026). Se llamaba asi, y
REM RESPALDO_SEMANAL.bat tambien define LOG. Al invocarlo con `call`, el hijo
REM corre en el MISMO entorno y piso la variable del padre: a partir de ahi
REM todo se escribia dentro del registro del semanal, incluido un `type` del
REM propio archivo sobre si mismo. La salida salio duplicada y cortada, y la
REM parte de las tareas nunca se mostro.
REM
REM Tres defensas, no una: nombre propio, `setlocal`, y `cmd /c` en vez de
REM `call` para que el hijo tenga su propio entorno.
set SALIDA=resultado_verificar_respaldos.txt
set PY=.\.venv\Scripts\python.exe

echo.
echo   ============================================================
echo     VERIFICAR QUE LOS RESPALDOS QUEDARON CORRIENDO SOLOS
echo   ============================================================
echo.
echo   Dos cosas:
echo.
echo     1. Que las DOS tareas esten registradas en Windows
echo     2. Correr el respaldo SEMANAL una vez (el de las fotos)
echo        Pesa ~130 MB y puede tardar varios minutos.
echo.

if exist "%SALIDA%" del "%SALIDA%"

echo ===== 1. TAREAS REGISTRADAS EN WINDOWS ===== > "%SALIDA%"
echo   [1 de 2] Revisando las tareas...
schtasks /query /tn "AllPetCR - Respaldo diario"  /fo LIST >> "%SALIDA%" 2>&1
echo. >> "%SALIDA%"
schtasks /query /tn "AllPetCR - Respaldo semanal" /fo LIST >> "%SALIDA%" 2>&1

echo. >> "%SALIDA%"
echo ===== 2. RESPALDO SEMANAL DE PRUEBA (con fotos) ===== >> "%SALIDA%"
echo   [2 de 2] Corriendo el respaldo semanal. Puede tardar varios
echo            minutos: son unos 130 MB subiendo a OneDrive.
cmd /c RESPALDO_SEMANAL.bat
echo   Codigo de salida del semanal: %ERRORLEVEL%  (0 = bien) >> "%SALIDA%"

echo. >> "%SALIDA%"
echo ===== REGISTRO DEL SEMANAL (ultimas 20 lineas) ===== >> "%SALIDA%"
REM Se lee con el Python del proyecto y no con PowerShell (02/09/2026):
REM PowerShell leia el registro con la pagina de codigos del sistema y los
REM acentos salian como "sincronizaciÃ³n". Este Python ya corre en UTF-8 en
REM todos los .bat del proyecto, asi que el texto sale como fue escrito.
REM El -c no lleva ni < ni > : en la consola de Windows son redireccion.
%PY% -c "import io,sys;lineas=io.open('respaldos/log_respaldo_semanal.txt',encoding='utf-8',errors='replace').read().splitlines();print(chr(10).join(lineas[-20:]))" >> "%SALIDA%" 2>&1

echo. >> "%SALIDA%"
echo ===== FIN ===== >> "%SALIDA%"

type "%SALIDA%"
echo.
echo   ------------------------------------------------------------
echo   Copiale a Claude TODO lo que salio arriba.
echo   ------------------------------------------------------------
echo.
pause
