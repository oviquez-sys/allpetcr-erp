@echo off
setlocal
pushd "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
echo ---------------------------------------- >> logs\reconciliar.log
echo %date% %time% >> logs\reconciliar.log
".venv\Scripts\python.exe" manage.py reconciliar >> logs\reconciliar.log 2>&1
popd
