import unicodedata

# [V5-P1, V-AUTO] Flag de arquitectura: "V4" (camas, el motor probado en
# producción), "V5" (columnar/torres, ver Parches/v5/PATCH_LOG.md) o "AUTO"
# (corre AMBOS y se queda con el mejor resultado CD por CD -nunca peor que
# el mejor de los dos, ver src/pipeline_auto.py; el costo es correr el
# pipeline dos veces). pipeline.ejecutar_pipeline despacha según esto.
# Ninguno de los tres reemplaza formalmente a V4 en producción hasta
# decisión explícita -mientras tanto, cambiar este flag es el único punto
# de rollback, nunca hace falta tocar código.
PACKER_VERSION = "SKU_BLOQUE"  # [nueva lógica, instrucción del usuario] bloques enteros por SKU primero

# [V5-P7] Multi-start: cantidad de semillas iniciales por CD y tope.
MULTISTART_SEEDS = 20
MULTISTART_MAX = 50

# [V5-P6] V5 no preconstruye pallets homogéneos ni extrae camas puras antes
# de mirar el resto de la demanda -un resultado homogéneo puede seguir
# apareciendo, pero como consecuencia del optimizador, no como decisión previa.
PH_PREBUILD = False
PURE_FIRST = False

# [V5 sección 5.3] El sobresaliente de negocio (SOBRESALIENTE_MAX_CM, abajo)
# es válido para AUDITORÍA/VALIDACIÓN de datos por defecto. Ponerlo en True
# lo activaría también para planificación real (parte de la base 2D del
# packer usaría el área extendida 125x105) -decisión de negocio todavía sin
# confirmar, por eso queda en False.
SOBRESALIENTE_PLANIFICACION = False

PALLET_LARGO = 120
PALLET_ANCHO = 100

# [V4 / Parches/v4_cubicaje_mixto/PARCHES_V4.md, P2] Sobresaliente aceptado:
# cuánto puede volar la caja del borde del pallet. Confirmado con Omar. 2,5 cm
# por lado es el límite del estándar logístico -más allá la caja pierde sobre
# 20% de resistencia a la compresión porque su esquina queda sin apoyo.
# Poner 0.0 vuelve al criterio estricto de V3.
#
# Medido sobre 458 SKUs, cuánto del dato declarado por la operación resulta
# geométricamente alcanzable según el sobresaliente que se acepte:
#     0,0 cm/lado -> 73%
#     1,0 cm/lado -> 78%
#     2,0 cm/lado -> 81%
#     2,5 cm/lado -> 82%   <- elegido
#     5,0 cm/lado -> 86%   (fuera del estándar seguro)
#
# Uso: SÍ en la validación/reconciliación de "Cajas por cama" (¿es creíble el
# dato del Maestro?, ver reconciliacion_geometrica.capacidad_xy_max_con_sobresaliente).
# NO en el packing real (packing_2d) -si el motor planifica asumiendo
# sobresaliente en todos lados, dos camas que sobresalen en direcciones
# distintas dan un pallet con perfil irregular difícil de estibar y envolver.
# Es una decisión de negocio de PLANIFICACIÓN todavía no confirmada con Omar.
SOBRESALIENTE_MAX_CM = 2.5
PALLET_LARGO_EFECTIVO = PALLET_LARGO + 2 * SOBRESALIENTE_MAX_CM  # 125
PALLET_ANCHO_EFECTIVO = PALLET_ANCHO + 2 * SOBRESALIENTE_MAX_CM  # 105

# [V4c / fotos de los 42 pallets reales] Confirmado con Omar viendo las fotos:
# Comestibles y Cigarros se acuestan para ahorrar espacio -no se dejan siempre
# "de pie". Medido contra la demanda real (Cubicaje18.07.2026.xlsx): 44/47
# SKUs de Comestibles (94%) y 5/24 de Cigarros caben MÁS cajas por cama
# acostados (una cara lateral como huella, no la base) que parados. Para el
# resto de las categorías (Licores, vidrio, Lácteos, etc.) se mantiene
# "siempre parada" -no son seguras para acostar (riesgo de derrame/quiebre).
# Ver reconciliacion_geometrica.mejor_orientacion_3d.
CATEGORIAS_ROTACION_LIBRE = ["Comestibles", "Cigarros"]

