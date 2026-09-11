"""Configuración ALLPETCR ERP.

Todo lo que varía entre desarrollo y producción se lee de variables de
entorno. Desarrollo: SQLite. Producción (VPS): PostgreSQL (POSTGRES_HOST).
"""
import os
import sys
from importlib.util import find_spec
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

# --- Proxies inversos de confianza (auditoría 2026-07-28, hallazgo SEG-05) ---
# Solo si la petición llega desde una de estas IP se hace caso a la cabecera
# X-Forwarded-For para registrar el origen en la auditoría. Vacío = no se
# confía en nadie y se usa REMOTE_ADDR, que el cliente no puede falsificar.
# En el VPS: DJANGO_PROXIES_CONFIABLES="127.0.0.1" (el nginx local).
PROXIES_CONFIABLES = tuple(
    p.strip() for p in os.environ.get("DJANGO_PROXIES_CONFIABLES", "").split(",") if p.strip()
)

# --- Duración de la sesión (auditoría 2026-07-28, hallazgo SEG-08) ---
# Django trae 2 semanas por defecto. En una tienda con turnos eso significa
# que el cajero termina, no cierra sesión, y el siguiente opera con SU
# identidad: la auditoría atribuye las ventas a la persona equivocada y el
# arqueo de caja pierde sentido. 12 horas cubre la jornada más larga y obliga
# a autenticarse de nuevo al día siguiente.
SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_HORAS", "12")) * 3600
SESSION_SAVE_EVERY_REQUEST = True  # la jornada se cuenta desde la última acción, no desde el login
SESSION_COOKIE_HTTPONLY = True     # también fuera de producción
SESSION_COOKIE_SAMESITE = "Lax"

# --- Content-Security-Policy (auditoría 2026-07-28, hallazgo SEG-03) ---
# Ver core/seguridad.py: por defecto se bloquean las directivas que no rompen
# nada y el resto va en modo reporte. DJANGO_CSP_ESTRICTA=1 pasa todo a
# bloqueo — activar solo después de sacar el JavaScript en línea.
CSP_ESTRICTA = os.environ.get("DJANGO_CSP_ESTRICTA") == "1"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "storages",  # backend de almacenamiento S3-compatible para fotos (ver MEDIA_STORAGE_BACKEND)
    "rest_framework",
    "rest_framework.authtoken",  # token de autenticación para el sitio web -> ERP (Bloque 3)
    "corsheaders",
    # módulos del ERP
    "core",
    "catalogo",
    "inventario",
    "caja",
    "ventas",
    "contabilidad",
    "compras",
    "pedidos",
    "facturacion_electronica",
    "api",
    "impresion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Sirve los archivos estáticos (CSS, JS, logo) en el servidor. Django NO los
    # sirve solo cuando DEBUG está apagado, así que sin esto el ERP en la nube
    # sale sin estilos. En la computadora local no estorba.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # antes de CommonMiddleware, como pide django-cors-headers
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.CurrentUserMiddleware",  # usuario/IP para auditoría
    "core.middleware.AdminSoloGerente",       # /admin solo para gerentes
    "core.seguridad.CabecerasDeSeguridad",    # CSP y Permissions-Policy (SEG-03)
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# --- API del catálogo y pedidos (Bloque 3, 2026-08-28) ---
#
# CORS: cerrado por defecto (ninguna lista = ningún origen permitido). El
# sitio web se habilita con CORS_ALLOWED_ORIGINS="https://allpetcr.com" (o
# la lista que corresponda, separada por comas) por variable de entorno —
# nunca "permitir cualquier origen" para una API que puede recibir pedidos
# pagados.
_cors_origenes = os.environ.get("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origenes.split(",") if o.strip()]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    # Por defecto nadie entra: cada vista declara su propio permiso
    # (AllowAny para catálogo público, IsAuthenticated para lo que mueve
    # inventario o dinero). Ver api/views.py.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    # Valores de arranque, no una medición (mismo criterio que
    # ReservaStock.PLAZO_MINUTOS): suficiente para navegar el catálogo con
    # holgura, bajo para frenar un raspado agresivo o un abuso del endpoint
    # de pedidos. Se ajustan acá si en producción resultan cortos o largos.
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "120/min",
    },
}

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

