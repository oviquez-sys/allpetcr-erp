"""Configuración ALLPETCR ERP.

Todo lo que varía entre desarrollo y producción se lee de variables de
entorno. Desarrollo: SQLite. Producción (VPS): PostgreSQL (POSTGRES_HOST).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# PRODUCCIÓN: un solo interruptor. En el VPS se pone DJANGO_PRODUCTION=1 y el
# sistema exige llave secreta real y activa todo el blindaje (HTTPS, cookies
# seguras, HSTS). En local (sin esa variable) todo queda en modo desarrollo:
# la prueba en tu computadora funciona igual que siempre.
PRODUCCION = os.environ.get("DJANGO_PRODUCTION") == "1"

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "solo-para-desarrollo-cambiar-en-produccion",  # nunca usar en el VPS
)
if PRODUCCION and SECRET_KEY == "solo-para-desarrollo-cambiar-en-produccion":
    raise RuntimeError(
        "En producción hay que definir DJANGO_SECRET_KEY con un valor largo y "
        "aleatorio. Generá uno con: python -c \"import secrets;print(secrets.token_urlsafe(64))\""
    )

# En producción DEBUG siempre False (no se puede dejar prendido por error).
# En local sigue el valor de siempre (por defecto encendido).
DEBUG = (not PRODUCCION) and os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

# --- Blindaje que SOLO se activa en producción (detrás de HTTPS) ---
if PRODUCCION:
    SECURE_SSL_REDIRECT = True                # obliga HTTPS
    SESSION_COOKIE_SECURE = True              # la cookie de sesión solo viaja cifrada
    CSRF_COOKIE_SECURE = True                 # idem para el token anti-CSRF
    SECURE_HSTS_SECONDS = 31536000            # 1 año; el navegador exige HTTPS
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    X_FRAME_OPTIONS = "DENY"
    # Detrás de un proxy (nginx) que termina el TLS: confía en su cabecera.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # CSRF necesita el/los dominios reales para aceptar formularios.
    CSRF_TRUSTED_ORIGINS = [
        o.strip() for o in os.environ.get("DJANGO_CSRF_ORIGINS", "").split(",") if o.strip()
    ]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # módulos del ERP
    "core",
    "catalogo",
    "inventario",
    "caja",
    "ventas",
    "contabilidad",
    "compras",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.CurrentUserMiddleware",  # usuario/IP para auditoría
    "core.middleware.AdminSoloGerente",       # /admin solo para gerentes
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.media",
            ],
            # Filtro de formato CR (miles con punto, decimales con coma)
            # disponible en TODAS las plantillas sin {% load %}.
            "builtins": ["core.templatetags.formato"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["POSTGRES_HOST"],
            "NAME": os.environ.get("POSTGRES_DB", "allpetcr"),
            "USER": os.environ.get("POSTGRES_USER", "allpetcr"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    # DJANGO_DB_PATH permite sacar la base de datos de carpetas sincronizadas
    # (OneDrive/Dropbox), donde SQLite falla por bloqueo de archivos.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Costa_Rica"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]  # logo y otros estáticos del proyecto

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"  # fotos de productos y otros archivos subidos

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"

# --- Protección contra fuerza bruta en el login (django-axes) ---
# Se activa con DJANGO_ENABLE_AXES=1 y el paquete instalado (pip install django-axes).
# Gated así para que la prueba local sin el paquete no se rompa.
if os.environ.get("DJANGO_ENABLE_AXES") == "1":
    INSTALLED_APPS += ["axes"]
    # El backend de axes debe ir PRIMERO para poder bloquear.
    AUTHENTICATION_BACKENDS = [
        "axes.backends.AxesStandaloneBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]
    # El middleware de axes debe ir de ÚLTIMO.
    MIDDLEWARE += ["axes.middleware.AxesMiddleware"]
    AXES_FAILURE_LIMIT = 5           # 5 intentos fallidos
    AXES_COOLOFF_TIME = 1            # bloquea 1 hora
    AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
    AXES_RESET_ON_SUCCESS = True

# --- Registro de errores y accesos (logs) ---
# En producción escribe a archivo con rotación; en local, a la consola.
_LOG_DIR = Path(os.environ.get("DJANGO_LOG_DIR", BASE_DIR / "logs"))
if PRODUCCION:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _handler = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(_LOG_DIR / "allpetcr.log"),
        "maxBytes": 5 * 1024 * 1024,  # 5 MB por archivo
        "backupCount": 10,            # conserva 10 archivos
        "formatter": "detallado",
    }
else:
    _handler = {"class": "logging.StreamHandler", "formatter": "detallado"}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detallado": {"format": "{asctime} [{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {"principal": _handler},
    "root": {"handlers": ["principal"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["principal"], "level": "ERROR", "propagate": False},
    },
}

# --- Correo (envío de facturas por email) ---
# Sin EMAIL_HOST_PASSWORD configurado, Django usa el backend de consola: no
# manda nada de verdad, solo imprime el correo en la terminal. Así el sistema
# no se rompe si todavía no se configuró el correo.
if os.environ.get("EMAIL_HOST_PASSWORD"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.office365.com")
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", f"AllPetcr <{EMAIL_HOST_USER}>")
    # Sin esto, si el servidor de correo no responde (bloqueo de firewall,
    # SMTP AUTH desactivado sin avisar, red caída), Django puede quedarse
    # colgado esperando en vez de fallar rápido con un error claro.
    EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "20"))
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
