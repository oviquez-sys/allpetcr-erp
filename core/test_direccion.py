"""La dirección de la tienda vive en un solo lugar (core/tienda.py).

17/11/2026: Oscar cambió la dirección pública a la de la tarjeta navideña
(«25 m al norte, en diagonal a FarmaValue Heredia»). La vieja estaba copiada a
mano en el catálogo PDF y en el correo de bienvenida. Esta prueba falla si
alguien la vuelve a escribir en cualquier archivo del ERP.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

VIEJAS = ("100 m oeste", "entrada principal de la UNA", "15 m norte")


class LaDireccionViejaNoVuelve(SimpleTestCase):
    def test_ningun_archivo_usa_la_direccion_vieja(self):
        raiz = Path(settings.BASE_DIR)
        culpables = []
        for ruta in list(raiz.rglob("*.py")) + list(raiz.rglob("*.html")) + list(raiz.rglob("*.txt")):
            partes = set(ruta.relative_to(raiz).parts)
            if partes & {".venv", "node_modules", "staticfiles", "migrations"} or ruta.name == "test_direccion.py":
                continue
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
            culpables += [f"{ruta.relative_to(raiz)}: «{v}»" for v in VIEJAS if v in texto]
        self.assertEqual(culpables, [], "La dirección se cambia en core/tienda.py, no a mano.")

    def test_la_direccion_es_la_que_decidio_oscar(self):
        from core.tienda import DIRECCION_TIENDA
        self.assertEqual(DIRECCION_TIENDA, "25 m al norte, en diagonal a FarmaValue Heredia")
