"""Carga masiva de fotos desde una carpeta, asociando cada archivo a su
producto por el SKU en el NOMBRE del archivo (ej. "75564.jpg" → SKU 75564).

Es un mecanismo distinto de `importar_imagenes`: ese extrae fotos EMBEBIDAS
en el Excel de inventario y las ubica por la fila en que están dibujadas.
Este lee archivos sueltos de una carpeta (ej. una sesión de fotos nueva) y
los ubica por nombre. Ninguno reemplaza al otro.

Uso:
    python manage.py cargar_fotos_por_sku data/fotos_nuevas/
    python manage.py cargar_fotos_por_sku data/fotos_nuevas/ --reemplazar

Por qué NO se adivina el SKU con coincidencia parcial
------------------------------------------------------
Un archivo "75564-2.jpg" o "75564 (copia).jpg" podría interpretarse como del
producto 75564 con una regla "tomá lo de antes del primer separador", pero
esa regla también le pondría la foto de otro producto a cualquier archivo
cuyo nombre por casualidad empiece con un SKU ajeno. El nombre del archivo
(sin extensión) tiene que coincidir EXACTO con un SKU existente. Lo que no
coincide se lista al final para que Oscar lo revise a mano, en vez de
arriesgar una asignación equivocada.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Producto
from core.imagenes import guardar_imagen_producto

EXTENSIONES_VALIDAS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class Command(BaseCommand):
    help = "Carga fotos desde una carpeta, asociando cada archivo a su producto por SKU exacto en el nombre."

    def add_arguments(self, parser):
        parser.add_argument("carpeta", help="Carpeta con los archivos de imagen a cargar.")
        parser.add_argument(
            "--reemplazar", action="store_true",
            help="Sobrescribir la foto de productos que YA tienen una. Por defecto se "
                 "omiten, para no pisar una foto ya curada sin querer.",
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        carpeta = Path(opciones["carpeta"])
        if not carpeta.is_dir():
            raise CommandError(f"No existe la carpeta: {carpeta}")
        reemplazar = opciones["reemplazar"]

        archivos = sorted(
            f for f in carpeta.iterdir()
            if f.is_file() and f.suffix.lower() in EXTENSIONES_VALIDAS
        )
        if not archivos:
            self.stdout.write(self.style.WARNING(
                f"No hay archivos de imagen ({', '.join(sorted(EXTENSIONES_VALIDAS))}) en {carpeta}."
            ))
            return

        por_sku = {p.sku: p for p in Producto.objects.all()}

        guardadas, omitidas, sin_producto = 0, [], []
        for archivo in archivos:
            sku = archivo.stem
            producto = por_sku.get(sku)
            if producto is None:
                sin_producto.append(archivo.name)
                continue
            if producto.imagen and not reemplazar:
                omitidas.append(f"{sku} — {producto.nombre} (ya tiene foto)")
                continue
            rel = guardar_imagen_producto(f"{sku}{archivo.suffix.lower()}", archivo.read_bytes())
            producto.imagen = rel
            producto.save(update_fields=["imagen"])
            guardadas += 1

        self.stdout.write(self.style.SUCCESS(f"Listo: {guardadas} foto(s) cargadas."))
        if omitidas:
            self.stdout.write(self.style.WARNING(
                f"\n  {len(omitidas)} producto(s) ya tenían foto y se omitieron "
                "(usá --reemplazar para forzar):"
            ))
            for linea in omitidas[:15]:
                self.stdout.write(f"    {linea}")
            if len(omitidas) > 15:
                self.stdout.write(f"    … y {len(omitidas) - 15} más.")
        if sin_producto:
            self.stdout.write(self.style.WARNING(
                f"\n  {len(sin_producto)} archivo(s) sin producto con ese SKU exacto:"
            ))
            for nombre in sin_producto[:15]:
                self.stdout.write(f"    {nombre}")
            if len(sin_producto) > 15:
                self.stdout.write(f"    … y {len(sin_producto) - 15} más.")