ALTURA_PALLET_VACIO = 14.92

# --- Ventana de altura total del pallet (producto + pallet vacío) -- V3 -------
# [V3 / sección 11] Reemplaza la ventana V2 (190/195/200/205/210, con reserva
# de 55cm para remate) por la semántica del benchmark real ("Cubicado Real",
# 42 pallets físicos, promedio 198.3cm, mínimo 170cm, máximo 215cm).
#
# Zonas (sección 6.2 de DOCUMENTACION_LOGICA_V3.md), de la más a la menos
# deseable. Son etiquetas de REPORTE (estado_altura), no topes que bloqueen
# distinto según la zona -el único tope operacional es ALTURA_MAX_OBSERVADA,
# ver más abajo:
#   195-200  ÓPTIMO
#   190-195  NOMINAL
#   185-190  TOLERADO
#   170-185  PARCIAL OPERATIVO
#   <170     RESIDUAL / REVISAR
#   200-210  ALTO PERO OPERATIVO
#   210-215  EXCEPCIÓN / VALIDAR
#   >215     NO PERMITIDO hasta validación adicional
ALTURA_TARGET = 198.3
ALTURA_OPTIMA_MIN = 195.0
ALTURA_OPTIMA_MAX = 200.0
ALTURA_NOMINAL_MIN = 190.0
ALTURA_TOLERADO_MIN = 185.0
ALTURA_PARCIAL_OPERATIVA_MIN = 170.0
ALTURA_ALERTA_ALTA = 210.0
ALTURA_MAX_OBSERVADA = 215.0

# [V3] Ninguno de los umbrales de arriba es un límite normativo validado -son
# el benchmark observado. Mientras ALTURA_HARD_VALIDADA sea None, el sistema
# NO debe tratar 210 ni 215 como "techo físico absoluto": son alerta y
# excepción/máximo observado respectivamente. El motor SÍ necesita un tope
# operacional para decidir cuándo dejar de apilar -se usa ALTURA_MAX_OBSERVADA
# (215) para eso, que es distinto de afirmar que 215 es un límite validado.
# Si en algún momento hay una cifra formal (norma de seguridad, límite de
# rack, etc.), fijarla acá para que se vuelva un bloqueo real.
ALTURA_HARD_VALIDADA: float | None = None

# Altura útil de producto = altura total - pallet vacío.
ALTURA_PRODUCTO_MIN = ALTURA_NOMINAL_MIN - ALTURA_PALLET_VACIO
ALTURA_PRODUCTO_MAX = ALTURA_MAX_OBSERVADA - ALTURA_PALLET_VACIO

# --- Peso -----------------------------------------------------------------
# [V3 / sección 12] Los valores heredados (1.400 alerta / 1.430 bloqueo) NO
# están validados contra capacidad real de pallet/montacargas/rack/SST/
# transporte -funcionaban mejor en el modelo, pero eso no los valida. Se
# mantienen como PROVISIONALES (bandera explícita) en vez de sacarlos, porque
# sin algún tope el Paso 4 no tiene ninguna restricción de peso.
PESO_ALERTA_KG = 1400
PESO_HARD_KG = 1430
PESO_PARAMETROS_VALIDADOS = False

# [V4b / fotos de los 42 pallets reales] Confirmado con Omar: la única
# restricción dura de armado es la altura (ver ALTURA_NOMINAL_MIN/
# ALTURA_MAX_OBSERVADA, ~190-215cm); "buscar la mejor forma geométrica...
# con el fin de mover la menor cantidad de pallets" no deja margen para que
# el peso bloquee una combinación que geométricamente conviene. PESO_HARD_KG
# se mantiene para el reporte/alerta de validacion_peso.py (ESTADO_ALERTA_PESO),
# pero deja de usarse como gate en apilado_3d._cabe / bat.py. Poner True
# vuelve a bloquear el armado por peso (comportamiento V3).
PESO_ES_RESTRICCION_DURA = False

PESO_CAJA_MIN = 0.05
PESO_CAJA_MAX = 100

