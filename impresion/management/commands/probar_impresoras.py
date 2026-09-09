"""Comprueba las impresoras desde la línea de comandos (lo usa un .bat).

    python manage.py probar_impresoras            # solo diagnóstico
    python manage.py probar_impresoras --imprimir # además saca papel
"""
from django.core.management.base import BaseCommand

from impresion import servicio
from impresion.servicio import ErrorDeImpresion


class Command(BaseCommand):
    help = "Muestra el estado de las impresoras y, con --imprimir, hace una prueba real."

    def add_arguments(self, parser):
        parser.add_argument("--imprimir", action="store_true",
                            help="Saca una prueba en papel de cada impresora.")
        parser.add_argument("--solo", choices=["recibos", "etiquetas"],
                            help="Prueba una sola impresora, para no gastar el papel de la otra.")

    def handle(self, *args, **opciones):
        d = servicio.diagnostico()
        self.stdout.write("=== IMPRESORAS DEL ERP ===")
        self.stdout.write(f"Componente de Windows disponible: {'sí' if d['disponible'] else 'NO'}")
        self.stdout.write(f"Recibos configurada  : {d['impresora_recibos']}  "
                          f"[{'encontrada' if d['recibos_ok'] else 'NO ENCONTRADA'}]")
        self.stdout.write(f"Etiquetas configurada: {d['impresora_etiquetas']}  "
                          f"[{'encontrada' if d['etiquetas_ok'] else 'NO ENCONTRADA'}]")
        self.stdout.write(f"Tiquete automático   : {'sí' if d['tiquete_automatico'] else 'no'}")
        self.stdout.write("Instaladas en Windows:")
        for nombre in d["instaladas"]:
            self.stdout.write(f"  - {nombre}")

        if not opciones["imprimir"]:
            return

        from impresion.prueba import prueba_etiquetas, prueba_recibos
        pruebas = (("recibos", prueba_recibos), ("etiquetas", prueba_etiquetas))
        if opciones["solo"]:
            pruebas = tuple(p for p in pruebas if p[0] == opciones["solo"])
        for nombre, funcion in pruebas:
            try:
                funcion()
                self.stdout.write(self.style.SUCCESS(f"Prueba de {nombre}: enviada."))
            except ErrorDeImpresion as e:
                self.stdout.write(self.style.ERROR(f"Prueba de {nombre}: {e}"))
