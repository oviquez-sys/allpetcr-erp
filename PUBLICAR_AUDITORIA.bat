@echo off
chcp 65001 >nul
title AllPetCR - Publicar las mejoras de la auditoria
REM ============================================================================
REM  PUBLICAR LAS MEJORAS DE LA AUDITORIA (26/09/2026)
REM ----------------------------------------------------------------------------
REM  Pasa el trabajo de la rama "auditoria-erp-fase2" a "main" y lo sube a
REM  GitHub. DigitalOcean lo publica solo y aplica las actualizaciones de la
REM  base (son campos nuevos: no cambian ni borran datos).
REM
REM  ANTES de darle doble clic:
REM    1. Correr TRAER_RESPALDOS_NUBE.bat y ver que termine bien (respaldo de
REM       hoy). Si falla, NO publicar: avisarle a Claude.
REM    2. Hacerlo en un momento sin clientes: el ERP se reinicia un par de
REM       minutos mientras DigitalOcean publica.
REM ============================================================================
cd /d "%~dp0"
set "LOG=%~dp0resultado_publicar.txt"
echo Publicacion %date% %time% > "%LOG%"

echo.
echo   Antes de seguir: ¿ya corrio TRAER_RESPALDOS_NUBE.bat y termino bien?
choice /c SN /m "  Escriba S para publicar, N para cancelar"
if errorlevel 2 ( echo   Cancelado. & pause & exit /b 0 )

git checkout main >> "%LOG%" 2>&1 || goto :error
git pull --ff-only >> "%LOG%" 2>&1 || goto :error
git merge --ff-only auditoria-erp-fase2 >> "%LOG%" 2>&1 || goto :error
git push >> "%LOG%" 2>&1 || goto :error

echo.
echo   LISTO. DigitalOcean esta publicando (tarda unos minutos).
echo   Despues pruebe una venta y revise que salga el tiquete.
echo   LISTO >> "%LOG%"
pause
exit /b 0

:error
echo.
echo   ERROR: no se publico nada nuevo. Mandele a Claude el archivo
echo   resultado_publicar.txt que quedo en esta carpeta.
pause
exit /b 1
