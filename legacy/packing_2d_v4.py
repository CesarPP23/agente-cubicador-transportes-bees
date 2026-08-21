import pandas as pd

import config
from models import Cama, Placement


def _clusterizar_por_altura(rows: list, tolerancia: float = config.TOLERANCIA_ALTURA_PORTANTE) -> list[list]:
    ordenado = sorted(rows, key=lambda r: r["Alto_Efectivo"])
    clusters: list[list] = []
    actual: list = []
    base = None
    for r in ordenado:
        if not actual:
            actual = [r]
            base = r["Alto_Efectivo"]
            continue
        if r["Alto_Efectivo"] - base <= tolerancia:
            actual.append(r)
        else:
            clusters.append(actual)
            actual = [r]
            base = r["Alto_Efectivo"]
    if actual:
        clusters.append(actual)
    return clusters


def _elegir_orientacion(largo: float, ancho: float) -> tuple[float, float, int] | None:
    """[PARCHE P1 / V3 sección 7, 13.1] Elige la orientación que maximiza la
    cantidad TOTAL de cajas en la cama (columnas x filas), no solo las
    columnas a lo largo de 120 cm.

    [V3] Solo se comparan las DOS rotaciones XY permitidas -la caja siempre
    de pie, el alto nunca pasa a ser largo o ancho (sección 7). La rotación
    "acostada" que existía en V2 salió del flujo productivo: se investigó y
    se confirmó como hipótesis real (explicaba el 78% de los casos donde la
    geometría de pie daba menos que el Maestro), pero conectarla al packer
    rompía el balance entre camas puras y mezcla. V3 resuelve el mismo
    problema de raíz con reconciliación geométrica Maestro<->UMA (ver
    src/reconciliacion_geometrica.py) en vez de rotar la caja.

    Desempate: menor profundidad `d`, porque deja shelves más bajos y por lo
    tanto más reutilizables por otros SKUs en la fase de mezcla.
    """
    mejor = None
    mejor_capacidad = -1
    for w, d in ((largo, ancho), (ancho, largo)):
        if w > config.PALLET_LARGO or d > config.PALLET_ANCHO:
            continue
        columnas = int(config.PALLET_LARGO // w)
        filas = int(config.PALLET_ANCHO // d)
        if columnas == 0 or filas == 0:
            continue
        capacidad = columnas * filas
        if capacidad > mejor_capacidad or (capacidad == mejor_capacidad and d < mejor[1]):
            mejor = (w, d, columnas)
            mejor_capacidad = capacidad
    return mejor


def _empacar_cama(candidatos: list[dict]) -> tuple[list[Placement], dict[str, int]]:
    preparados = []
    for c in candidatos:
        orientacion = _elegir_orientacion(c["largo"], c["ancho"])
        if orientacion is None:
            continue
        w, d, _ = orientacion
        preparados.append({**c, "_w": w, "_d": d})

    preparados.sort(key=lambda c: -c["_d"])

    shelves: list[dict] = []
    y_acumulado = 0.0
    placements: list[Placement] = []
    colocadas = {c["sku"]: 0 for c in candidatos}

    for c in preparados:
        sku, w, d, h = c["sku"], c["_w"], c["_d"], c["alto"]
        restante = min(c["disponible"], c["densidad_max"]) - colocadas[sku]
        if restante <= 0:
            continue

        for shelf in shelves:
            if restante <= 0:
                break
            if shelf["alto"] < d - 1e-6:
                continue
            columnas_disp = int((config.PALLET_LARGO - shelf["x_usado"]) // w)
            if columnas_disp <= 0:
                continue
            colocar = min(columnas_disp, restante)
            placements.append(Placement(sku=sku, cantidad=colocar, x=shelf["x_usado"], y=shelf["y"], w=w, d=d, h=h))
            shelf["x_usado"] += colocar * w
            colocadas[sku] += colocar
            restante -= colocar

        while restante > 0:
            if y_acumulado + d > config.PALLET_ANCHO + 1e-6:
                break
            columnas_posibles = int(config.PALLET_LARGO // w)
            if columnas_posibles <= 0:
                break
            colocar = min(columnas_posibles, restante)
            placements.append(Placement(sku=sku, cantidad=colocar, x=0, y=y_acumulado, w=w, d=d, h=h))
            shelves.append({"y": y_acumulado, "alto": d, "x_usado": colocar * w})
            colocadas[sku] += colocar
            restante -= colocar
            y_acumulado += d

    return placements, colocadas


def _cama_desde_colocacion(placements: list[Placement], colocadas: dict[str, int], info: dict) -> Cama:
    colocadas_positivas = {sku: qty for sku, qty in colocadas.items() if qty > 0}
    # El alto físico del SKU es siempre constante (sección 7) -todos los
    # placements de un mismo SKU tienen el mismo h, así que max(p.h) coincide
    # con max("Alto_Efectivo"); se deja vía placements para que
    # altura_min_cajas/altura_max_cajas (desnivel, sección 14.3) salgan del
    # mismo lugar sin recalcular por SKU.
    alturas = [p.h for p in placements]
    alto_cama = max(alturas)
    categorias = sorted({info[sku]["Categoria_Normalizada"] for sku in colocadas_positivas})
    # Nivel de la cama = el MÁS RESTRICTIVO (más alto) entre sus SKUs, no "el de
    # un SKU cualquiera" como estaba antes (`next(iter(...))`). Con camas de una
    # sola categoría daba lo mismo; con camas mixtas (punto 6) era un bug latente.
    nivel = max(info[sku]["Nivel_Categoria"] for sku in colocadas_positivas)
    # [PARCHE P5] superficie realmente cubierta, para la regla de soporte del Paso 4
    area_ocupada = sum(p.cantidad * p.w * p.d for p in placements)
    # [V3 / sección 4.1] Trazabilidad de geometría inferida: si algún SKU de
    # la cama usa Largo/Ancho reconciliados (no medidos), la cama queda
    # marcada -aunque el resto de sus SKUs sean UMA_VALIDADA.
    geometria_inferida = any(
        info[sku].get("Fuente_Geometria") in ("INFERIDA_MAESTRO", "MAESTRO_IMPOSIBLE_DEGRADADO")
        for sku in colocadas_positivas
    )
    return Cama(
        categorias=categorias,
        altura_cama=alto_cama,
        placements=placements,
        cantidades=colocadas_positivas,
        nivel_categoria=nivel,
        area_ocupada=area_ocupada,
        altura_min_cajas=min(alturas),
        altura_max_cajas=max(alturas),
        geometria_inferida=geometria_inferida,
    )


def _capacidad_real_cama(sku: str, info: dict) -> int:
    """[PARCHE P2 / V3 sección 6] Tope real de cajas de un SKU en una cama
    pura: la capacidad operacional (`Cajas_Cama_Efectivo`, ya reconciliada
    contra la geometría efectiva -ver derivados.py), verificada colocándola
    de verdad contra la geometría efectiva (Largo_Efectivo/Ancho_Efectivo,
    no la UMA cruda)."""
    densidad_max = info[sku]["Cajas_Cama_Efectivo"]
    if densidad_max <= 0:
        return 0
    prueba = [
        {
            "sku": sku,
            "largo": info[sku]["Largo_Efectivo"],
            "ancho": info[sku]["Ancho_Efectivo"],
            "alto": info[sku]["Alto_Efectivo"],
            "disponible": densidad_max,
            "densidad_max": densidad_max,
        }
    ]
    _, colocadas = _empacar_cama(prueba)
    return colocadas.get(sku, 0)


def _extraer_camas_puras(grupo_rows: list) -> tuple[list[Cama], list[dict]]:
    """[ESTRATEGIA_CAMAS = PURE_FIRST, ver config.py] Arma camas puras (un
    solo SKU, hasta su tope real de densidad) por cada SKU del grupo.
    Devuelve las camas puras y las filas de remanente -lo que no alcanzó
    para una cama pura más- para que se agrupen con las de otros SKUs en la
    fase de mezcla (`_mezclar_remanentes`).

    No depende de la altura de los demás SKUs del grupo -cada SKU arma su
    cama pura contra su propia geometría- así que se corre sobre TODO el
    grupo (mismo nivel de estabilidad / mismo aislamiento NABs-remate), lo
    que libera más remanente para pool-earse antes de clusterizar por altura
    en la fase de mezcla.
    """
    info = {r["SKU"]: r for r in grupo_rows}
    pendientes = {r["SKU"]: r["Cajas_Remanente"] for r in grupo_rows}
    camas: list[Cama] = []

    for sku in pendientes:
        capacidad_cama = _capacidad_real_cama(sku, info)
        if capacidad_cama <= 0:
            continue  # no cabe ni una caja; se resuelve (o se descarta) en la mezcla final

        densidad_max = info[sku]["Cajas_Cama_Efectivo"]
        while pendientes[sku] >= capacidad_cama:
            candidato = [
                {
                    "sku": sku,
                    "largo": info[sku]["Largo_Efectivo"],
                    "ancho": info[sku]["Ancho_Efectivo"],
                    "alto": info[sku]["Alto_Efectivo"],
                    "disponible": pendientes[sku],
                    "densidad_max": densidad_max,
                }
            ]
            placements, colocadas = _empacar_cama(candidato)
            colocado = colocadas.get(sku, 0)
            if colocado <= 0:
                break  # guard anti-loop; no debería ocurrir si capacidad_cama > 0
            pendientes[sku] -= colocado
            camas.append(_cama_desde_colocacion(placements, colocadas, info))

    remanente_rows = [{**info[sku], "Cajas_Remanente": qty} for sku, qty in pendientes.items() if qty > 0]
    return camas, remanente_rows


def _mezclar_remanentes(rows: list) -> list[Cama]:
    """Combina remanentes de varios SKUs -ya agrupados por altura, ver
    `generar_camas`- en camas de cierre, para aprovechar el perímetro de
    120x100 en vez de dejarlas sueltas en camas de un solo SKU sub-llenas."""
    if not rows:
        return []

    info = {r["SKU"]: r for r in rows}
    pendientes = {r["SKU"]: r["Cajas_Remanente"] for r in rows}
    camas: list[Cama] = []

    while any(v > 0 for v in pendientes.values()):
        candidatos = [
            {
                "sku": sku,
                "largo": info[sku]["Largo_Efectivo"],
                "ancho": info[sku]["Ancho_Efectivo"],
                "alto": info[sku]["Alto_Efectivo"],
                "disponible": pendientes[sku],
                "densidad_max": info[sku]["Cajas_Cama_Efectivo"],
            }
            for sku in pendientes
            if pendientes[sku] > 0
        ]
        placements, colocadas = _empacar_cama(candidatos)

        if not any(qty > 0 for qty in colocadas.values()):
            break

        for sku, qty in colocadas.items():
            pendientes[sku] -= qty

        camas.append(_cama_desde_colocacion(placements, colocadas, info))

    return camas


def generar_camas(df_remanente: pd.DataFrame) -> dict[str, list[Cama]]:
    """[V4b / fotos de los 42 pallets reales] La operación real mezcla
    categorías libremente en el mismo pallet -e incluso en la misma
    cama/columna- según lo que convenga geométricamente, no por nivel de
    estabilidad (Licores/Lácteos/.../remate). Confirmado con Omar: la única
    restricción dura de armado es la altura del pallet (~190-215cm); ya no
    hay separación de NABs/remate en su propia sub-cama
    (`_separar_nabs_y_remate`, V3) ni tope de separación entre niveles
    (`_separar_por_nivel`, `config.MAX_SEPARACION_NIVELES`) -ambas se
    retiraron de este flujo. Lo único que sigue agrupando es la altura de
    caja (`_clusterizar_por_altura`): cajas de alturas muy distintas no
    comparten cama porque physically no se puede -no por categoría.

    [V3] `df_remanente` YA NO incluye Cigarros/vapes (BAT) -se separan antes,
    ver bat.separar_bat y pipeline.py- y ya trae Largo_Efectivo/
    Ancho_Efectivo/Alto_Efectivo (geometría reconciliada, no UMA cruda) desde
    reconciliacion_geometrica.reconciliar.

    Dentro de cada CD: primero se extraen las camas puras (por SKU), y recién
    el remanente se agrupa por altura para la fase de mezcla."""
    camas_por_cd: dict[str, list[Cama]] = {}

    for cd, df_cd in df_remanente.groupby("CD"):
        camas_por_cd[cd] = []
        rows = df_cd.to_dict("records")
        camas_puras, remanente = _extraer_camas_puras(rows)
        camas_por_cd[cd].extend(camas_puras)
        for cluster in _clusterizar_por_altura(remanente):
            camas_por_cd[cd].extend(_mezclar_remanentes(cluster))

    return camas_por_cd
