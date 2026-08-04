@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "WEB=%~dp0..\allpetcr-web"

echo.
echo ===============================================================
echo   SINCRONIZAR INVENTARIO - ERP + SITIO WEB
echo   Fuente: data\INVENTARIO_ALLPETCR.xlsx
echo ===============================================================
echo.
echo   Segun el ensayo previo va a:
echo     - crear 348 productos
echo     - actualizar 184 (183 cambian de nombre)
echo     - cambiar 184 precios (72 suben, 112 bajan)
echo     - ajustar 3 existencias
echo.
echo   Todo queda auditado en CambioPrecio y en el kardex.
echo   El paso 1 saca un respaldo antes de tocar nada.
echo.
pause

REM --- 1/8 -----------------------------------------------------------
echo.
echo [1/8] Entorno de Python y dependencias
echo ---------------------------------------------------------------
REM Se usa .venv a proposito. Es el entorno donde corrieron las 235 pruebas
REM y donde requirements.txt fija Django 5.2 (6.0 no esta validado). El
REM Python global de Windows tiene su propio Django y puede ser otra version:
REM correr migraciones con uno y arrancar el ERP con el otro es como tener
REM dos sistemas distintos apuntando a la misma base.
if not exist ".venv\Scripts\activate.bat" (
    echo   No existe .venv. Creandolo...
    python -m venv .venv
    if errorlevel 1 goto :fallo
)
call .venv\Scripts\activate.bat
if errorlevel 1 goto :fallo
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 goto :fallo
for /f "tokens=2" %%v in ('python -m django --version 2^>^&1') do set DJV=%%v
python -c "import django; print('   Django', django.get_version(), '- entorno .venv')"

REM --- 2/8 -----------------------------------------------------------
echo.
echo [2/8] Respaldo de la base
echo ---------------------------------------------------------------
python manage.py respaldar
if errorlevel 1 goto :fallo

REM --- 3/8 -----------------------------------------------------------
echo.
echo [3/8] Migraciones pendientes
echo ---------------------------------------------------------------
python manage.py migrate
if errorlevel 1 goto :fallo

REM --- 4/8 -----------------------------------------------------------
echo.
echo [4/8] Usuario que firma los cambios
echo ---------------------------------------------------------------
if exist _usuario_sync.txt del _usuario_sync.txt
python manage.py shell < _resolver_usuario.py
if not exist _usuario_sync.txt (
    echo.
    echo   ERROR: no se pudo resolver el usuario que firma.
    goto :fallo
)
set /p FIRMA=<_usuario_sync.txt
del _usuario_sync.txt

REM --- 5/8 -----------------------------------------------------------
echo.
echo [5/8] Sincronizar el inventario
echo ---------------------------------------------------------------
python manage.py sincronizar_inventario --usuario %FIRMA%
if errorlevel 1 goto :fallo

REM --- 6/8 -----------------------------------------------------------
echo.
echo [6/8] Verificar que el kardex cuadra con las existencias
echo ---------------------------------------------------------------
python manage.py reconciliar
if errorlevel 1 (
    echo.
    echo   AVISO: reconciliar reporto diferencias.
    echo   No bloquean la publicacion, pero anotalas y revisalas hoy.
    echo.
    pause
)

REM --- 7/8 -----------------------------------------------------------
echo.
echo [7/8] Fotos y exportacion al sitio
echo ---------------------------------------------------------------
python manage.py importar_imagenes
if errorlevel 1 goto :fallo
python manage.py exportar_catalogo_web
if errorlevel 1 goto :fallo

REM --- 8/8 -----------------------------------------------------------
echo.
echo [8/8] Revisar y construir el sitio web
echo ---------------------------------------------------------------
if not exist "%WEB%\package.json" (
    echo   No encontre allpetcr-web en:
    echo   %WEB%
    echo   El ERP quedo listo; el sitio hay que construirlo aparte.
    goto :listo
)
pushd "%WEB%"
call npm run revisar
if errorlevel 1 (
    echo.
    echo   Las revisiones del sitio fallaron. NO se construyo.
    echo   El ERP si quedo actualizado.
    popd
    goto :fallo
)
call npm run build
if errorlevel 1 (
    echo.
    echo   El build fallo. Mira el mensaje del guardian de datos:
    echo   casi siempre es una foto que no llego a public\productos.
    popd
    goto :fallo
)
popd

REM --- fin -----------------------------------------------------------
:listo
echo.
echo ===============================================================
echo   LISTO
echo ===============================================================
echo.
echo   Cambios firmados por: %FIRMA%
echo.
echo   Que revisar ahora, en este orden:
echo     1. Punto de venta: buscar un producto, ver precio y foto.
echo     2. Precios: abrir un producto y ver su historial de cambio.
echo     3. Sitio: npm run dev en allpetcr-web y abrir el catalogo.
echo.
echo   Si algo quedo mal, el respaldo del paso 2 esta en respaldos\
echo   y se restaura con:  python manage.py restaurar
echo.
pause
exit /b 0

:fallo
echo.
echo ===============================================================
echo   SE DETUVO POR UN ERROR
echo ===============================================================
echo.
echo   El mensaje de arriba dice que paso. Nada quedo a medias:
echo   cada comando corre dentro de su propia transaccion.
echo.
echo   Para volver al estado inicial:
echo     python manage.py restaurar
echo.
pause
exit /b 1
