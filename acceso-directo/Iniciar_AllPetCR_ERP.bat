@echo off
title AllPetCR ERP - Servidor local
cd /d "C:\Users\oviqu\OneDrive\Desktop\GRUPO VAYRU\AllPet\CLAUDE\allpetcr-erp"

echo Activando entorno virtual...
call .venv\Scripts\activate

echo Configurando ruta de base de datos (fuera de OneDrive)...
set DJANGO_DB_PATH=C:\allpetcr-datos\db.sqlite3

echo Abriendo el navegador...
start "" http://127.0.0.1:8000/

echo Iniciando servidor Django...
echo (Para detener el servidor, cerrar esta ventana o presionar Ctrl+C)
echo.
python manage.py runserver

pause
