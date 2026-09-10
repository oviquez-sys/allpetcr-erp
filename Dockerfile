# ============================================================================
#  ALLPETCR ERP — imagen del servidor
# ----------------------------------------------------------------------------
#  Esto es la "receta" con la que DigitalOcean arma el servidor cada vez que
#  se sube un cambio a GitHub. No hay que tocarla para el trabajo del día a
#  día: solo si se agrega una dependencia del sistema.
#
#  Lo que NO va acá: la impresión de tiquetes y etiquetas. Vive en
#  impresion/windows.py, necesita Windows, y solo se importa al momento de
#  imprimir. El ERP arranca igual en este servidor sin ella.
# ============================================================================
FROM python:3.12-slim

# Python sin buffer: los mensajes salen al registro apenas ocurren, no cuando
# se llena el buffer. Sin esto un error puede tardar en aparecer en el log.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias del sistema. libpq5 es lo que psycopg necesita para hablar con
# PostgreSQL; las libjpeg/zlib son para que Pillow dibuje las etiquetas.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Las dependencias primero y solas: así, mientras requirements.txt no cambie,
# reconstruir la imagen no vuelve a bajar todo (los despliegues son rápidos).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Junta CSS, JS y logo en /app/staticfiles para que whitenoise los sirva.
# DJANGO_SECRET_KEY de relleno: collectstatic no la usa, pero settings.py la
# exige en producción y este paso corre durante la construcción, sin secretos.
RUN DJANGO_SECRET_KEY=solo-para-construir-la-imagen \
    DJANGO_PRODUCTION= \
    python manage.py collectstatic --noinput

# Usuario sin privilegios: si alguien logra ejecutar algo dentro del
# contenedor, no lo hace como administrador.
RUN useradd --create-home --shell /usr/sbin/nologin allpet \
    && chown -R allpet:allpet /app
USER allpet

EXPOSE 8080

# El arranque (migraciones + servidor) vive en entrypoint.sh, versionado con
# el código. Se invoca con "sh" para no depender del permiso de ejecución,
# que Windows no conserva al subir a git.
CMD ["sh", "/app/entrypoint.sh"]
