"""El manual de emergencia tiene que coincidir con el sistema de verdad.

Por que existe esta prueba (02/09/2026)
----------------------------------------
RESPALDOS.txt es lo que alguien va a leer el peor dia: el dia que la
computadora no prende. Un manual de emergencia con un comando mal escrito no se
descubre nunca, porque nadie lo lee hasta que hace falta; y para entonces ya no
hay tiempo de averiguar cual era el comando bueno.

Esa noche, escribiendo la version nueva del manual, se documentaron dos
opciones que NO EXISTEN (`--listar` y `--base`). Salio a la luz por casualidad.
Esta prueba lo convierte en algo que no puede volver a pasar: lee el manual,
saca cada `python manage.py ...` que aparece, y comprueba contra el sistema que
el comando exista y que cada opcion este de verdad en ese comando.

La regla general que defiende: la documentacion que promete un comando es parte
del sistema y se prueba como el codigo. Ya se habia pagado el precio de creerle
a un documento --el mismo RESPALDOS.txt aseguraba que los respaldos subian
solos a OneDrive cuando hacia semanas que no.
"""
import re
from pathlib import Path

from django.conf import settings
from django.core.management import get_commands, load_command_class
from django.test import SimpleTestCase

MANUAL = Path(settings.BASE_DIR) / "RESPALDOS.txt"

# "python manage.py restaurar --archivo X.zip --confirmar"
#           grupo 1: el comando        grupo 2: el resto de la linea
INVOCACION = re.compile(r"python\s+manage\.py\s+([a-z_][a-z0-9_]*)([^\n]*)")


def invocaciones_del_manual():
    texto = MANUAL.read_text(encoding="utf-8", errors="replace")
    for comando, resto in INVOCACION.findall(texto):
        opciones = re.findall(r"(--[a-z][a-z0-9-]*)", resto)
        yield comando, opciones


class ManualDeRespaldosTest(SimpleTestCase):
    def test_el_manual_existe(self):
        self.assertTrue(MANUAL.exists(), "Falta RESPALDOS.txt: es el manual de emergencia.")

    def test_el_manual_menciona_algun_comando(self):
        """Si la expresion regular deja de encontrar nada, las pruebas de abajo
        pasarian en vacio y no protegerian de nada. Esto las mantiene honestas."""
        self.assertTrue(list(invocaciones_del_manual()),
                        "El manual no menciona ningun 'python manage.py ...'. "
                        "¿Cambio el formato? Esta prueba dejo de servir.")

    def test_todos_los_comandos_del_manual_existen(self):
        disponibles = get_commands()
        for comando, _ in invocaciones_del_manual():
            with self.subTest(comando=comando):
                self.assertIn(
                    comando, disponibles,
                    f"RESPALDOS.txt manda a correr 'python manage.py {comando}' y ese "
                    f"comando no existe. El dia de la emergencia contestaria "
                    f"'Unknown command'.",
                )

    def test_todas_las_opciones_del_manual_existen(self):
        disponibles = get_commands()
        for comando, opciones in invocaciones_del_manual():
            if comando not in disponibles or not opciones:
                continue
            clase = load_command_class(disponibles[comando], comando)
            parser = clase.create_parser("manage.py", comando)
            validas = {o for accion in parser._actions for o in accion.option_strings}
            for opcion in opciones:
                with self.subTest(comando=comando, opcion=opcion):
                    self.assertIn(
                        opcion, validas,
                        f"RESPALDOS.txt usa '{opcion}' en 'manage.py {comando}' y esa "
                        f"opcion no existe. Opciones reales: {sorted(validas)}",
                    )


class EnsayoDeRestauracionTest(SimpleTestCase):
    """El ensayo repite las opciones de pg_restore; que no se separen.

    `_prueba_restauracion.py` no puede llamar a `manage.py restaurar` porque ese
    comando restaura siempre sobre la base real, que es justo lo que el ensayo
    no debe tocar. Entonces repite la linea de pg_restore. El riesgo es obvio:
    que alguien cambie las opciones en un lado y no en el otro, y el ensayo
    termine probando algo distinto de lo que pasaria en una emergencia.
    """

    OPCIONES = ("--clean", "--if-exists", "--no-owner", "--no-privileges")

    def _banderas(self, ruta):
        texto = Path(ruta).read_text(encoding="utf-8")
        return {o for o in self.OPCIONES if f'"{o}"' in texto}

    def test_ensayo_usa_las_mismas_opciones_que_restaurar(self):
        comando = Path(settings.BASE_DIR) / "core/management/commands/restaurar.py"
        ensayo = Path(settings.BASE_DIR) / "_prueba_restauracion.py"
        self.assertTrue(comando.exists(), "Falta el comando restaurar.")
        self.assertTrue(ensayo.exists(), "Falta el ensayo de restauracion.")
        self.assertEqual(
            self._banderas(comando), self._banderas(ensayo),
            "Las opciones de pg_restore se separaron entre 'manage.py restaurar' y "
            "_prueba_restauracion.py. El ensayo estaria probando otra cosa distinta "
            "de lo que pasaria en una emergencia real.",
        )

    def test_el_ensayo_nunca_apunta_a_la_base_real(self):
        ensayo = (Path(settings.BASE_DIR) / "_prueba_restauracion.py").read_text(encoding="utf-8")
        self.assertIn('BASE_ENSAYO == CFG["NAME"]', ensayo,
                      "El ensayo perdio la guarda que impide trabajar sobre la base real.")
        self.assertIn("allpetcr_ensayo_", ensayo,
                      "El ensayo debe usar un nombre de base propio y desechable.")