# --- Caché (auditoría 2026-07-28, hallazgo PERF-03) ---
# Caché en memoria del proceso. Decisiones y por qué:
#
# NO Redis: para un negocio con un local sería complejidad prematura —un
# servicio más que instalar, monitorear y que se puede caer—. El propio
# auditor lo desaconsejó hasta que haya varios workers.
#
# NO caché en base de datos: en PostgreSQL, una consulta que falla dentro de
# una transacción la aborta ENTERA. Si faltara `createcachetable`, un fallo
# al leer la caché del dashboard podría tumbar operaciones que no tienen nada
# que ver. Cambiar rendimiento por ese riesgo no vale la pena.
#
# Límite conocido y aceptado: con varios workers de gunicorn cada uno tiene su
# copia, así que un indicador puede tardar hasta TIMEOUT en verse igual en
# todos. Para un tablero de dos minutos de vigencia es irrelevante. El día que
# haya varios workers y esto moleste, ahí sí entra Redis.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "allpetcr-dashboard",
        "TIMEOUT": 120,
    }
}

# Durante `manage.py test`, sin caché. Django NO limpia LocMemCache entre
# pruebas, así que una prueba que carga el dashboard deja indicadores viejos
# que la siguiente lee como si fueran suyos: fallos intermitentes que
# dependen del ORDEN en que corren las pruebas, de los más caros de
# diagnosticar. Las pruebas de la caché en sí activan LocMemCache
# explícitamente con override_settings (core/test_dashboard_cache.py).
if "test" in sys.argv:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}

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

# --- Almacenamiento de fotos de producto (Bloque 1, 2026-08-28) ---
#
# Por defecto: disco local (como siempre). Para apuntar a un bucket
# S3-compatible (S3, Cloudflare R2, Backblaze B2) se define
# MEDIA_STORAGE_BACKEND=s3 y las variables AWS_* de abajo — nada de código
# cambia, solo configuración. boto3 ya era una dependencia (respaldo a B2);
# django-storages es la única pieza nueva.
#
# El código NUNCA debe escribir archivos con Path()/open() directo en
# MEDIA_ROOT: siempre a través de django.core.files.storage.default_storage
# (ver core/imagenes.py), que es lo que hace que este interruptor funcione.
if os.environ.get("MEDIA_STORAGE_BACKEND") == "s3":
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": os.environ["AWS_STORAGE_BUCKET_NAME"],
                "endpoint_url": os.environ.get("AWS_S3_ENDPOINT_URL") or None,
                "region_name": os.environ.get("AWS_S3_REGION_NAME") or None,
                "access_key": os.environ.get("AWS_ACCESS_KEY_ID"),
                "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
                "custom_domain": os.environ.get("AWS_S3_CUSTOM_DOMAIN") or None,
                "default_acl": "public-read",
                "querystring_auth": False,  # URLs públicas simples, sin firma que vence
                "file_overwrite": False,
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"

# --- Protección contra fuerza bruta en el login (django-axes) ---
# ACTIVO POR DEFECTO (auditoría 2026-07-28, hallazgo SEG-04).
#
# Antes se activaba solo con DJANGO_ENABLE_AXES=1, así que el comportamiento
# por defecto era SIN protección: el login del admin —que es la puerta única
# de todo el ERP— aceptaba intentos ilimitados. Un defecto de seguridad nunca
# debe ser el valor por defecto.
#
# Ahora la lógica es al revés: se activa salvo que se pida lo contrario, y en
# producción no se puede apagar ni por error. En local se puede desactivar con
# DJANGO_ENABLE_AXES=0 si estorba para probar.
#
# Excepción: durante `manage.py test` se apaga. No es una concesión de
# seguridad — axes rechaza el authenticate() del cliente de pruebas de Django
# porque no le llega un `request` real, y eso rompería las 174 pruebas del
# proyecto sin que exista ningún fallo de verdad. El login de producción sí
# pasa por el middleware y sí queda protegido.
_EN_PRUEBAS = "test" in sys.argv
_AXES_PEDIDO = os.environ.get("DJANGO_ENABLE_AXES", "1") != "0" and not _EN_PRUEBAS
_AXES_DISPONIBLE = find_spec("axes") is not None

