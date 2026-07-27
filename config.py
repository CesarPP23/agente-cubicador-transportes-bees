import unicodedata

PALLET_LARGO = 120
PALLET_ANCHO = 100

ALTURA_PALLET_VACIO = 14.92
ALTURA_TOTAL_MIN = 190
ALTURA_TOTAL_MAX = 195
ALTURA_PRODUCTO_MIN = 175.08
ALTURA_PRODUCTO_MAX = 180.08

PESO_ALERTA_KG = 1350
PESO_CAJA_MIN = 0.05
PESO_CAJA_MAX = 100

TOLERANCIA_ALTURA_CAMA_MIXTA = 3

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
