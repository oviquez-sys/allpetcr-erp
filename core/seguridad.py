"""Cabeceras de seguridad que Django no trae de serie.

Auditoría 2026-07-28, hallazgo SEG-03: el ERP ya enviaba X-Frame-Options,
X-Content-Type-Options y Referrer-Policy, pero le faltaban
Content-Security-Policy y Permissions-Policy.

Por qué la CSP va en dos velocidades
------------------------------------
Una CSP estricta (sin 'unsafe-inline') es la defensa que convierte cualquier
XSS en no explotable. Pero este ERP tiene 59 atributos `onclick=` en las
plantillas y nueve bloques `<script>` en línea. Activar la CSP estricta de
golpe rompería el punto de venta completo — botones que no responden, sin
error visible. Eso es peor que el riesgo que evita.

Así que se separa en dos grupos:

1. BLOQUEO YA — directivas que no rompen nada de lo que el ERP hace hoy y
   que aun así cierran vectores reales:
     · frame-ancestors 'none'  → nadie puede embeber el ERP en un iframe
                                 (clickjacking sobre el POS o sobre anular
                                 una venta).
     · object-src 'none'       → nada de <object>/<embed>, que son vías
                                 clásicas de ejecución.
     · base-uri 'self'         → impide que un <base> inyectado redirija
                                 todas las URL relativas de la página a un
                                 servidor ajeno.
     · form-action 'self'      → un formulario inyectado no puede enviar los
                                 datos a otro dominio.

2. SOLO REPORTE — el resto (default-src, script-src, style-src). Se manda en
   Content-Security-Policy-Report-Only: el navegador NO bloquea, solo avisa
   en su consola. Sirve para ver exactamente qué habría que arreglar antes de
   pasar a bloqueo, sin arriesgar la operación.

Cómo pasar a bloqueo total (el trabajo pendiente, honestamente):
  1. Migrar los `onclick=` a addEventListener en archivos .js estáticos.
  2. Sacar los `<script>` en línea a /static/.
  3. Probar con DJANGO_CSP_ESTRICTA=1 en local y revisar la consola.
  4. Activar esa variable en el VPS.
Mientras tanto, la protección real contra el XSS del POS es escapar los datos
antes de insertarlos en el DOM (hallazgo SEG-02), que ya está hecho. La CSP
es defensa en profundidad, no el arreglo principal.
"""
from django.conf import settings

# Sin cámara, micrófono, ubicación, sensores ni pagos: el ERP no usa ninguna
# de esas capacidades, así que negarlas no cuesta nada y limita el daño de
# cualquier script que se llegue a colar.
PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(), usb=()"
)

# Grupo 1: se aplica en bloqueo. Verificado contra las plantillas actuales.
CSP_BLOQUEO = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"

# Grupo 2: solo reporte. Chart.js se sirve desde cdnjs en el dashboard.
_CDN = "https://cdnjs.cloudflare.com"
CSP_OBJETIVO = (
    f"default-src 'self'; script-src 'self' {_CDN}; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    f"{CSP_BLOQUEO}"
)


class CabecerasDeSeguridad:
    """Añade Permissions-Policy y Content-Security-Policy a cada respuesta.

    No pisa cabeceras que otra capa (nginx, un decorador) ya haya puesto.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.estricta = getattr(settings, "CSP_ESTRICTA", False)

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        if self.estricta:
            response.setdefault("Content-Security-Policy", CSP_OBJETIVO)
        else:
            response.setdefault("Content-Security-Policy", CSP_BLOQUEO)
            response.setdefault("Content-Security-Policy-Report-Only", CSP_OBJETIVO)
        return response
