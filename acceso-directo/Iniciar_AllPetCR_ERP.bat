@echo off
title AllPetCR ERP - Servidor local
cd /d "C:\Users\oviqu\OneDrive\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

echo Activando entorno virtual...
call .venv\Scripts\activate

echo Verificando base de datos PostgreSQL...
if "%POSTGRES_HOST%"=="" (
    echo.
    echo   [ERROR] No se encontro POSTGRES_HOST.
    echo.
    echo   El sistema usa PostgreSQL desde el 28/07/2026. Sin esta variable,
    echo   Django arrancaria contra el SQLite viejo y VERIAS EL SISTEMA VACIO
    echo   aunque los datos esten intactos en PostgreSQL.
    echo.
    echo   Para reparar, abrir PowerShell y ejecutar:
    echo     setx POSTGRES_HOST "localhost"
    echo     setx POSTGRES_DB "allpetcr"
    echo     setx POSTGRES_USER "allpetcr"
    echo     setx POSTGRES_PASSWORD "la-contrasena-local-de-postgres"
    echo     setx POSTGRES_PORT "5432"
    echo.
    echo   Luego cerrar esta ventana y volver a abrir el sistema.
    echo.
    pause
    exit /b 1
)
echo   OK: PostgreSQL configurado (%POSTGRES_DB% en %POSTGRES_HOST%).

echo Verificando clave de Claude (chat de ayuda)...
if "%ANTHROPIC_API_KEY%"=="" (
    echo   [AVISO] No se encontro ANTHROPIC_API_KEY como variable de entorno de Windows.
    echo   El chat de ayuda no va a funcionar hasta configurarla con setx.
) else (
    echo   OK: clave encontrada.
)

echo Abriendo el navegador...
start "" http://127.0.0.1:8000/

echo Iniciando servidor Django...
echo (Para detener el servidor, cerrar esta ventana o presionar Ctrl+C)
echo.
python manage.py runserver

pause
