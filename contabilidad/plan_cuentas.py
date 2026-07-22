"""Plantilla mínima de cuentas para una PYME comercial costarricense.

Se crea automáticamente por empresa la primera vez que se necesita una
cuenta (ver services.cuenta). Es editable en el admin: agregar cuentas no
rompe nada; el motor solo usa las de CODIGOS.
"""

# (codigo, nombre, naturaleza, es_de_movimiento)
PLANTILLA = [
    ("1", "ACTIVO", "A", False),
    ("11", "Activo circulante", "A", False),
    ("1101", "Caja general", "A", True),
    ("1102", "Bancos", "A", True),
    ("1201", "Cuentas por cobrar clientes", "A", True),
    ("1301", "Inventario de mercadería", "A", True),
    ("2", "PASIVO", "P", False),
    ("2401", "IVA por pagar", "P", True),
    ("3", "PATRIMONIO", "Q", False),
    ("4", "INGRESOS", "I", False),
    ("4101", "Ventas de mercadería", "I", True),
    ("4102", "Descuentos sobre ventas", "I", True),
    ("5", "GASTOS", "G", False),
    ("5101", "Costo de ventas", "G", True),
    ("5102", "Gasto por regalías y promociones", "G", True),
]

# Cuentas que usa el motor, por nombre lógico.
CODIGOS = {
    "caja": "1101",
    "bancos": "1102",
    "cxc": "1201",
    "inventario": "1301",
    "iva_por_pagar": "2401",
    "ventas": "4101",
    "descuentos": "4102",
    "costo_ventas": "5101",
    "gasto_regalias": "5102",
}