# La columna "Peso bruto por unidad" de la hoja UMA trae, en la práctica, el peso
# BRUTO DE LA CAJA del SKU — no el de la unidad suelta. Verificado contra la
# densidad resultante: tratándola como peso de caja las densidades por categoría
# caen en 130-855 kg/m³ (físicamente correcto); multiplicándola por
# "Unidades por caja" saltan a 7.700-65.000 kg/m³ (imposible).
# Poner True restaura el comportamiento anterior (peso unitario x unidades).
PESO_UMA_ES_POR_UNIDAD = False

# --- Camas: portante vs terminal -- V3 -------------------------------------
# [V3 / sección 14] Una tolerancia única (±8cm) para decidir qué remanentes
# se combinan en una misma cama de mezcla no distingue entre una cama que va
# a SOSTENER otra encima (portante -necesita quedar razonablemente nivelada)
# y una que va a ser la última del pallet (terminal -nada se apoya encima,
# puede tolerar más diferencia de altura sin ningún riesgo).
# TOLERANCIA_ALTURA_PORTANTE hereda el valor ya calibrado contra
# Cubicaje18.07.2026.xlsx (ver historial: 3->91% parciales, 8->76%, retorno
# decreciente después). TOLERANCIA_ALTURA_TERMINAL queda "por calibrar": se
# puso más ancha que portante porque no hay riesgo de estabilidad al mezclar
# remanentes bajo la cama de cierre, pero el valor concreto no se barrió
# todavía -ajustar con la próxima medición contra pallets reales.
TOLERANCIA_ALTURA_PORTANTE = 8
TOLERANCIA_ALTURA_TERMINAL = 20

# [PARCHE P5 / V3 sección 10] Fracción mínima de la base 120x100 que una cama
# debe cubrir para poder sostener otra encima. DESACTIVADA (0.0): no debe
# interpretarse como "seguridad validada" -es el valor con el que se corrió
# la última validación contra pallets físicos reales (dio la densidad más
# parecida a la real), no uno que se haya confirmado formalmente como seguro.
FILL_RATIO_MIN_SOPORTE = 0.0

# Alias retrocompatible: código/tests viejos todavía puede referenciar el
# nombre V2. Mismo valor que TOLERANCIA_ALTURA_PORTANTE.
TOLERANCIA_ALTURA_MEZCLA = TOLERANCIA_ALTURA_PORTANTE

# --- Rotación -- V3 ---------------------------------------------------------
# [V3 / sección 7] "Cajas acostadas" (probar Largo x Alto / Ancho x Alto como
# base) sale del flujo productivo. Se investigó y CONFIRMÓ como hipótesis
# (explica el 78% de los casos donde la geometría de pie da menos que el
# Maestro), pero conectarla al packer real no mejoraba el resultado -rompía
# el balance entre camas puras y mezcla (ver commits anteriores). V3 la
# reemplaza por la reconciliación geométrica Maestro<->UMA
# (src/reconciliacion_geometrica.py), que resuelve el mismo problema de raíz
# sin rotar la caja: si el Maestro declara más capacidad de la que la
# geometría de pie explica, se infiere un Largo/Ancho efectivo compatible en
# vez de forzar una orientación físicamente arriesgada para el SKU.
# Solo quedan permitidas dos orientaciones, ambas con la caja parada:
#   (largo, ancho, alto)
#   (ancho, largo, alto)
# `alto` es SIEMPRE constante -nunca pasa a ser largo o ancho.

# --- Reconciliación geométrica Maestro<->UMA -- V3 -------------------------
# [V3 / sección 5] "Cajas por cama" del Maestro es la capacidad OPERACIONAL
# declarada; ya no se reduce automáticamente solo porque la geometría UMA
# calcule menos (eso era P2/V2: min(Maestro, geometría), "la geometría gana
# por ser más conservadora" -- supuesto que la validación contra pallets
# reales contradijo: el Maestro resultó más confiable que nuestra grilla
# simple en la mayoría de los casos). Ver src/reconciliacion_geometrica.py.
RECONCILIACION_PESO_DELTA_DIMENSIONES = 1.0
RECONCILIACION_PESO_ESPACIO_VACIO = 0.5
RECONCILIACION_PESO_ASPECT_RATIO = 0.25

