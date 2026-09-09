"""Códigos de barras internos de AllPetCR.

UN EAN NO SE INVENTA. Los números pertenecen a GS1 y se asignan por empresa;
generar EAN al azar es apropiarse de códigos de otras empresas, y eso revienta
el día que el producto pase por una caja ajena (un marketplace, un
distribuidor). Pero la norma SÍ reserva un rango para "circulación
restringida" —los códigos que una tienda usa puertas adentro—: en EAN-8 son
los que empiezan con 0 o con 2. AllPetCR usa el 2.

EAN-8 y no EAN-13 porque la etiqueta mide 35 mm de ancho:

    EAN-8      67 módulos  ->  barras de 0,375 mm
    EAN-13     95 módulos  ->  barras de 0,250 mm
    Code128   123 módulos  ->  barras de 0,250 mm apretando la zona de silencio
    Code128   156 módulos  ->  barras de 0,125 mm, que la pistola NO lee

Menos dígitos es barras más gruesas, y barras más gruesas es leer al primer
intento. Se comprobó en papel el 05/09/2026.

Formato: 2 + seis dígitos correlativos + dígito verificador. Un millón de
códigos posibles contra 532 productos en catálogo.

El dígito verificador lo calcula python-barcode y no una cuenta escrita acá:
si el verificador sale mal, el lector lee un número distinto del que guarda el
ERP y la caja no encuentra el producto. Ese cálculo se delega a quien ya lo
tiene probado.
"""
from __future__ import annotations

import barcode

PREFIJO_INTERNO = "2"
# 1 del prefijo + 6 correlativos. El octavo dígito es el verificador.
LARGO_CORRELATIVO = 6


def con_verificador(cuerpo: str) -> str:
    """EAN-8 completo (8 dígitos) a partir de sus 7 dígitos de datos."""
    return barcode.get("ean8", cuerpo).get_fullcode()


def es_ean_valido(codigo: str) -> bool:
    """True si el código es un EAN-13 o EAN-8 legítimo (verificador incluido).

    Sirve para distinguir el código de fábrica —que hay que conservar— del que
    salió del SKU y conviene reemplazar."""
    codigo = (codigo or "").strip()
    if not codigo.isdigit():
        return False
    for nombre, largo in (("ean13", 13), ("ean8", 8)):
        if len(codigo) == largo:
            try:
                return barcode.get(nombre, codigo[:-1]).get_fullcode() == codigo
            except Exception:
                return False
    return False


def es_interno(codigo: str) -> bool:
    """True si es uno de los códigos internos de AllPetCR (EAN-8 que abre con 2)."""
    codigo = (codigo or "").strip()
    return (len(codigo) == 8 and codigo.startswith(PREFIJO_INTERNO)
            and es_ean_valido(codigo))


def siguiente_interno(usados) -> str:
    """Siguiente código interno libre.

    `usados` es el conjunto de códigos ya ocupados; se pasa desde afuera para
    que este módulo no dependa de los modelos (y para poder asignar una tanda
    entera sin ir a la base en cada vuelta)."""
    mayor = 0
    for codigo in usados:
        if es_interno(codigo):
            mayor = max(mayor, int(codigo[1:1 + LARGO_CORRELATIVO]))
    numero = mayor + 1
    while True:
        candidato = con_verificador(
            PREFIJO_INTERNO + str(numero).zfill(LARGO_CORRELATIVO)
        )
        if candidato not in usados:
            return candidato
        numero += 1


# --- Plan de conversión ------------------------------------------------------
#
# La misma cuenta la usan el comando de consola y la pantalla del ERP. Si cada
# uno la hiciera por su lado, el ensayo mostraría una cosa y la aplicación haría
# otra — y eso se descubre con los 532 códigos ya cambiados.

CONSERVAR = "ean_de_fabrica"
YA_INTERNO = "ya_interno"
CONVERTIR = "convertir"


def clasificar(codigo: str) -> str:
    """Qué hacer con un código: dejarlo quieto o cambiarlo por uno interno."""
    codigo = (codigo or "").strip()
    if es_interno(codigo):
        return YA_INTERNO
    if es_ean_valido(codigo):
        return CONSERVAR
    return CONVERTIR


def plan_de_conversion(productos, usados=None):
    """Qué pasaría con cada producto. NO escribe nada.

    Devuelve un diccionario con las tres listas. `cambios` trae tercias
    (producto, código viejo, código nuevo) ya con los códigos nuevos
    reservados, de forma que no se repitan entre sí ni con los existentes.

    `usados` son los códigos ocupados en TODO el sistema. Importa pasarlo
    cuando `productos` es solo una parte del catálogo (por ejemplo los activos
    de una empresa): si se dedujera de esa parte, un código nuevo podría
    chocar con el de un producto inactivo y el escáner quedaría ambiguo."""
    productos = list(productos)
    if usados is None:
        usados = {(p.codigo_barras or "").strip() for p in productos if p.codigo_barras}
    else:
        usados = set(usados)
    plan = {"conservados": [], "ya_internos": [], "cambios": []}
    for producto in sorted(productos, key=lambda x: str(x.sku)):
        actual = (producto.codigo_barras or "").strip()
        destino = clasificar(actual)
        if destino == YA_INTERNO:
            plan["ya_internos"].append(producto)
        elif destino == CONSERVAR:
            plan["conservados"].append(producto)
        else:
            nuevo = siguiente_interno(usados)
            usados.add(nuevo)
            plan["cambios"].append((producto, actual, nuevo))
    return plan


def aplicar_conversion(plan, ruta_csv) -> int:
    """Escribe los códigos nuevos y deja el respaldo del viejo→nuevo.

    El CSV no es burocracia: si una etiqueta ya impresa quedó pegada a un
    artículo, ese archivo es la única forma de saber a qué producto
    correspondía."""
    import csv

    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["sku", "nombre", "codigo_anterior", "codigo_nuevo"])
        for producto, viejo, nuevo in plan["cambios"]:
            escritor.writerow([producto.sku, producto.nombre, viejo, nuevo])
            producto.codigo_barras = nuevo
            producto.save(update_fields=["codigo_barras"])
    return len(plan["cambios"])
