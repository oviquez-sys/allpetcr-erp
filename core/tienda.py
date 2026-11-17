"""Datos públicos de la tienda que el ERP escribe en lo que ve el cliente.

Un solo lugar para la dirección (17/11/2026): estaba copiada a mano en el
catálogo PDF y en el correo de bienvenida, y cuando cambió hubo que buscarla
archivo por archivo. `core/test_direccion.py` falla si la vieja reaparece.

Ojo: esta es la dirección para que el cliente LLEGUE. La dirección fiscal
del emisor (Empresa.provincia / canton / distrito / otras_senas, para la
factura electrónica) es otra cosa: tiene que ser la inscrita en Hacienda y se
llena en el admin con lo que confirme el contador.
"""

# Decisión de Oscar, 17/11/2026: la misma frase de la tarjeta navideña.
DIRECCION_TIENDA = "25 m al norte, en diagonal a FarmaValue Heredia"
DIRECCION_TIENDA_COMPLETA = f"Heredia centro, {DIRECCION_TIENDA}"