# --- BAT (Cigarros/vapes) -- V3 ---------------------------------------------
# [V3 / sección 9, 11] Cigarros/vapes NUNCA se despachan por caja completa (el
# 96% de sus líneas de demanda son fraccionarias) y el personal los consolida
# en una caja física FIJA, separada del cubicaje normal, que se coloca como
# remate encima de un pallet "host" ya armado -no se empaca con la geometría
# de cada SKU. La identificación de qué es BAT es una categoría logística
# EXPLÍCITA (no un valor numérico genérico compartido con otros productos).
CATEGORIAS_BAT = ["Cigarros"]

CAJA_BAT_LARGO = 52.5
CAJA_BAT_ANCHO = 34.0
CAJA_BAT_ALTO = 49.0
CAJA_BAT_CAPACIDAD_UNIDADES = 1000

# Alias retrocompatibles (nombres V2 usados en config/tests anteriores).
CAJA_CONSOLIDACION_CIGARROS_LARGO = CAJA_BAT_LARGO
CAJA_CONSOLIDACION_CIGARROS_ANCHO = CAJA_BAT_ANCHO
CAJA_CONSOLIDACION_CIGARROS_ALTO = CAJA_BAT_ALTO
CAJA_CONSOLIDACION_CIGARROS_MAX_UNIDADES = CAJA_BAT_CAPACIDAD_UNIDADES

# [V3 / sección 9.3, 17.1] La reserva global de altura (RESERVA_ALTURA_REMATE
# = 55cm en TODOS los pallets base de un CD con remate pendiente) se ELIMINA
# para BAT: no reproducía la operación real y sobre-reservaba margen en
# pallets que nunca terminaban recibiendo una caja BAT. Se reemplaza por
# selección de host DINÁMICA después de armar todos los pallets normales
# (bat.asignar_hosts_bat), que busca, para cada caja BAT, el pallet cuya
# altura + 55cm quede más cerca de ALTURA_TARGET (198.3cm) -sin reservar nada
# de antemano.
RESERVA_ALTURA_REMATE = 0

# --- Heurística de armado de camas -- V3 (sección 13.3) --------------------
# Estrategia con la que packing_2d arma camas puras vs. mixtas. Hoy solo está
# implementada PURE_FIRST (comportamiento heredado de V2: camas puras primero,
# remanente a mezcla). GLOBAL_MIX / HYBRID_LOOKAHEAD quedan documentadas como
# alternativas a comparar contra el benchmark real, pero no implementadas
# todavía -comparar heurísticas completas es un proyecto aparte.
ESTRATEGIA_CAMAS = "PURE_FIRST"

UMBRAL_DATO_NO_CONFIABLE = 10000

ORDEN_CATEGORIAS = ["Licores", "Lácteos", "Aseo", "Importados", "Merch", "NABs"]
CATEGORIAS_REMATE = ["Comestibles", "Cigarros"]
CATEGORIAS_SIN_NADA_ENCIMA = ["NABs", "Comestibles", "Cigarros"]

CATEGORIAS_CONOCIDAS = ORDEN_CATEGORIAS + CATEGORIAS_REMATE

# [V3 / sección 8, 16] "Mantener temporalmente" -la migración a matrices
# explícitas de compatibilidad (COMPATIBILIDAD_APILADO / COMPATIBILIDAD_CAMA,
# una para vertical y otra para mezcla en cama, que no tienen por qué ser
# equivalentes) queda para una iteración posterior, no entra en este pase.
# Máxima separación de niveles permitida dentro de una misma cama mixta,
# SOLO entre los niveles base 1-5 (Licores..Merch) -NABs y remate quedan
# siempre aislados de la mezcla, ver packing_2d._separar_nabs_y_remate.
MAX_SEPARACION_NIVELES = 2

# Nivel de estabilidad: 1 (base, más pesado) .. 6 (NABs) .. 7 (remate).
NIVEL_REMATE = len(ORDEN_CATEGORIAS) + 1  # 7


def nivel_de_categoria(categoria: str | None) -> int | None:
    """Nivel de estabilidad de una categoría ya normalizada, o None si no clasifica."""
    if categoria in CATEGORIAS_REMATE:
        return NIVEL_REMATE
    if categoria in ORDEN_CATEGORIAS:
        return ORDEN_CATEGORIAS.index(categoria) + 1
    return None


