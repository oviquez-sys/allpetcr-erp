"""Comprueba que el aviso por correo del respaldo llegue de verdad.

Por que existe (02/09/2026)
---------------------------
Todo el sistema de respaldos se probo y funciona. Pero el AVISO por correo
--que es lo que evita repetir los 29 dias de silencio-- nunca se ejecuto, justo
porque ningun respaldo fallo. Es la ultima pieza sin probar, y es la mas
importante: sin el aviso, un respaldo que deje de correr vuelve a pasar
inadvertido.

Esto manda un correo de prueba por el MISMO camino que usaria un fallo real:
la funcion `avisar_por_correo` de `_respaldo_programado.py`. No simula nada.

No toca ningun respaldo. Solo manda el correo.
"""
import os
import sys

# Importar el modulo del respaldo trae consigo django.setup(): se usa
# exactamente el mismo camino que en una falla real, no una copia parecida.
import _respaldo_programado as respaldo  # noqa: E402

print("=" * 70)
print("PRUEBA DEL AVISO POR CORREO")
print("=" * 70)

destino = os.environ.get("RESPALDO_AVISO_A") or os.environ.get("EMAIL_HOST_USER")
print(f"\nDestinatario: {destino or '(NO HAY: falta RESPALDO_AVISO_A o EMAIL_HOST_USER)'}")

if not destino:
    print("\nSin destinatario no hay a quien avisar. Si el respaldo falla, nadie")
    print("se entera. Hay que definir la variable antes de confiar en esto.")
    sys.exit(1)

print("\nMandando el correo por el mismo camino que usaria un fallo real...")
respaldo.avisar_por_correo(
    "[AllPetCR] PRUEBA del aviso de respaldo",
    "Esto es una PRUEBA. No paso nada malo.\n\n"
    "Sirve para comprobar que, el dia que el respaldo falle de verdad, el "
    "aviso llegue a esta bandeja.\n\n"
    "Si estas leyendo esto, el aviso funciona.\n\n"
    "Cuando sea un fallo real, el asunto va a decir 'FALLO el respaldo' y el "
    "cuerpo va a traer el detalle tecnico.",
)

print("\nListo. Revisa la bandeja de servicioalcliente@allpetcr.com.")
print("Puede tardar un minuto en llegar.")
print()
print("SI NO LLEGA: el sistema de respaldos funciona, pero se quedo mudo.")
print("Un respaldo que falla en silencio es el problema original sin resolver.")
