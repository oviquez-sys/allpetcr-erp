#!/bin/sh
# ============================================================================
#  ARRANQUE DEL ERP EN EL SERVIDOR
# ----------------------------------------------------------------------------
#  Corre las migraciones pendientes y luego levanta el servidor web.
#
#  Por qué existe este archivo y no se pone el comando en el panel de
#  DigitalOcean: el panel NO interpreta el "&&" — pasa toda la línea como si
#  fuera un solo comando con argumentos, y el arranque falla. Un script sí lo
#  entiende. Además así el arranque queda versionado junto al código.
#
#  set -e: si la migración falla, NO levanta el servidor. Es a propósito:
#  vale más que el despliegue se caiga a que la tienda quede funcionando
#  contra una base a medio actualizar.
# ============================================================================
set -e

echo "==> Aplicando migraciones pendientes"
python manage.py migrate --noinput

echo "==> Levantando el servidor"
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8080 \
    --workers 2 --threads 4 \
    --timeout 120 \
    --access-logfile - --error-logfile -
