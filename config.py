import unicodedata

PALLET_LARGO = 120
PALLET_ANCHO = 100

ALTURA_PALLET_VACIO = 14.92
ALTURA_TOTAL_MIN = 190
ALTURA_TOTAL_MAX = 195
ALTURA_PRODUCTO_MIN = 175.08
ALTURA_PRODUCTO_MAX = 180.08

PESO_ALERTA_KG = 1350

# [PARCHE P4] Tope duro de peso usado como RESTRICCIÓN en el apilado (Paso 4).
# Antes el peso solo se calculaba en el Paso 5 y se etiquetaba: el motor podía
# emitir pallets de 1.600 kg que la operación no puede ejecutar. Se deja como
# constante separada de PESO_ALERTA_KG para poder divergirlas (ej. restringir a
# 1.300 y alertar a 1.350) sin tocar código.
PESO_MAX_PALLET_KG = 1350

PESO_CAJA_MIN = 0.05
PESO_CAJA_MAX = 100

TOLERANCIA_ALTURA_CAMA_MIXTA = 3

# [PARCHE P5] Fracción mínima de la base 120x100 que una cama debe cubrir para
# poder sostener otra cama encima. Sin esto, 3 cajas sueltas de Licores pueden
# quedar como base de 170 cm de producto. Es una restricción de SEGURIDAD DE
# CARGA, no de optimización: subirla genera más pallets.
# Poner 0.0 desactiva la regla por completo (comportamiento anterior).
FILL_RATIO_MIN_SOPORTE = 0.60

UMBRAL_DATO_NO_CONFIABLE = 10000

ORDEN_CATEGORIAS = ["Licores", "Lácteos", "Aseo", "Importados", "Merch", "NABs"]
CATEGORIAS_REMATE = ["Comestibles", "Cigarros"]
CATEGORIAS_SIN_NADA_ENCIMA = ["NABs", "Comestibles", "Cigarros"]

CATEGORIAS_CONOCIDAS = ORDEN_CATEGORIAS + CATEGORIAS_REMATE


def _sin_acentos(texto: str) -> str:
    forma = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in forma if not unicodedata.combining(c))


_MAPA_NORMALIZACION = {_sin_acentos(cat).strip().lower(): cat for cat in CATEGORIAS_CONOCIDAS}


def normalizar_categoria(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    clave = _sin_acentos(texto).lower()
    return _MAPA_NORMALIZACION.get(clave)


ESTADO_OK = "OK"
ESTADO_ALERTA_PESO = "⚠ ALERTA DE PESO"
ESTADO_PESO_NO_VALIDABLE = "⚠ PESO NO VALIDABLE"
ESTADO_PALLET_PARCIAL = "⚠ PALLET PARCIAL — CIERRE FORZADO"
ESTADO_CATEGORIA_NO_CLASIFICADA = "⚠ CATEGORÍA NO CLASIFICADA"
ESTADO_DATO_INSUFICIENTE = "⚠ DATO INSUFICIENTE"
