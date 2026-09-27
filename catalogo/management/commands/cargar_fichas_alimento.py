"""Carga las fichas de alimento desde catalogo/fichas_alimento/*.json (26/09/2026).

    python manage.py cargar_fichas_alimento --dry-run
    python manage.py cargar_fichas_alimento

Por qué archivos JSON en el repositorio
---------------------------------------
Cada ficha es investigación contra una fuente oficial. Guardarla como archivo
versionado deja en git quién cambió qué dato, cuándo y por qué (el mensaje
del commit), además de la fuente y la fecha que ya trae la ficha. El comando
solo la pasa a la base, donde la lee la API del sitio.

Qué toca y qué no
-----------------
- Crea o actualiza la FichaAlimento por su `clave` (valida el vocabulario con
  full_clean: una etiqueta mal escrita detiene la carga entera).
- Vincula cada SKU de la lista `skus` a su ficha.
- Completa `peso_valor` / `peso_unidad` del producto a partir de su
  presentación ("12 lb", "2 kg") SOLO si están vacíos: es la base del precio
  por kilo del futuro comparador.
- NUNCA toca precio, existencias, SKU, código de barras, nombre ni foto.

Todo en una transacción: o entra la carga completa, o nada.
"""
import json
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Categoria, FichaAlimento, Producto

CARPETA = Path(settings.BASE_DIR) / "catalogo" / "fichas_alimento"
CAMPOS = [
    "marca", "linea", "nombre", "especie", "tipo", "etapas", "tamanos_raza", "necesidades",
    "proteina_principal", "sabor", "descripcion_corta", "descripcion", "beneficios",
    "ingredientes", "aditivos", "analisis", "kcal_kg", "kcal_unidad", "unidad_kcal",
    "guia_alimentacion", "fuentes", "estado", "verificado_en", "notas_internas",
]
PESO = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(kg|g|lb|oz|ml|l)\s*$", re.IGNORECASE)
RAICES_ALIMENTO = ("Alimento", "Snacks y premios")


def peso_de(presentacion):
    m = PESO.match(presentacion or "")
    if not m:
        return None, ""
    return Decimal(m.group(1).replace(",", ".")), m.group(2).lower()


class Command(BaseCommand):
    help = "Carga las fichas de alimento (JSON) y vincula sus presentaciones."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Muestra qué haría, sin escribir.")
        parser.add_argument("--carpeta", default=str(CARPETA))

    def handle(self, *args, dry_run, carpeta, **opciones):
        archivos = sorted(Path(carpeta).glob("*.json"))
        if not archivos:
            raise CommandError(f"No hay fichas en {carpeta}")

        creadas = actualizadas = vinculados = pesos = 0
        skus_faltantes = []
        with transaction.atomic():
            for archivo in archivos:
                datos = json.loads(archivo.read_text(encoding="utf-8"))
                clave = datos.get("clave") or archivo.stem
                ficha = FichaAlimento.objects.filter(clave=clave).first()
                nueva = ficha is None
                ficha = ficha or FichaAlimento(clave=clave)
                for campo in CAMPOS:
                    if campo in datos:
                        valor = datos[campo]
                        # json lee 19.7 como float y Decimal(19.7) arrastra ruido
                        # binario (19.699999…) que el validador rechaza.
                        if campo in ("kcal_kg", "kcal_unidad") and isinstance(valor, float):
                            valor = str(valor)
                        # full_clean() deja pasar None en un campo de texto con
                        # blank=True (lo trata como vacío y no lo valida), pero
                        # la base lo rechaza: NOT NULL. Vacío es "".
                        if valor is None and campo not in ("kcal_kg", "kcal_unidad", "verificado_en"):
                            valor = [] if campo in ("etapas", "tamanos_raza", "necesidades", "beneficios", "analisis", "fuentes") else ({} if campo == "guia_alimentacion" else "")
                        setattr(ficha, campo, valor)
                try:
                    ficha.full_clean()
                except ValidationError as e:
                    raise CommandError(f"{archivo.name}: {e.message_dict}")
                ficha.save()
                creadas += nueva
                actualizadas += not nueva

                for sku in datos.get("skus", []):
                    producto = Producto.objects.filter(sku=sku).first()
                    if producto is None:
                        skus_faltantes.append(f"{sku} ({archivo.name})")
                        continue
                    campos = []
                    if producto.ficha_alimento_id != ficha.pk:
                        producto.ficha_alimento = ficha
                        campos.append("ficha_alimento")
                        vinculados += 1
                    if producto.peso_valor is None:
                        valor, unidad = peso_de(producto.presentacion)
                        if valor is not None:
                            producto.peso_valor, producto.peso_unidad = valor, unidad
                            campos += ["peso_valor", "peso_unidad"]
                            pesos += 1
                    if campos:
                        producto.save(update_fields=campos)

            sin_ficha = self._alimentos_sin_ficha()
            if dry_run:
                transaction.set_rollback(True)

        if skus_faltantes:
            self.stdout.write(self.style.WARNING(f"SKU que no existen en esta base ({len(skus_faltantes)}):"))
            for s in skus_faltantes:
                self.stdout.write(f"  {s}")
        if sin_ficha:
            self.stdout.write(self.style.WARNING(f"\nAlimentos activos todavía sin ficha ({len(sin_ficha)}):"))
            for p in sin_ficha:
                self.stdout.write(f"  {p.sku}  {p.nombre}")
        verbo = "Se crearían" if dry_run else "Se crearon"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verbo} {creadas} fichas, {actualizadas} actualizadas, {vinculados} presentaciones "
            f"vinculadas y {pesos} pesos netos completados."
            + (" (simulación: no se escribió nada)" if dry_run else "")))

    def _alimentos_sin_ficha(self):
        raices = Categoria.objects.filter(padre__isnull=True, nombre__in=RAICES_ALIMENTO)
        ids = set(raices.values_list("id", flat=True))
        ids |= set(Categoria.objects.filter(padre__in=raices).values_list("id", flat=True))
        return list(Producto.objects.filter(activo=True, categoria_id__in=ids, ficha_alimento__isnull=True).order_by("sku"))
