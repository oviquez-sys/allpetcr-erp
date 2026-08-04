# Resuelve qué usuario firma los cambios de la sincronización.
#
# Se corre con:  python manage.py shell < _resolver_usuario.py
#
# Por qué existe: `sincronizar_inventario --usuario X` exige que X ya exista, y
# `createsuperuser` es interactivo (pide contraseña por teclado), así que no se
# puede encadenar dentro de un .bat. Esto resuelve el usuario sin intervención:
# reutiliza el superusuario que ya esté en la base y solo crea uno si no hay
# ninguno.
#
# Escribe el username en _usuario_sync.txt porque el .bat lo necesita como
# variable, y leerlo de la salida del shell no es confiable: el logging de
# django-axes se mezcla con stdout.

from django.contrib.auth import get_user_model

U = get_user_model()

# El más antiguo, que es el que Oscar creó al montar el sistema. Ordenar por id
# evita que el usuario que firme cambie entre corridas si se agregan usuarios.
usuario = U.objects.filter(is_superuser=True).order_by("id").first()

if usuario is None:
    usuario = U.objects.create_superuser(
        username="oscar",
        email="o.viquez@hotmail.com",
        password="AllPet2026.Cambiar",
    )
    print("")
    print("  *** SE CREO EL USUARIO 'oscar' ***")
    print("  Contrasena temporal: AllPet2026.Cambiar")
    print("  CAMBIALA hoy mismo desde /admin -> Usuarios -> oscar.")
    print("")

with open("_usuario_sync.txt", "w", encoding="ascii") as f:
    f.write(usuario.username)

print("Los cambios quedaran firmados por: %s" % usuario.username)
