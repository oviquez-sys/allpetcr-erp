"""Cuándo llega un pedido de cada proveedor, y la carga de su ficha desde el
Excel de Oscar (26/11/2026).

POR QUÉ EXISTE
--------------
«Reponer» decía «quedan pocas» con 7 días para todos. Pero Gosbi entrega al
día siguiente y Belina solo los viernes: con 4 días de producto, a Gosbi le
sobra tiempo y con Belina un martes ya es tarde. Oscar tenía los horarios en
un Excel (ENTREGAS_PROVEDORES.xlsx, una hoja por proveedor); aquí se leen y
quedan editables en `compras:proveedores`.

LA REGLA (`llegada`)
--------------------
Si se pide hoy, ¿qué día llega?
1. Si ya pasó la hora límite, hoy no cuenta como día de pedido.
2. El primer día de pedido desde ahí (vacío = cualquiera).
3. Más los días mínimos (si no se anotaron y sí hay días de entrega, 1).
4. El primer día de entrega desde ahí (vacío = de lunes a sábado: ningún
   proveedor entrega en domingo y ese día la tienda no recibe).
Sin días de entrega ni días mínimos no se sabe: `None`, y «Reponer» usa
su regla general.

LECTURA DEL EXCEL (`leer_excel`)
--------------------------------
Cada hoja es un proveedor con filas «Dato | valor». Se toma celular,
contacto, correo, cuentas, nombre (razón social), dirección de bodega,
catálogo, pedidos en línea y horario. **Usuario y contraseña NO se importan**:
el ERP no es lugar para claves de otros sistemas. Del horario, escrito en
palabras, se sacan solo los días que vienen con nombre completo («viernes»),
«un/dos días», «72 h» y «antes de las 5pm». Las abreviaturas («M y J») no:
en Costa Rica la M puede ser martes o miércoles. Lo que no se entiende queda
en el texto para completarlo a mano.
"""
import re
import unicodedata
from datetime import time, timedelta

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _sin_tildes(texto):
    t = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def nombres_de_dias(codigo, vacio="Cualquier día"):
    """"04" → "Lun y Vie"; vacío → `vacio`."""
    dias = [DIAS_CORTOS[int(c)] for c in sorted(set(codigo or "")) if c.isdigit() and int(c) < 7]
    if not dias:
        return vacio
    return dias[0] if len(dias) == 1 else ", ".join(dias[:-1]) + " y " + dias[-1]


def sabe_cuando_llega(proveedor):
    return bool(proveedor and (proveedor.dias_entrega or proveedor.dias_minimos is not None))


def llegada(proveedor, ahora):
    """Fecha en que llega lo que se pide en este momento, o None."""
    if not sabe_cuando_llega(proveedor):
        return None
    dia = ahora.date()
    if proveedor.hora_limite and ahora.time() > proveedor.hora_limite:
        dia += timedelta(days=1)
    pedido = {int(c) for c in proveedor.dias_pedido or "" if c.isdigit()}
    for _ in range(7):
        if not pedido or dia.weekday() in pedido:
            break
        dia += timedelta(days=1)
    minimos = proveedor.dias_minimos
    if minimos is None:
        minimos = 1
    dia += timedelta(days=minimos)
    entrega = {int(c) for c in proveedor.dias_entrega or "" if c.isdigit()} or set(range(6))
    for _ in range(7):
        if dia.weekday() in entrega:
            break
        dia += timedelta(days=1)
    return dia


# --------------------------------------------------------- leer el Excel ----

CAMPOS = {
    "celular": "telefono", "telefono": "telefono",
    "contacto": "contacto",
    "correo": "email",
    "cuentas": "cuenta_bancaria", "cuenta": "cuenta_bancaria",
    "nombre": "razon_social",
    "direccion bodega": "direccion_bodega", "bodega ( direccion)": "direccion_bodega",
    "bodega (direccion)": "direccion_bodega",
    "catalogo": "catalogo",
    "pedidos en linea": "pedidos_en_linea",
    "horario de entrega": "horario_entrega", "horario entregas": "horario_entrega",
    "horario entrega personalizado": "horario_entrega",
}
NO_SE_IMPORTA = {"usuario", "contrasena", "clave", "password"}
ETIQUETAS = {
    "telefono": "Celular", "contacto": "Contacto", "email": "Correo",
    "cuenta_bancaria": "Cuenta", "razon_social": "Razón social",
    "direccion_bodega": "Dirección de bodega", "catalogo": "Catálogo",
    "pedidos_en_linea": "Pedidos en línea", "horario_entrega": "Horario (texto)",
    "notas": "Notas",
}


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    if isinstance(valor, int) and len(texto) == 8:      # celular 86547319 → 8654-7319
        texto = f"{texto[:4]}-{texto[4:]}"
    return texto


