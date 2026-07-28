@echo off
REM ============================================================
REM   APLICAR MEJORAS - ALLPETCR ERP
REM   Agrega los indices de rendimiento a la base de datos.
REM
REM   Es seguro: los indices NO tocan tus datos, solo aceleran
REM   las consultas. Aun asi, este script respalda ANTES de
REM   cambiar nada y te muestra que base va a modificar.
REM ============================================================

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

echo.
echo ============================================================
echo   PASO 1 de 4: verificar CUAL base se va a modificar
echo ============================================================
echo.
echo Esto es lo mas importante. Si aparece una ruta dentro de
echo esta carpeta (que termina en allpetcr-erp\db.sqlite3), algo
echo esta mal: esa es la base VACIA, no la real. En ese caso
echo cerra esta ventana sin continuar.
echo.

python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup();from django.conf import settings;from pathlib import Path;p=Path(settings.DATABASES['default']['NAME']);print('  Base de datos:',p);print('  Existe:','SI' if p.exists() else 'NO');print('  Tamano:',(str(round(p.stat().st_size/1048576,2))+' MB') if p.exists() else '(no existe)')"

if errorlevel 1 (
    echo.
    echo ERROR: no se pudo leer la configuracion. Revisa que la
    echo variable DJANGO_SECRET_KEY este definida.
    pause
    exit /b 1
)

echo.
echo Si el tamano es 0 MB o dice que NO existe, DETENETE: esa no
echo es tu base real. Falta definir DJANGO_DB_PATH en esta
echo terminal antes de correr este script.
echo.
pause

echo.
echo ============================================================
echo   PASO 2 de 4: respaldo de seguridad
echo ============================================================
echo.
python manage.py respaldar
if errorlevel 1 (
    echo.
    echo ERROR: el respaldo fallo. NO se aplicaran los cambios.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   PASO 3 de 4: cambios que se van a aplicar
echo ============================================================
echo.
python manage.py showmigrations --plan | findstr /C:"[ ]"
echo.
echo Las lineas de arriba (si hay) son los cambios pendientes.
echo Deberian ser 4 migraciones de indices: compras, contabilidad,
echo inventario y ventas. Si aparece algo distinto, cancela.
echo.
echo Presiona una tecla para APLICAR, o cerra la ventana para cancelar.
pause

echo.
echo ============================================================
echo   PASO 4 de 4: aplicando
echo ============================================================
echo.
python manage.py migrate
if errorlevel 1 (
    echo.
    echo ERROR al aplicar. Tu respaldo del paso 2 esta intacto en
    echo la carpeta "respaldos".
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   LISTO
echo ============================================================
echo.
echo Los indices quedaron aplicados. Abri el sistema y revisa que
echo todo funcione normal: el dashboard, el POS y algun reporte.
echo.
pause
