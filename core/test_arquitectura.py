"""Pruebas de arquitectura: reglas del proyecto que se verifican solas.

Auditoría 2026-07-28, hallazgo ARQ-01. El aislamiento multi-empresa estaba a
medio aplicar: existía core/tenancy.py, pero trece puntos del código
resolvían la empresa con `Empresa.objects.first()` y tres consultas de
producto no filtraban por empresa. La abstracción existía; su cumplimiento
era voluntario.

El auditor lo dijo mejor de lo que yo podría: "una regla que no se verifica
automáticamente se rompe en tres meses". Estas pruebas son esa verificación.
No comprueban comportamiento, comprueban que el código respete un acuerdo.

Por qué importa aunque hoy haya UNA sola empresa: el día que haya dos, cada
consulta sin filtrar deja ver inventario, precios y ventas de la otra. Migrar
trece llamadas dispersas con el sistema en producción es mucho más riesgoso
que sostener la regla desde ahora.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

# Apps del proyecto (no las de terceros ni el entorno virtual).
APPS = ["caja", "catalogo", "compras", "contabilidad", "core", "inventario", "ventas"]


def _archivos_python():
    """Todos los .py del proyecto, sin migraciones ni pruebas.

    Las migraciones se excluyen porque son historia congelada: no se editan.
    Las pruebas, porque legítimamente construyen escenarios con varias
    empresas y necesitan tocarlas directamente.
    """
    for app in APPS:
        base = Path(settings.BASE_DIR) / app
        if not base.exists():
            continue
        for ruta in base.rglob("*.py"):
            partes = ruta.parts
            if "migrations" in partes:
                continue
            if ruta.name.startswith("test") or ruta.name.endswith("_tests.py"):
                continue
            yield ruta


class ResolucionDeEmpresaTest(TestCase):
    """`Empresa.objects.first()` solo puede vivir en un lugar: core/tenancy.py."""

    PATRON = re.compile(r"Empresa\.objects\.first\(\)")
    # tenancy.py es el punto único de resolución; ese ES su trabajo.
    # chat_tools.py no recibe `request` (lo llama el bucle de herramientas del
    # asistente), así que resuelve por su cuenta y queda documentado ahí.
    PERMITIDOS = {"tenancy.py", "chat_tools.py"}

    def test_nadie_resuelve_la_empresa_por_su_cuenta(self):
        infractores = []
        for ruta in _archivos_python():
            if ruta.name in self.PERMITIDOS:
                continue
            # Los comandos de `manage.py` corren fuera de una petición: no hay
            # `request` del que sacar la empresa. Es una excepción real, no un
            # descuido. Cuando el sistema sea multi-empresa habrá que darles un
            # argumento --empresa; queda anotado aquí para que no se olvide.
            if "management" in ruta.parts and "commands" in ruta.parts:
                continue
            texto = ruta.read_text(encoding="utf-8")
            for n, linea in enumerate(texto.splitlines(), 1):
                if self.PATRON.search(linea) and not linea.strip().startswith("#"):
                    infractores.append(f"{ruta.relative_to(settings.BASE_DIR)}:{n}")
        self.assertEqual(
            infractores,
            [],
            "Estos puntos resuelven la empresa sin pasar por core/tenancy.py:\n  "
            + "\n  ".join(infractores)
            + "\n\nUsá `empresa_actual(request)`. El día que el sistema sea "
            "multi-empresa, cambiar tenancy.py debe bastar para que todo el "
            "ERP respete la separación.",
        )


class ConsultasDeProductoTest(TestCase):
    """Ninguna consulta de producto puede omitir el filtro por empresa."""

    def test_las_consultas_de_producto_filtran_por_empresa(self):
        # Busca `Producto.objects.filter(...)` cuyo contenido no mencione
        # `empresa`. Es un chequeo de texto, deliberadamente simple: prefiero
        # una regla que cualquiera pueda leer y entender a un análisis de AST
        # que nadie mantenga.
        patron = re.compile(r"Producto\.objects\.filter\(([^)]*)\)")
        # Campos globalmente únicos: filtrar por empresa en un chequeo de
        # unicidad sería un error, no una mejora. El código de barras tiene que
        # ser único en TODO el sistema o el escáner del POS sería ambiguo, y el
        # SKU se usa igual. Estos son chequeos de colisión, no listados.
        UNICOS = ("sku=", "codigo_barras=", "pk=", "id=")
        infractores = []
        for ruta in _archivos_python():
            # Los comandos de manage.py operan sobre toda la base a propósito
            # (importar, exportar, asignar códigos). Misma excepción que arriba.
            if "management" in ruta.parts and "commands" in ruta.parts:
                continue
            texto = ruta.read_text(encoding="utf-8")
            for m in patron.finditer(texto):
                argumentos = m.group(1)
                if "empresa" in argumentos:
                    continue
                if any(argumentos.strip().startswith(u) for u in UNICOS):
                    continue
                linea = texto[: m.start()].count("\n") + 1
                infractores.append(f"{ruta.relative_to(settings.BASE_DIR)}:{linea}")
        self.assertEqual(
            infractores,
            [],
            "Estas consultas de producto no filtran por empresa:\n  "
            + "\n  ".join(infractores)
            + "\n\nAgregá `empresa=empresa_actual(request)`.",
        )


class ExcepcionesSilenciosasTest(TestCase):
    """Auditoría 2026-07-28, BE-03: nada de `except ...: pass` sin registro.

    Tolerar un fallo puede ser correcto; no dejar rastro de que ocurrió, no.
    Cuando el problema se manifieste —fotos que faltan, auditorías huecas— no
    va a haber forma de averiguar la causa.
    """

    def test_no_hay_except_seguido_de_pass(self):
        patron = re.compile(r"except[^\n]*:\s*\n\s*pass\b")
        infractores = []
        for ruta in _archivos_python():
            texto = ruta.read_text(encoding="utf-8")
            for m in patron.finditer(texto):
                linea = texto[: m.start()].count("\n") + 1
                infractores.append(f"{ruta.relative_to(settings.BASE_DIR)}:{linea}")
        self.assertEqual(
            infractores,
            [],
            "Estos bloques se tragan la excepción sin dejar rastro:\n  "
            + "\n  ".join(infractores)
            + "\n\nSeguir adelante está bien; hacerlo en silencio no. "
            "Agregá logger.exception(...) antes de continuar.",
        )


class AuditoriaConectadaPorSenderTest(TestCase):
    """Auditoría 2026-07-28, BE-01: los receptores no vuelven a ser globales."""

    def test_las_senales_se_registran_por_sender_explicito(self):
        ruta = Path(settings.BASE_DIR) / "core" / "signals.py"
        texto = ruta.read_text(encoding="utf-8")
        self.assertNotIn(
            "@receiver(post_save)",
            texto,
            "Un @receiver sin `sender` se ejecuta en CADA save() del proyecto. "
            "Conectá por modelo en signals.conectar(), como está documentado.",
        )
        self.assertIn("post_save.connect(", texto)
        self.assertIn("sender=modelo", texto)

    def test_los_modelos_de_detalle_siguen_fuera_de_la_auditoria(self):
        """Volver a auditarlos multiplica las filas por venta sin aportar
        trazabilidad: su documento padre ya queda auditado y es inmutable."""
        from core.signals import AUDITED, NO_AUDITADOS_A_PROPOSITO

        solapados = AUDITED & NO_AUDITADOS_A_PROPOSITO
        self.assertEqual(
            solapados,
            set(),
            f"Estos modelos están marcados como no auditados a propósito pero "
            f"volvieron a AUDITED: {solapados}",
        )


class ReglaSoloEnExistenciaTest(TestCase):
    """Regla del 02/08/2026: el ERP lista solo lo que hay en existencia.

    Las pantallas que listan productos para verlos o venderlos pasan por
    `catalogo.consultas.productos_visibles`. Las dos que NO —compras y ajuste
    de inventario— son excepciones documentadas, y esta prueba las fija: si
    alguien las "corrige" por consistencia, rompe el sistema de una forma que
    no da error, solo hace desaparecer productos para siempre.
    """

    # Archivo -> por qué se salta el filtro. Estar en esta lista obliga a
    # escribir la razón; una excepción sin razón no pasa la revisión.
    EXCEPCIONES = {
        "compras/views.py": "es la pantalla que hace que un agotado deje de estarlo",
        "inventario/forms.py": "corrige el conteo, filtrar por stock filtra el dato a corregir",
    }
    # Pantallas que listan productos y sí deben respetar la regla.
    OBLIGADAS = ["ventas/views.py", "catalogo/views.py", "inventario/views.py"]

    def test_las_pantallas_de_listado_usan_productos_visibles(self):
        faltan = []
        for relativa in self.OBLIGADAS:
            texto = (Path(settings.BASE_DIR) / relativa).read_text(encoding="utf-8")
            if "productos_visibles" not in texto:
                faltan.append(relativa)
        self.assertEqual(
            faltan,
            [],
            "Estas pantallas listan productos sin pasar por "
            "catalogo.consultas.productos_visibles:\n  " + "\n  ".join(faltan)
            + "\n\nSi la pantalla necesita ver los agotados, usá "
            "productos_visibles(..., incluir_agotados=True) para que la "
            "excepción quede escrita.",
        )

    def test_las_excepciones_siguen_documentadas(self):
        """Cada excepción tiene que explicarse en el archivo que la comete.

        No es burocracia: el fallo que evita es silencioso. Un producto que se
        agota y desaparece del selector de compras no lanza ningún error —
        simplemente ya nunca se puede reponer, y el día que alguien lo note
        van a haber pasado semanas.
        """
        sin_explicar = []
        for relativa in self.EXCEPCIONES:
            texto = (Path(settings.BASE_DIR) / relativa).read_text(encoding="utf-8")
            if "EXCEPCIÓN DELIBERADA" not in texto:
                sin_explicar.append(relativa)
        self.assertEqual(
            sin_explicar,
            [],
            "Estos archivos consultan productos sin el filtro de existencias y "
            "ya no explican por qué:\n  " + "\n  ".join(sin_explicar)
            + "\n\nSi la excepción sigue siendo válida, restaurá el comentario "
            "«EXCEPCIÓN DELIBERADA». Si ya no lo es, aplicá "
            "catalogo.consultas.productos_visibles y sacá el archivo de "
            "EXCEPCIONES en esta prueba.",
        )