def interpretar_horario(texto):
    """Del horario en palabras saca días de pedido, días de entrega, días
    mínimos y hora límite. Lo que no está claro queda vacío."""
    t = _sin_tildes(texto)
    pedido, entrega = set(), set()
    for trozo in re.split(r"[,.;]|\by\s+se\b", t):
        dias = {i for i, d in enumerate(DIAS) if re.search(rf"\b{d}\b", trozo)}
        if re.search(r"\bpedi(do|dos|r)\b", trozo) and not re.search(r"entreg", trozo):
            pedido |= dias
        else:
            entrega |= dias
    minimos = None
    numeros = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
    m = re.search(r"\b(\d+|un|una|uno|dos|tres|cuatro|cinco)\s+dias?\b", t)
    if m:
        minimos = int(m.group(1)) if m.group(1).isdigit() else numeros[m.group(1)]
    m = re.search(r"\b(\d+)\s*(h|hrs?|horas)\b", t)
    if m:
        minimos = max(1, -(-int(m.group(1)) // 24))
    hora = None
    m = re.search(r"antes de las?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", t)
    if m:
        h = int(m.group(1))
        if (m.group(3) or "").startswith("p") and h < 12:
            h += 12
        elif not m.group(3) and h < 8:      # «antes de las 5» en horario de oficina = tarde
            h += 12
        hora = time(min(h, 23), int(m.group(2) or 0))
    return {
        "dias_pedido": "".join(str(d) for d in sorted(pedido)),
        "dias_entrega": "".join(str(d) for d in sorted(entrega)),
        "dias_minimos": minimos,
        "hora_limite": hora.strftime("%H:%M") if hora else "",
    }


def leer_excel(archivo):
    """[{hoja, datos: {campo: texto}, entregas: {...}, omitidos: [...]}].

    `omitidos` dice qué filas no se importaron (usuario y contraseña), para
    mostrarlo en la vista previa sin mostrar su valor."""
    from openpyxl import load_workbook

    wb = load_workbook(archivo, read_only=True, data_only=True)
    hojas = []
    for ws in wb.worksheets:
        datos, horario, notas, omitidos = {}, [], [], []
        for fila in ws.iter_rows(values_only=True):
            valores = [_texto(v) for v in fila]
            if not any(valores):
                continue
            clave = _sin_tildes(valores[0]).strip(" :")
            resto = [v for v in valores[1:] if v]
            if not clave:
                notas.extend(resto)
                continue
            if any(p in clave for p in NO_SE_IMPORTA):
                if resto:
                    omitidos.append(valores[0].strip())
                continue
            campo = CAMPOS.get(clave)
            if campo is None or not resto:
                if resto:
                    notas.append(f"{valores[0].strip()}: {' · '.join(resto)}")
                continue
            if campo == "horario_entrega":
                horario.extend(resto)
            elif campo == "direccion_bodega" and len(resto) > 1:
                datos[campo] = resto[0]
                notas.extend(resto[1:])
            else:
                datos[campo] = " ".join(resto)
        if horario:
            datos["horario_entrega"] = ". ".join(horario)
        if notas:
            datos["notas"] = "\n".join(notas)
        if "email" in datos and "@" not in datos["email"]:
            datos["notas"] = (datos.get("notas", "") + f"\nCorreo: {datos.pop('email')}").strip()
        hojas.append({
            "hoja": ws.title.strip(),
            "datos": datos,
            "entregas": interpretar_horario(datos.get("horario_entrega", "")),
            "omitidos": omitidos,
        })
    wb.close()
    return hojas


def adivinar_proveedor(hoja, proveedores):
    """El proveedor cuyo nombre contiene el de la hoja (o al revés), sin
    tildes ni mayúsculas. Si hay más de uno o ninguno, None: que elija Oscar."""
    h = re.sub(r"[^a-z0-9 ]", "", _sin_tildes(hoja)).strip()
    if not h:
        return None
    candidatos = []
    for p in proveedores:
        n = re.sub(r"[^a-z0-9 ]", "", _sin_tildes(p.nombre)).strip()
        if n and (h in n or n in h):
            candidatos.append(p)
    return candidatos[0] if len(candidatos) == 1 else None


def aplicar(proveedor, fila):
    """Pasa una hoja al proveedor. Solo llena lo que el Excel trae: un dato
    vacío en el Excel no borra lo que ya estaba. Las notas se agregan."""
    cambios = []
    for campo, valor in fila["datos"].items():
        if campo == "notas":
            if valor and valor not in (proveedor.notas or ""):
                proveedor.notas = ((proveedor.notas or "") + "\n" + valor).strip()
                cambios.append(campo)
            continue
        maximo = proveedor._meta.get_field(campo).max_length
        valor = valor[:maximo] if maximo else valor
        if valor and getattr(proveedor, campo) != valor:
            setattr(proveedor, campo, valor)
            cambios.append(campo)
    e = fila["entregas"]
    for campo in ("dias_pedido", "dias_entrega"):
        if e.get(campo) and getattr(proveedor, campo) != e[campo]:
            setattr(proveedor, campo, e[campo])
            cambios.append(campo)
    if e.get("dias_minimos") is not None and proveedor.dias_minimos != e["dias_minimos"]:
        proveedor.dias_minimos = e["dias_minimos"]
        cambios.append("dias_minimos")
    if e.get("hora_limite"):
        h, m = (int(x) for x in e["hora_limite"].split(":"))
        if proveedor.hora_limite != time(h, m):
            proveedor.hora_limite = time(h, m)
            cambios.append("hora_limite")
    if cambios:
        proveedor.save()
    return cambios
