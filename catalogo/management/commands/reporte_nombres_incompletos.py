"""Reporte de nombres de producto que parecen abreviados o incompletos
(ej. "R.C. Adulto"). SOLO lista — no corrige nada.

Por qué no se corrige solo
---------------------------
"R.C." puede ser "Royal Canin" en un producto y una talla o un código interno
en otro; expandir la abreviatura a ciegas puede escribir un nombre que
suena bien pero es falso. Es exactamente el tipo de dato de negocio que
las reglas de esta noche prohíben inventar. El reporte deja la lista lista
para que Oscar la revise y decida caso por caso.

Uso:
    python manage.py reporte_nombres_incompletos
    python manage.py reporte_nombres_incompletos --salida reporte.md
"""
import re

from django.core.management.base import BaseCommand

from catalogo.models import Producto

# Abreviatura: 1 a 4 letras seguidas de un punto (ej. "R.C.", "Ad.", "Nat.").
# \b al final evita marcar decimales como "2.5" o el punto final de una frase.
PATRON_ABREVIATURA = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{1,4}\.(?:[A-ZÁÉÍÓÚÑ]{1,4}\.)*", re.IGNORECASE)

# Nombre sospechosamente corto: pocas palabras Y pocos caracteres a la vez.
# Un nombre de una sola palabra larga ("Rascador") no es incompleto; uno de
# tres palabras cortitas ("Bozal M azul") tampoco. Lo que se busca es el
# patrón "se cortó a la mitad": "Cepillo p/", "Correa 1.", "Bolsa Ad".
PALABRAS_MINIMAS = 3
LARGO_MINIMO = 14


class Command(BaseCommand):
    help = "Lista productos con nombres que parecen abreviados o incompletos, sin corregirlos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salida", default=None,
            help="Si se da, además de imprimir el reporte lo escribe en este archivo (Markdown).",
        )

    def handle(self, *args, **opciones):
        productos = Producto.objects.filter(activo=True).order_by("sku")

        con_abreviatura, cortos = [], []
        for p in productos:
            nombre = p.nombre.strip()
            if PATRON_ABREVIATURA.search(nombre):
                con_abreviatura.append(p)
            palabras = nombre.split()
            if len(palabras) < PALABRAS_MINIMAS and len(nombre) < LARGO_MINIMO:
                cortos.append(p)

        lineas = self._armar_reporte(con_abreviatura, cortos, productos.count())
        texto = "\n".join(lineas)
        self.stdout.write(texto)

        if opciones["salida"]:
            with open(opciones["salida"], "w", encoding="utf-8") as f:
                f.write(texto + "\n")
            self.stdout.write(self.style.SUCCESS(f"\nGuardado en {opciones['salida']}"))

    def _armar_reporte(self, con_abreviatura, cortos, total):
        vistos = {p.pk for p in con_abreviatura} | {p.pk for p in cortos}
        lineas = [
            "# Nombres de producto que parecen abreviados o incompletos",
            "",
            f"Revisados {total} productos activos. {len(vistos)} con algo para revisar. "
            "Esto es un LISTADO, nada se corrigió solo.",
            "",
            f"## Con abreviatura tipo \"R.C.\" ({len(con_abreviatura)})",
            "",
        ]
        if con_abreviatura:
            for p in con_abreviatura:
                lineas.append(f"- `{p.sku}` — {p.nombre}")
        else:
            lineas.append("(ninguno)")

        lineas += ["", f"## Nombres muy cortos, posible corte ({len(cortos)})", ""]
        if cortos:
            for p in cortos:
                lineas.append(f"- `{p.sku}` — {p.nombre}")
        else:
            lineas.append("(ninguno)")

        return lineas
