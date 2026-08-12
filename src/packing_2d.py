import pandas as pd

import config
from models import Cama, Placement


def _clusterizar_por_altura(rows: list, tolerancia: float = config.TOLERANCIA_ALTURA_CAMA_MIXTA) -> list[list]:
    ordenado = sorted(rows, key=lambda r: r["Alto de caja"])
    clusters: list[list] = []
    actual: list = []
    base = None
    for r in ordenado:
        if not actual:
            actual = [r]
            base = r["Alto de caja"]
            continue
        if r["Alto de caja"] - base <= tolerancia:
            actual.append(r)
        else:
            clusters.append(actual)
            actual = [r]
            base = r["Alto de caja"]
    if actual:
        clusters.append(actual)
    return clusters


def _elegir_orientacion(largo: float, ancho: float) -> tuple[float, float, int] | None:
    """[PARCHE P1] Elige la orientación que maximiza la cantidad TOTAL de cajas
    en la cama (columnas x filas), no solo las columnas a lo largo de 120 cm.

    BUG ORIGINAL: el criterio era `columnas > mejor[2]`, o sea maximizaba solo
    cuántas cajas entran a lo largo de los 120 cm, ignorando cuántas filas caben
    en los 100 cm. Con una caja de 25x51 cm:
        - orientación A (w=25, d=51) -> 4 columnas x 1 fila =  4 cajas
        - orientación B (w=51, d=25) -> 2 columnas x 4 filas =  8 cajas
    El código elegía A porque 4 > 2, perdiendo la mitad de la cama. Y como la
    orientación se fija una sola vez por SKU, el error se propagaba a TODAS sus
    camas, puras y mixtas -> más camas -> más pallets -> más transporte.

    El criterio nuevo es idéntico al que ya usaba derivados._capacidad_geometrica
    para el fallback del Maestro; antes convivían dos nociones distintas de
    "capacidad geométrica" en el mismo repo, y esta era la incorrecta.

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
        sku, w, d = c["sku"], c["_w"], c["_d"]
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
            placements.append(Placement(sku=sku, cantidad=colocar, x=shelf["x_usado"], y=shelf["y"], w=w, d=d))
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
            placements.append(Placement(sku=sku, cantidad=colocar, x=0, y=y_acumulado, w=w, d=d))
            shelves.append({"y": y_acumulado, "alto": d, "x_usado": colocar * w})
            colocadas[sku] += colocar
            restante -= colocar
            y_acumulado += d

    return placements, colocadas


def _cama_desde_colocacion(placements: list[Placement], colocadas: dict[str, int], info: dict) -> Cama:
    colocadas_positivas = {sku: qty for sku, qty in colocadas.items() if qty > 0}
    alto_cama = max(info[sku]["Alto de caja"] for sku in colocadas_positivas)
    categorias = sorted({info[sku]["Categoria_Normalizada"] for sku in colocadas_positivas})
    nivel = info[next(iter(colocadas_positivas))]["Nivel_Categoria"]
    return Cama(
        categorias=categorias,
        altura_cama=alto_cama,
        placements=placements,
        cantidades=colocadas_positivas,
        nivel_categoria=nivel,
    )


def _capacidad_real_cama(sku: str, info: dict) -> int:
    """[PARCHE P2] Tope real de cajas de un SKU en una cama pura.

    Es el mínimo entre el techo de densidad del Maestro (`Cajas_Cama_Efectivo`)
    y lo que la geometría permite colocar de verdad. Se calcula UNA vez por SKU
    haciendo una corrida de prueba del packer.
    """
    densidad_max = info[sku]["Cajas_Cama_Efectivo"]
    if densidad_max <= 0:
        return 0
    prueba = [
        {
            "sku": sku,
            "largo": info[sku]["Largo de caja"],
            "ancho": info[sku]["Ancho de caja"],
            "disponible": densidad_max,
            "densidad_max": densidad_max,
        }
    ]
    _, colocadas = _empacar_cama(prueba)
    return colocadas.get(sku, 0)


def _procesar_cluster(cluster_rows: list) -> list[Cama]:
    """Prioriza camas puras (un solo SKU, hasta su tope real de densidad) por cada
    SKU del cluster; solo el remanente final de cada uno -- lo que no alcanza para
    llenar una cama completa por sí solo -- se mezcla entre sí en la(s) cama(s) de
    cierre, para aprovechar el perímetro de 120x100 en vez de dejarlas sueltas.

    [PARCHE P2] BUG ORIGINAL: el bucle era

        while pendientes[sku] >= densidad_max:      # densidad_max = dato del Maestro
            ...
            if colocado < densidad_max:
                break

    `densidad_max` venía del Maestro, pero `_empacar_cama` está acotado por la
    geometría. El propio doc de diseño dice que el Maestro NO coincide con la
    geometría en el 80% de los SKUs de la demanda real, con lo cual
    `colocado < densidad_max` era el caso NORMAL y el `break` disparaba casi
    siempre: con 100 cajas pendientes y capacidad geométrica de 20, se armaba UNA
    cama pura y las 80 restantes caían a la fase de mezcla, en vez de armar 5
    camas puras. Toda la estrategia documentada de "priorizar camas puras" estaba
    desactivada en la práctica.

    FIX: calcular el tope REAL de la cama una sola vez (Maestro acotado por
    geometría) y usar ese valor como condición del bucle. El `break` por
    `colocado < densidad_max` desaparece; queda solo el guard anti-loop.
    """
    info = {r["SKU"]: r for r in cluster_rows}
    pendientes = {r["SKU"]: r["Cajas_Remanente"] for r in cluster_rows}
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
                    "largo": info[sku]["Largo de caja"],
                    "ancho": info[sku]["Ancho de caja"],
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

    while any(v > 0 for v in pendientes.values()):
        candidatos = [
            {
                "sku": sku,
                "largo": info[sku]["Largo de caja"],
                "ancho": info[sku]["Ancho de caja"],
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
    camas_por_cd: dict[str, list[Cama]] = {}

    for cd, df_cd in df_remanente.groupby("CD"):
        camas_por_cd[cd] = []
        for _categoria, df_categoria in df_cd.groupby("Categoria_Normalizada"):
            rows = df_categoria.to_dict("records")
            for cluster in _clusterizar_por_altura(rows):
                camas_por_cd[cd].extend(_procesar_cluster(cluster))

    return camas_por_cd