def estado_altura(altura: float) -> str:
    """[V3 / sección 6.2] Zona de altura -etiqueta de reporte, no un bloqueo:
    todo lo que pasa por acá ya fue aceptado por el armado (altura <=
    ALTURA_MAX_OBSERVADA). Distinta de Pallet.estado (que además incorpora
    peso, soporte, etc.) -ver apilado_3d.estado_pallet."""
    if altura > ALTURA_MAX_OBSERVADA:
        return "NO PERMITIDO"
    if altura > ALTURA_ALERTA_ALTA:
        return "EXCEPCIÓN"
    if altura > ALTURA_OPTIMA_MAX:
        return "ALTO PERO OPERATIVO"
    if altura >= ALTURA_OPTIMA_MIN:
        return "ÓPTIMO"
    if altura >= ALTURA_NOMINAL_MIN:
        return "NOMINAL"
    if altura >= ALTURA_TOLERADO_MIN:
        return "TOLERADO"
    if altura >= ALTURA_PARCIAL_OPERATIVA_MIN:
        return "PARCIAL OPERATIVO"
    return "RESIDUAL"


# Alias retrocompatible (nombre V2). El motor ya no distingue un "techo
# normal" de un "tope duro" -ver ALTURA_HARD_VALIDADA arriba- así que ambos
# alias apuntan al mismo tope operacional único.
ALTURA_TOTAL_MIN = ALTURA_NOMINAL_MIN
ALTURA_TOTAL_MIN_TOLERADO = ALTURA_TOLERADO_MIN
ALTURA_TOTAL_MAX = ALTURA_MAX_OBSERVADA
ALTURA_TOPE_DURO = ALTURA_MAX_OBSERVADA
PESO_TOPE_ELASTICO_KG = PESO_HARD_KG


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


def estado_pallet_por_altura(altura: float) -> str:
    """[V3 / sección 6.2, 16] Traduce la zona de altura (estado_altura) al
    estado que se muestra en el plan de picking. Varias zonas "buenas"
    (ÓPTIMO/NOMINAL/ALTO PERO OPERATIVO) se reportan como OK -la zona fina
    no se pierde, sigue disponible recalculando desde Altura_Final_Pallet_cm
    con estado_altura() si hace falta más detalle."""
    zona = estado_altura(altura)
    if zona in ("ÓPTIMO", "NOMINAL", "ALTO PERO OPERATIVO"):
        return ESTADO_OK
    if zona == "TOLERADO":
        return ESTADO_TOLERADO
    if zona == "EXCEPCIÓN":
        return ESTADO_ALTURA_EXCEPCIONAL
    if zona in ("PARCIAL OPERATIVO", "RESIDUAL"):
        return ESTADO_PALLET_PARCIAL
    return ESTADO_REQUIERE_REVISION  # NO PERMITIDO -- _cabe no debería dejar llegar hasta acá


ESTADO_OK = "OK"
ESTADO_OPTIMO = "ÓPTIMO"
ESTADO_TOLERADO = "TOLERADO"
ESTADO_ALERTA_PESO = "⚠ ALERTA DE PESO"
ESTADO_PESO_NO_VALIDABLE = "⚠ PESO NO VALIDABLE"
ESTADO_PALLET_PARCIAL = "⚠ PALLET PARCIAL"
ESTADO_ALTURA_EXCEPCIONAL = "⚠ ALTURA EXCEPCIONAL"
ESTADO_CATEGORIA_NO_CLASIFICADA = "⚠ CATEGORÍA NO CLASIFICADA"
ESTADO_GEOMETRIA_INFERIDA = "⚠ GEOMETRÍA INFERIDA"
ESTADO_GEOMETRIA_INCONSISTENTE = "⚠ GEOMETRÍA INCONSISTENTE"
ESTADO_SOPORTE_BAJO = "⚠ SOPORTE BAJO"
ESTADO_DATO_INSUFICIENTE = "⚠ DATO INSUFICIENTE"
ESTADO_REQUIERE_REVISION = "⚠ REQUIERE REVISIÓN"