if PRODUCCION and not _EN_PRUEBAS:
    if not _AXES_DISPONIBLE:
        raise RuntimeError(
            "django-axes no está instalado y es obligatorio en producción "
            "(protege el login contra fuerza bruta). Instalalo con: "
            "pip install django-axes"
        )
    if not _AXES_PEDIDO:
        raise RuntimeError(
            "DJANGO_ENABLE_AXES=0 no está permitido en producción: dejaría el "
            "login sin límite de intentos. Quitá esa variable de entorno."
        )

if _AXES_PEDIDO and _AXES_DISPONIBLE:
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
# ── Certificados TLS: usar el almacen de Windows, no el de Python ──────────
#
# Python trae su propia lista de autoridades certificadoras y NO mira la de
# Windows. Eso rompe cualquier conexion TLS en una maquina donde un antivirus
# o un proxy corporativo inspecciona el trafico cifrado: esos programas se
# meten en el medio y presentan su propio certificado. Windows confia en el
# (el antivirus lo instalo al instalarse, por eso el navegador funciona), pero
# Python no lo conoce y corta la conexion.
#
# Sintoma exacto que se vio el 02/09/2026 al mandar el primer correo:
#     [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
#     Basic Constraints of CA cert not marked critical
#
# `truststore` hace que Python valide contra el almacen de Windows. OJO con lo
# que esto NO es: no desactiva la verificacion. El certificado se sigue
# validando, solo que contra la lista en la que Windows ya confia. Desactivar
# la verificacion (verify_mode = CERT_NONE) seria abrir la puerta a que
# cualquiera lea las facturas en el camino, y por eso no se hace.
try:
    import truststore
except ImportError:
    # Sin la libreria, Python sigue usando su propia lista. Funciona en
    # cualquier maquina limpia; falla donde haya antivirus con inspeccion TLS.
    TRUSTSTORE_ACTIVO = False
else:
    truststore.inject_into_ssl()
    TRUSTSTORE_ACTIVO = True

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
    # 60 s, no 20 (02/09/2026). La prueba sin adjunto pasaba y el envio de una
    # factura moria con "The read operation timed out": la diferencia es el PDF.
    # En esta maquina el antivirus inspecciona el trafico cifrado, y para
    # hacerlo tiene que descifrar, escanear y volver a cifrar cada adjunto.
    # Eso agrega segundos que con 20 no alcanzaban.
    #
    # Subirlo es seguro: el timeout solo limita cuanto se ESPERA, no cuanto se
    # tarda. Si el correo sale en dos segundos, sale en dos segundos.
    EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "60"))
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --- Reporte diario a los socios (FRA-004, auditoría 2026-08-15) ---
# Control detectivo contra fraude interno: un resumen automático de cada día
# (ventas, regalías/descuentos con autorización de gerente, arqueo de caja,
# ediciones/borrados de AuditLog) que llega a ambos socios sin que nadie
# tenga que entrar a revisar. Separado del login del sistema a propósito: no
# existe un concepto de "socio" en el modelo de usuarios (is_superuser es
# "dueño", no necesariamente los dos), así que los destinatarios se
# configuran aparte, igual que DJANGO_ALLOWED_HOSTS/DJANGO_CSRF_ORIGINS.
REPORTE_DIARIO_DESTINATARIOS = [
    d.strip() for d in os.environ.get("REPORTE_DIARIO_DESTINATARIOS", "").split(",") if d.strip()
]


# --- Impresoras de la tienda (05/09/2026) ---
# El ERP corre en la misma máquina donde están enchufadas las impresoras, así
# que imprime el servidor y el cajero no pasa por el diálogo del navegador en
# cada venta. Cuando el ERP se mude al VPS esto deja de alcanzar y hará falta
# un agente en la caja: por eso toda la impresión está aislada en `impresion/`
# y nada más del ERP habla con Windows.
#
# Los nombres son los que muestra Windows en "Impresoras y escáneres". Si se
# cambian ahí, hay que cambiarlos acá (o en el .env) o el ERP no las encuentra.
IMPRESORA_RECIBOS = os.environ.get("IMPRESORA_RECIBOS", "Caysn 80mm")
IMPRESORA_ETIQUETAS = os.environ.get("IMPRESORA_ETIQUETAS", "Xprinter XP-360B")

# Columnas de la térmica de recibos. 48 es lo normal en 80 mm; algunas traen
# 42. Se comprueba con la regla numerada de /impresion/estado/: si esa fila se
# parte en dos renglones, hay que bajarlo.
ANCHO_TIQUETE = int(os.environ.get("ANCHO_TIQUETE", "48"))

