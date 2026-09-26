@echo off
title AllPetCR - Publicar las mejoras de la auditoria
REM ============================================================================
REM  PUBLICAR LAS MEJORAS DE LA AUDITORIA (26/09/2026)
REM ----------------------------------------------------------------------------
REM  Pasa el trabajo de la rama "auditoria-erp-fase2" a "main" y lo sube a
REM  GitHub. DigitalOcean lo publica solo y aplica las actualizaciones de la
REM  base (son campos nuevos: no cambian ni borran datos).
REM
REM  OJO AL TOCAR ESTE ARCHIVO: se guarda con saltos de linea de Windows (CRLF)
REM  y sin tildes. La primera version (26/09) quedo con saltos de Linux y cmd.exe
REM  la leyo partida ("EM no se reconoce..."). core/test_arquitectura lo revisa.
REM
REM  ANTES: correr TRAER_RESPALDOS_NUBE.bat y hacerlo en un momento sin
REM  clientes (el ERP se reinicia un par de minutos mientras se publica).
REM ============================================================================
cd /d "%~dp0"
set "LOG=%~dp0resultado_publicar.txt"
echo Publicacion %date% %time% > "%LOG%"

echo.
echo   Antes de seguir: ya corrio TRAER_RESPALDOS_NUBE.bat?
choice /c SN /m "  Escriba S para publicar, N para cancelar"
if errorlevel 2 goto :cancelado

echo   Pasando los cambios a la rama principal...
git checkout main >> "%LOG%" 2>&1
if errorlevel 1 goto :error
git pull --ff-only >> "%LOG%" 2>&1
if errorlevel 1 goto :error
git merge --ff-only auditoria-erp-fase2 >> "%LOG%" 2>&1
if errorlevel 1 goto :error
echo   Subiendo a GitHub...
git push >> "%LOG%" 2>&1
if errorlevel 1 goto :error

echo LISTO >> "%LOG%"
echo.
echo   LISTO. DigitalOcean esta publicando (tarda unos minutos).
echo   Despues pruebe una venta y revise que salga el tiquete.
pause
exit /b 0

:cancelado
echo   Cancelado. No se publico nada.
pause
exit /b 0

:error
echo ERROR >> "%LOG%"
echo.
echo   ERROR: no se publico nada nuevo. Mandele a Claude el archivo
echo   resultado_publicar.txt que quedo en esta carpeta.
pause
exit /b 1
