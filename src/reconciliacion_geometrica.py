"""[V3 / sección 5] Reconciliación geométrica Maestro <-> UMA.

Regla central (sección 0 de DOCUMENTACION_LOGICA_V3.md): el Maestro define la
capacidad operacional declarada ("Cajas por cama"); UMA valida la geometría.
Si UMA contradice una capacidad operacional conocida, el sistema NO reduce
"Cajas por cama" automáticamente (eso era V2: min(Maestro, geometría)).
En cambio: mantiene el Maestro, mantiene el alto, e infiere un Largo/Ancho
efectivo compatible con el Maestro usando una sola orientación -dejando
trazabilidad de que la geometría fue inferida, no medida.
"""
from functools import lru_cache

import pandas as pd

import config
from models import GeometriaSKU
from src.solver_cajas import max_cajas


def capacidad_orientacion_unica(pallet_largo: float, pallet_ancho: float, caja_largo: float, caja_ancho: float) -> int:
    """Cajas que entran en una sola orientación fija (sin probar el swap)."""
    if caja_largo is None or caja_ancho is None or caja_largo <= 0 or caja_ancho <= 0:
        return 0
    return int(pallet_largo // caja_largo) * int(pallet_ancho // caja_ancho)


@lru_cache(maxsize=4096)
def _capacidad_xy_max_cacheada(largo: float, ancho: float, pallet_largo: float, pallet_ancho: float) -> tuple[int, str]:
    """[V4 / P1] Probar TODAS las disposiciones con la caja de pie: grillas
    uniformes, patrones mixtos por cortes rectos recursivos, y molinete -no
    solo las dos grillas uniformes (subestimaba la capacidad en 108 de 183
    SKUs de la demanda real, ver PARCHES_V4.md). `lru_cache` (con `largo`/
    `ancho` ya redondeados por el caller): el solver mixto tarda ~70ms por
    dimensión con molinete, y `derivados.calcular_derivados` lo llama por
    FILA de demanda, no por SKU único -sin cachear, sería ~70ms por fila."""
    cap_a = capacidad_orientacion_unica(pallet_largo, pallet_ancho, largo, ancho)
    cap_b = capacidad_orientacion_unica(pallet_largo, pallet_ancho, ancho, largo)
    cap_mix, _metodo = max_cajas(pallet_largo, pallet_ancho, largo, ancho)
    if cap_mix > max(cap_a, cap_b):
        return cap_mix, "MIXTA"
    return (cap_a, "A") if cap_a >= cap_b else (cap_b, "B")


def capacidad_xy_max(largo: float, ancho: float) -> tuple[int, str]:
    """Mejor capacidad entre las rotaciones permitidas (XY, la caja siempre de
    pie), incluyendo patrones MIXTOS (una parte de la cama en una orientación,
    otra en la otra) y molinete -no solo grilla uniforme. Devuelve (capacidad,
    orientación) donde orientación es 'A' (largo a lo largo del lado de 120),
    'B' (ancho a lo largo del lado de 120) o 'MIXTA' (no hay una orientación
    única -ningún consumidor actual usa el segundo valor para otra cosa que no
    sea descartarlo, ver `grep -rn "capacidad_xy_max" src/`)."""
    if largo is None or ancho is None:
        return 0, "A"
    return _capacidad_xy_max_cacheada(round(largo, 3), round(ancho, 3), config.PALLET_LARGO, config.PALLET_ANCHO)


def capacidad_xy_max_con_sobresaliente(largo: float, ancho: float) -> tuple[int, str]:
    """[V4 / P2, P3] Igual que `capacidad_xy_max` pero contra el área EFECTIVA
    (con sobresaliente permitido, config.PALLET_LARGO_EFECTIVO/ANCHO_EFECTIVO)
    -solo para juzgar si un dato de "Cajas por cama" del Maestro es
    geométricamente creíble (`reconciliar_sku`). Nunca se usa para la
    geometría real de packing (Largo_Efectivo/Ancho_Efectivo siguen siendo
    las medidas estrictas de UMA, sin sobresaliente -sección "Dónde usarlo, y
    dónde NO" de PARCHES_V4.md)."""
    if largo is None or ancho is None:
        return 0, "A"
    return _capacidad_xy_max_cacheada(
        round(largo, 3), round(ancho, 3), config.PALLET_LARGO_EFECTIVO, config.PALLET_ANCHO_EFECTIVO
    )


def mejor_orientacion_3d(
    largo: float,
    ancho: float,
    alto: float,
    permitir_acostada: bool,
    cajas_objetivo: int | None = None,
    con_sobresaliente: bool = False,
) -> tuple[float, float, float, int, bool]:
    """[V4c / fotos de los 42 pallets reales] Si `permitir_acostada` (la
    categoría del SKU está en config.CATEGORIAS_ROTACION_LIBRE), evalúa las 3
    caras posibles como huella -parada (largo x ancho, alto vertical) y las 2
    acostadas (largo x alto con ancho vertical; ancho x alto con largo
    vertical). Si no se permite acostar (Licores, vidrio, etc. -riesgo de
    derrame/quiebre), se evalúa solo la parada, igual que V3.

    El criterio de selección NO es "más capacidad a cualquier costo": el
    Maestro ("Cajas por cama", `cajas_objetivo`) sigue siendo el techo
    operacional (sección 5.3.B) -si una orientación ya alcanza ese techo,
    acostarla más no suma cajas, solo suma altura de cama porque `alto_uma`
    deja de ser el lado más corto. Por eso:

    - con `cajas_objetivo`: entre las orientaciones que ALCANZAN el techo, se
      elige la de MENOR altura de cama (la cama queda más baja sin cambiar
      cuántas cajas entran); si NINGUNA lo alcanza, se elige la de MAYOR
      capacidad (para la rama de inconsistencia/degradado, que necesita saber
      qué tan cerca se puede llegar).
    - sin `cajas_objetivo` (SKU sin techo declarado): se elige la de MAYOR
      capacidad sin más, porque esa capacidad se usa tal cual (sección "UMA
      es la única fuente").

    `con_sobresaliente` usa el área EFECTIVA (config.PALLET_*_EFECTIVO) en vez
    de la estricta -solo para el chequeo de plausibilidad de P3, nunca para
    la geometría real de packing.

    Devuelve (largo_efectivo, ancho_efectivo, alto_efectivo, capacidad,
    acostada)."""
    calc = capacidad_xy_max_con_sobresaliente if con_sobresaliente else capacidad_xy_max

    candidatos = [(largo, ancho, alto)]
    if permitir_acostada:
        candidatos.append((largo, alto, ancho))
        candidatos.append((ancho, alto, largo))

    evaluados = [(l, a, h, calc(l, a)[0]) for l, a, h in candidatos]

    if cajas_objetivo is not None:
        alcanzan = [c for c in evaluados if c[3] >= cajas_objetivo]
        mejor = min(alcanzan, key=lambda c: c[2]) if alcanzan else max(evaluados, key=lambda c: c[3])
    else:
        mejor = max(evaluados, key=lambda c: c[3])

    l, a, h, cap = mejor
    return l, a, h, cap, h != alto


def inferir_footprint_desde_cajas_cama(
    cajas_cama: int,
    largo_uma: float,
    ancho_uma: float,
    pallet_largo: float | None = None,
    pallet_ancho: float | None = None,
) -> tuple[float | None, float | None, dict]:
    """[sección 5.3] Busca (largo, ancho) que reproduzcan EXACTO `cajas_cama`
    en una sola orientación de grilla uniforme, priorizando la solución de
    menor score entre todos los pares de factores (columnas x filas):

        score = peso_delta_dimensiones   * |cambio respecto a UMA|
              + peso_espacio_vacio       * (área no usada del pallet)
              + peso_cambio_aspect_ratio * (cuánto cambia largo/ancho)

    La salida es geometría EFECTIVA INFERIDA, no una medida real -por eso se
    prioriza moverse lo mínimo posible desde lo que UMA ya midió, en vez de
    devolver cualquier par de factores que matemáticamente cierre.

    Si `cajas_cama` no tiene ninguna factorización que quepa en el pallet
    (ej. un número que solo se puede lograr con una dimensión absurdamente
    grande), devuelve (None, None, info) con el motivo -eso es
    DATO_INSUFICIENTE, no una inferencia forzada.

    [V5-P2] `pallet_largo`/`pallet_ancho` opcionales -por defecto el pallet
    estricto (config.PALLET_LARGO/ANCHO); `reconciliar_sku` pasa el área
    EXTENDIDA (con sobresaliente) cuando la geometría medida estricta no
    alcanza a explicar al Maestro, antes de degradar del todo.
    """
    PL = pallet_largo if pallet_largo is not None else config.PALLET_LARGO
    PA = pallet_ancho if pallet_ancho is not None else config.PALLET_ANCHO
    if cajas_cama <= 0 or largo_uma is None or ancho_uma is None or largo_uma <= 0 or ancho_uma <= 0:
        return None, None, {"motivo": "sin datos UMA suficientes para inferir"}

    aspecto_uma = largo_uma / ancho_uma
    mejor = None
    mejor_score = float("inf")
    mejor_info: dict = {}

    for columnas in range(1, cajas_cama + 1):
        if cajas_cama % columnas != 0:
            continue
        filas = cajas_cama // columnas
        if columnas > PL or filas > PA:
            continue
        l_min, l_max = PL / (columnas + 1), PL / columnas
        a_min, a_max = PA / (filas + 1), PA / filas
        if l_min >= l_max or a_min >= a_max:
            continue

        for orig_l, orig_a, swap in ((largo_uma, ancho_uma, False), (ancho_uma, largo_uma, True)):
            l_cand = min(max(orig_l, l_min + 1e-6), l_max - 1e-6)
            a_cand = min(max(orig_a, a_min + 1e-6), a_max - 1e-6)
            delta = abs(l_cand - orig_l) + abs(a_cand - orig_a)
            vacio = 1 - (cajas_cama * l_cand * a_cand) / (PL * PA)
            aspecto_cand = (l_cand / a_cand) if not swap else (a_cand / l_cand)
            cambio_aspecto = abs(aspecto_cand - aspecto_uma) / aspecto_uma if aspecto_uma else 0.0
            score = (
                config.RECONCILIACION_PESO_DELTA_DIMENSIONES * delta
                + config.RECONCILIACION_PESO_ESPACIO_VACIO * max(vacio, 0.0)
                + config.RECONCILIACION_PESO_ASPECT_RATIO * cambio_aspecto
            )
            if score < mejor_score:
                mejor_score = score
                mejor = (a_cand, l_cand) if swap else (l_cand, a_cand)
                mejor_info = {"columnas": columnas, "filas": filas, "delta_cm": round(delta, 2), "score": round(score, 3)}

    if mejor is None:
        return None, None, {"motivo": f"{cajas_cama} no factoriza dentro del pallet sin dimensiones absurdas"}
    return mejor[0], mejor[1], mejor_info


def reconciliar_sku(row) -> GeometriaSKU:
    """Reconcilia un SKU. `row` debe traer (al menos): SKU, "Largo de caja",
    "Ancho de caja", "Alto de caja", "Cajas por cama", "Categoria_Normalizada"."""
    sku = row["SKU"]
    largo_uma = row.get("Largo de caja")
    ancho_uma = row.get("Ancho de caja")
    alto_uma = row.get("Alto de caja")
    cajas_raw = row.get("Cajas por cama")
    cajas_maestro = int(cajas_raw) if pd.notna(cajas_raw) and cajas_raw > 0 else None

    largo_uma = None if pd.isna(largo_uma) else float(largo_uma)
    ancho_uma = None if pd.isna(ancho_uma) else float(ancho_uma)
    alto_uma = None if pd.isna(alto_uma) else float(alto_uma)

    def _insuficiente(motivo: str) -> GeometriaSKU:
        return GeometriaSKU(
            sku=sku, largo_uma=largo_uma, ancho_uma=ancho_uma, alto_uma=alto_uma,
            largo_efectivo=None, ancho_efectivo=None, alto_efectivo=alto_uma,
            cajas_cama_maestro=cajas_maestro, capacidad_uma=None,
            fuente_geometria="DATO_INSUFICIENTE", delta_largo=None, delta_ancho=None,
            requiere_revision=True,
        )

    # `alto_uma` sigue siendo obligatorio (una de las 3 medidas tiene que
    # existir para poder evaluar cualquier orientación), pero [V4c] ya NO es
    # necesariamente el alto EFECTIVO -para Comestibles/Cigarros
    # (config.CATEGORIAS_ROTACION_LIBRE) se puede acostar la caja si eso
    # entra más por cama, ver `mejor_orientacion_3d`.
    if alto_uma is None:
        return _insuficiente("sin Alto de caja")

    if largo_uma is None or ancho_uma is None:
        return _insuficiente("sin Largo/Ancho de caja en UMA")

    categoria = row.get("Categoria_Normalizada")
    permitir_acostada = categoria in config.CATEGORIAS_ROTACION_LIBRE
    largo_base, ancho_base, alto_base, capacidad_uma, acostada = mejor_orientacion_3d(
        largo_uma, ancho_uma, alto_uma, permitir_acostada, cajas_objetivo=cajas_maestro
    )

    if cajas_maestro is None:
        # Sin techo operacional declarado por el Maestro: UMA es la única
        # fuente, se usa tal cual (equivalente al fallback geométrico de V2).
        return GeometriaSKU(
            sku=sku, largo_uma=largo_uma, ancho_uma=ancho_uma, alto_uma=alto_uma,
            largo_efectivo=largo_base, ancho_efectivo=ancho_base, alto_efectivo=alto_base,
            cajas_cama_maestro=None, capacidad_uma=capacidad_uma,
            fuente_geometria="UMA_VALIDADA", delta_largo=0.0, delta_ancho=0.0,
            requiere_revision=False, acostada=acostada,
        )

    if capacidad_uma >= cajas_maestro:
        # UMA (en su mejor orientación) permite exactamente o más que el
        # Maestro: la geometría medida ya explica (o supera) la capacidad
        # operacional. No se sube la densidad automáticamente solo porque UMA
        # de para más -el Maestro sigue siendo el techo (sección 5.3.B).
        fuente = "UMA_VALIDADA" if capacidad_uma == cajas_maestro else "UMA_SOBRECAPACIDAD"
        return GeometriaSKU(
            sku=sku, largo_uma=largo_uma, ancho_uma=ancho_uma, alto_uma=alto_uma,
            largo_efectivo=largo_base, ancho_efectivo=ancho_base, alto_efectivo=alto_base,
            cajas_cama_maestro=cajas_maestro, capacidad_uma=capacidad_uma,
            fuente_geometria=fuente, delta_largo=0.0, delta_ancho=0.0,
            requiere_revision=False, acostada=acostada,
        )

    # [V5-P2] capacidad_uma < cajas_maestro: antes de inventar CUALQUIER
    # footprint (aunque sea uno "cercano" a lo medido, vía
    # inferir_footprint_desde_cajas_cama), se chequea si la geometría REAL
    # MEDIDA (sin tocar largo/ancho) ya explica al Maestro con el sobresaliente
    # de negocio (2,5cm/lado). Regla explícita (DOCUMENTACION_LOGICA_V5.md
    # sección 5.3): "no sustituir una medición física por footprint artificial
    # si el dato operacional puede explicarse con sobresaliente validado".
    # Antes (V4/P3) se saltaba directo a `inferir_footprint_desde_cajas_cama`
    # apenas la geometría estricta no alcanzaba -aunque el sobresaliente, SIN
    # cambiar ninguna medida, ya hubiera bastado.
    capacidad_sobresaliente_real, _ = capacidad_xy_max_con_sobresaliente(largo_base, ancho_base)
    if capacidad_sobresaliente_real >= cajas_maestro:
        return GeometriaSKU(
            sku=sku, largo_uma=largo_uma, ancho_uma=ancho_uma, alto_uma=alto_uma,
            largo_efectivo=largo_base, ancho_efectivo=ancho_base, alto_efectivo=alto_base,
            cajas_cama_maestro=cajas_maestro, capacidad_uma=capacidad_sobresaliente_real,
            fuente_geometria="UMA_VALIDADA_CON_SOBRESALIENTE", delta_largo=0.0, delta_ancho=0.0,
            requiere_revision=False, acostada=acostada,
        )

    # [V5-P2] Ni siquiera la geometría medida + sobresaliente alcanza. Acá
    # es donde V4 llamaba `inferir_footprint_desde_cajas_cama` para inventar
    # ALGÚN footprint que matemáticamente cierre -exactamente lo que la
    # regla de este patch prohíbe cuando no hay una razón física real
    # (`inferir_footprint_desde_cajas_cama` no tiene piso de "esto es
    # absurdo", así que si se la deja correr acá siempre encuentra algo,
    # sea o no representativo de la caja real -ver SKU 22183: declara 84
    # cajas/cama, la geometría real da 15 incluso con sobresaliente, pero la
    # búsqueda igual "resuelve" 84 con un footprint ficticio). Se degrada
    # directo al techo geométrico real (requiere_revision=False: SÍ hay
    # geometría utilizable, el problema era solo el número de "Cajas por
    # cama", ya corregido acá).
    return GeometriaSKU(
        sku=sku, largo_uma=largo_uma, ancho_uma=ancho_uma, alto_uma=alto_uma,
        largo_efectivo=largo_base, ancho_efectivo=ancho_base, alto_efectivo=alto_base,
        cajas_cama_maestro=capacidad_sobresaliente_real, capacidad_uma=capacidad_uma,
        fuente_geometria="MAESTRO_IMPOSIBLE_DEGRADADO", delta_largo=0.0, delta_ancho=0.0,
        requiere_revision=False, acostada=acostada,
    )


def reconciliar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconcilia geometría UNA VEZ POR SKU (es propiedad del SKU, no de la
    fila CD+SKU) y agrega las columnas de geometría efectiva a `df`. Devuelve
    (df con columnas nuevas, df de auditoría por SKU -sección 20, "Hoja de
    auditoría geométrica")."""
    df = df.copy()
    por_sku = df.drop_duplicates(subset="SKU")
    geometrias: dict = {row["SKU"]: reconciliar_sku(row) for _, row in por_sku.iterrows()}

    df["Largo_Efectivo"] = df["SKU"].map(lambda s: geometrias[s].largo_efectivo)
    df["Ancho_Efectivo"] = df["SKU"].map(lambda s: geometrias[s].ancho_efectivo)
    df["Alto_Efectivo"] = df["SKU"].map(lambda s: geometrias[s].alto_efectivo)
    df["Fuente_Geometria"] = df["SKU"].map(lambda s: geometrias[s].fuente_geometria)
    df["Geometria_Inferida"] = df["Fuente_Geometria"].isin(("INFERIDA_MAESTRO", "MAESTRO_IMPOSIBLE_DEGRADADO"))
    df["Requiere_Revision_Geometria"] = df["SKU"].map(lambda s: geometrias[s].requiere_revision)
    # [V4c] True si conviene acostar la caja (una cara lateral como huella)
    # en vez de dejarla parada -confirmado con las fotos de los 42 pallets
    # reales para Comestibles/Cigarros (config.CATEGORIAS_ROTACION_LIBRE).
    df["Geometria_Acostada"] = df["SKU"].map(lambda s: geometrias[s].acostada)
    # [V4 / P3] "Cajas por cama" ya RECONCILIADO: igual al del Maestro salvo
    # que fuera geométricamente imposible incluso con sobresaliente, en cuyo
    # caso viene degradado al techo real (ver reconciliar_sku). derivados.py
    # debe usar ESTA columna para Cajas_Cama_Efectivo, no la cruda del Maestro
    # -si no, el guard de P3 queda solo en la auditoría y nunca protege el plan.
    df["Cajas_Cama_Maestro_Reconciliado"] = df["SKU"].map(lambda s: geometrias[s].cajas_cama_maestro)

    auditoria = pd.DataFrame(
        [
            {
                "SKU": g.sku,
                "Largo_UMA": g.largo_uma,
                "Ancho_UMA": g.ancho_uma,
                "Alto_UMA": g.alto_uma,
                "Largo_Efectivo": g.largo_efectivo,
                "Ancho_Efectivo": g.ancho_efectivo,
                "Alto_Efectivo": g.alto_efectivo,
                "Capacidad_Geometrica_UMA": g.capacidad_uma,
                "Cajas_Cama_Maestro": g.cajas_cama_maestro,
                "Fuente_Geometria": g.fuente_geometria,
                "Delta_Largo": g.delta_largo,
                "Delta_Ancho": g.delta_ancho,
                "Requiere_Revision_Geometria": g.requiere_revision,
                "Geometria_Acostada": g.acostada,
            }
            for g in geometrias.values()
        ]
    )
    return df, auditoria
