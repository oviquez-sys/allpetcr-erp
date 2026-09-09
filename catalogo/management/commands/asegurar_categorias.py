"""Crea y ordena el árbol de categorías oficial de AllPetCR.

Uso:
    python manage.py asegurar_categorias --dry-run   # ver qué haría
    python manage.py asegurar_categorias             # aplicarlo

Es idempotente: se puede correr las veces que haga falta. Crea lo que falta,
corrige el orden y el padre de lo que ya existe, y NO borra ni renombra nada.

Por qué existe (01/09/2026)
---------------------------
Hasta hoy el catálogo eran cinco categorías planas y CERO subcategorías: las
532 filas del Excel traían la columna "Subcategoría" vacía. Al entrar los
alimentos hacía falta un árbol de verdad, y hacía falta que el ERP y el sitio
lo mostraran igual, porque el menú del sitio tenía las categorías escritas a
mano y no se enteraba de las nuevas.

Este comando es la ÚNICA definición del árbol. El sitio no lo repite: lo lee
del `orden` que publica `exportar_catalogo_web`.

Por qué este orden y no otro
-----------------------------
Alimento primero porque es lo que la gente viene a comprar y lo que mueve el
volumen; Snacks pegado, porque es compra por impulso y se decide junto al
alimento. Lo demás, de mayor a menor surtido.

Por qué las subcategorías de alimento son solo el formato
----------------------------------------------------------
Un producto vive en UNA categoría. Si las subcategorías se solapan —"húmedo" y
"enlatado" son la misma lata— el producto cae en una de las dos de forma
arbitraria y el cliente no lo encuentra buscando por la otra. Seco y húmedo
son excluyentes de verdad: ningún alimento es los dos.

La etapa de vida (cachorro / adulto / senior) NO entra como subcategoría por
la misma razón: un alimento de cachorro también es seco o húmedo. Cuando haga
falta, va como campo aparte del producto, no como rama del árbol.

Y la especie tampoco: `Producto.mascota` ya la resuelve, y un producto puede
ser "Perro y gato" a la vez.

Dietas veterinarias
-------------------
Se crea vacía a propósito. AllPetCR no tiene veterinario todavía (decisión de
Oscar, 01/09/2026), así que no hay producto que ponerle. Queda creada porque
el sitio solo publica categorías CON existencias: mientras esté vacía es
invisible para el cliente, y el día que entre el primer producto aparece sola,
en su lugar, sin tocar código.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import Categoria

# El árbol oficial. (orden, nombre, [hijas]).
#
# Huecos de 10 en 10 entre las raíces para poder intercalar una categoría
# nueva sin renumerar todo. Las hijas van pegadas a su padre.
# CORREGIDO el 01/09/2026. La primera versión de esta lista salió del Excel
# (`data/INVENTARIO_ALLPETCR.xlsx`), cuya columna "Subcategoría" está vacía en
# las 532 filas, y de ahí se concluyó —mal— que el catálogo era plano con cinco
# categorías. La base del ERP tenía otra cosa: 102 categorías en dos niveles,
# con las cinco viejas ya renombradas y repartidas. El Excel es la carga
# inicial de agosto; el ERP siguió evolucionando sin él.
#
# Regla que se saca de ahí: el árbol de categorías se verifica contra la BASE
# (`_verificar_categorias.py`), nunca contra el Excel.
#
# Las raíces de abajo son las que existen de verdad y tienen productos en sus
# hijas. Sus subcategorías NO se listan acá a propósito: son ~75, las creó el
# trabajo de catálogo anterior, y este comando no tiene por qué opinar sobre
# ellas. Solo fija el orden de las raíces y agrega lo que falta.
ARBOL = [
    # Lo nuevo: la rama de alimentos que no existía.
    (10, "Alimento", [
        (11, "Alimento seco"),
        (12, "Alimento húmedo"),
        # Vacía a propósito hasta que haya veterinario. Ver el docstring.
        (13, "Dietas veterinarias"),
    ]),
    (20, "Snacks y premios", []),
    # Lo que ya existía, en el orden en que conviene mostrarlo.
    (30, "Juguetes", []),
    (40, "Paseo", []),
    (50, "Ropa y accesorios", []),
    (60, "Comederos y bebederos", []),
    (70, "Descanso", []),
    (80, "Higiene y aseo", []),
    (90, "Salud y cuidado", []),
    (110, "Arena y sanitarios", []),
    (120, "Rascadores y muebles", []),
    (130, "Transporte", []),
    (140, "Acuario", []),
]
# Se salta el 100 a propósito: es el `orden` por defecto del modelo, o sea
# "nadie la ordenó todavía". Usarlo acá haría imposible distinguir las dos cosas.


class Command(BaseCommand):
    """Ojo con los caracteres del REPORTE: la consola de Windows escribe en
    cp1252 y una flecha Unicode (→, ←) la hace reventar con UnicodeEncodeError.
    Pasó el 01/09/2026. Los textos que se imprimen usan ASCII a propósito; los
    nombres de las categorías sí llevan tilde, y por eso el .bat fija
    `chcp 65001` y `PYTHONIOENCODING=utf-8` antes de llamar a Python."""

    help = "Crea y ordena el árbol de categorías oficial (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="No escribe nada: muestra exactamente qué cambiaría.",
        )
        parser.add_argument(
            "--borrar-vacias", action="store_true",
            help="Borra las categorías raíz que no tienen ni un producto ni una "
                 "subcategoría. Son cascarones que quedaron de reorganizaciones "
                 "anteriores y ensucian el menú. Por defecto solo se reportan.",
        )

    def handle(self, *args, **op):
        seco = op["dry_run"]
        creadas, movidas, reordenadas, borradas = [], [], [], []

        with transaction.atomic():
            for orden, nombre, hijas in ARBOL:
                raiz = self._asegurar(nombre, None, orden, creadas, movidas, reordenadas)
                for orden_hija, nombre_hija in hijas:
                    self._asegurar(nombre_hija, raiz, orden_hija, creadas, movidas, reordenadas)

            # Cascarones: raíz sin productos y sin hijas. Nunca se borra algo
            # con contenido — el ORM ni lo permitiría (Producto.categoria es
            # PROTECT), pero se comprueba igual para que el reporte sea honesto.
            #
            # Las del ARBOL quedan exentas AUNQUE estén vacías. Pasó el
            # 01/09/2026: la primera versión creaba "Snacks y premios" y la
            # borraba tres líneas después, en la misma corrida, porque todavía
            # no tenía productos. Una categoría declarada acá está vacía a
            # propósito —espera mercadería— y borrarla es justo lo contrario
            # de lo que este comando existe para hacer.
            oficiales = {n for _, n, _ in ARBOL} | {
                nh for _, _, hijas in ARBOL for _, nh in hijas
            }
            vacias = [
                c for c in Categoria.objects.filter(padre__isnull=True)
                if c.nombre not in oficiales
                and c.productos.count() == 0
                and c.hijas.count() == 0
            ]
            for c in vacias:
                borradas.append(c.nombre)
            if op["borrar_vacias"]:
                for c in vacias:
                    c.delete()

            if seco:
                transaction.set_rollback(True)

        self._reportar(creadas, movidas, reordenadas, borradas, op["borrar_vacias"], seco)

    def _asegurar(self, nombre, padre, orden, creadas, movidas, reordenadas):
        """Crea la categoría o corrige su padre y su orden. Devuelve el objeto."""
        cat = Categoria.objects.filter(nombre=nombre).first()
        if cat is None:
            cat = Categoria.objects.create(nombre=nombre, padre=padre, orden=orden)
            creadas.append(nombre if padre is None else f"{padre.nombre} > {nombre}")
            return cat

        cambios = []
        padre_id = padre.id if padre else None
        if cat.padre_id != padre_id:
            # Reparentar es delicado: se reporta con nombre y viejo padre para
            # que un movimiento inesperado se note en el resumen.
            anterior = cat.padre.nombre if cat.padre else "(raiz)"
            destino = padre.nombre if padre else "(raiz)"
            movidas.append(f"{nombre}: {anterior} -> {destino}")
            cat.padre = padre
            cambios.append("padre")
        if cat.orden != orden:
            reordenadas.append(f"{nombre}: {cat.orden} -> {orden}")
            cat.orden = orden
            cambios.append("orden")
        if cambios:
            cat.save(update_fields=cambios)
        return cat

    def _reportar(self, creadas, movidas, reordenadas, vacias, borrar, seco):
        w = self.stdout.write
        titulo = "SIMULACIÓN (no se escribió nada)" if seco else "Árbol de categorías al día"
        w(self.style.SUCCESS(f"\n{titulo}"))
        w(f"  Categorías creadas ....... {len(creadas)}")
        w(f"  Cambiadas de lugar ....... {len(movidas)}")
        w(f"  Reordenadas .............. {len(reordenadas)}")
        etiqueta_vacias = "Vacías borradas" if borrar else "Vacías encontradas"
        w(f"  {etiqueta_vacias} .......... {len(vacias)}")

        if vacias and not borrar:
            w(self.style.WARNING(
                "\n  Estas categorías no tienen ni un producto ni una subcategoría."
            ))
            w("  Son cascarones de reorganizaciones anteriores. No estorban a nadie,")
            w("  pero saldrían en el menú del sitio como categorías vacías.")
            w("  Para eliminarlas: volvé a correr con --borrar-vacias.")
            for x in vacias:
                w(f"    {x}")

        for etiqueta, lista in (("Creadas", creadas), ("Movidas", movidas),
                                ("Reordenadas", reordenadas),
                                ("Borradas por vacías" if borrar else None, vacias if borrar else [])):
            if etiqueta is None:
                continue
            if lista:
                w(f"\n  {etiqueta}:")
                for x in lista:
                    w(f"    {x}")

        w("\n  Árbol resultante:")
        for cat in Categoria.objects.filter(padre__isnull=True).order_by("orden", "nombre"):
            productos = cat.productos.count()
            w(f"    {cat.orden:>3}  {cat.nombre}  ({productos} productos)")
            for hija in cat.hijas.order_by("orden", "nombre"):
                n = hija.productos.count()
                nota = "   <- vacia a proposito (sin veterinario todavia)" if hija.nombre == "Dietas veterinarias" and n == 0 else ""
                w(f"    {hija.orden:>3}    - {hija.nombre}  ({n} productos){nota}")

        if seco:
            w(self.style.WARNING("\n  Nada de esto se guardó. Quitá --dry-run para aplicarlo.\n"))
        else:
            w(self.style.SUCCESS(
                "\n  Listo. Para que el sitio vea los cambios: `manage.py exportar_catalogo_web`.\n"
            ))