# Pie legal del tiquete. Mientras la empresa esté en Régimen de Tributación
# Simplificada el tiquete NO es un comprobante electrónico y tiene que decirlo.
PIE_TIQUETE = os.environ.get(
    "PIE_TIQUETE",
    "Documento interno de control. Regimen de Tributacion Simplificada: "
    "no constituye comprobante electronico.",
)

# Decisión de Oscar (05/09/2026): el tiquete sale solo al cobrar. Se deja
# apagable por si un día conviene ahorrar papel, pero el valor de fábrica es
# imprimir: en caja, un clic de menos por venta se nota.
TIQUETE_AUTOMATICO = os.environ.get("TIQUETE_AUTOMATICO", "1") != "0"

# Logo del tiquete, en puntos de la impresora (203 por pulgada). 384 puntos son
# 48 mm, que en el papel de 80 mm deja aire a los lados. En 0 el tiquete sale
# sin logo, con el nombre de la empresa en letra grande como antes del
# 09/09/2026.
TIQUETE_LOGO_PUNTOS = int(os.environ.get("TIQUETE_LOGO_PUNTOS", "384"))
# Puntos imprimibles a lo ancho del papel: 576 en las térmicas de 80 mm. Solo
# hay que tocarlo si algún día se pasa a una de 58 mm, que son 384.
TIQUETE_PAPEL_PUNTOS = int(os.environ.get("TIQUETE_PAPEL_PUNTOS", "576"))

# Rollo de etiquetas de la tienda: 44,5 × 31,8 mm, con el precio impreso
# (decisión de Oscar, 05/09/2026).
#
# El 08/09/2026 se cambió de 35 × 25 mm a 44,5 × 31,8 mm: es la única medida
# que tiene el proveedor. La etiqueta más grande además mejora la lectura —
# en 44,5 mm el código de barras entra con barras de 0,25 mm respetando la
# zona de silencio completa, que en 35 mm no se lograba.
#
# Si algún día se compra otro rollo, se cambian estas dos medidas y la
# etiqueta se redibuja sola: todo el dibujo es proporcional a ellas.
ETIQUETA_ANCHO_MM = float(os.environ.get("ETIQUETA_ANCHO_MM", "44.5"))
ETIQUETA_ALTO_MM = float(os.environ.get("ETIQUETA_ALTO_MM", "31.8"))
ETIQUETA_CON_PRECIO = os.environ.get("ETIQUETA_CON_PRECIO", "1") != "0"

# --- Agente de impresión de la tienda (10/09/2026) ---
#
# Desde que el ERP vive en DigitalOcean, el servidor no ve el USB del
# mostrador. Cuando el ERP detecta que no puede imprimir por sí mismo, deja el
# trabajo en una cola y un programita en la computadora de la tienda
# (AGENTE_IMPRESION.bat) lo recoge y lo manda a la impresora. Ver
# impresion/models.py para el diseño completo.
#
# La llave la comparten el servidor y ese programita, y es lo único que
# protege la cola: sin ella, las puertas del agente quedan CERRADAS (no
# abiertas) — ver impresion/agente.py.
IMPRESION_AGENTE_TOKEN = os.environ.get("IMPRESION_AGENTE_TOKEN", "")

# Cuánto vale un trabajo antes de descartarse. Un tiquete que no salió en el
# momento ya no sirve: la venta está registrada y el comprobante se puede
# volver a mandar desde la factura. Sin esto, encender la computadora a
# mediodía escupiría los tiquetes de toda la mañana de golpe.
IMPRESION_VIGENCIA_MINUTOS = int(os.environ.get("IMPRESION_VIGENCIA_MINUTOS", "15"))

# Cuántos días se guardan los trabajos ya terminados. Cada uno pesa cientos de
# kilobytes (la imagen de la etiqueta); sin límite engordan todos los respaldos.
IMPRESION_CONSERVAR_DIAS = int(os.environ.get("IMPRESION_CONSERVAR_DIAS", "7"))

# Solo para probar el camino del agente desde una computadora que SÍ tiene las
# impresoras conectadas. En el servidor no hace falta: allá se detecta solo.
IMPRESION_FORZAR_AGENTE = os.environ.get("IMPRESION_FORZAR_AGENTE") == "1"
