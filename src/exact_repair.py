"""[PATCH V6.04, secciones 10-13] Exact Local Repair -último fallback,
solo si el Repair Solver v2 (`src/repair_solver.py`, neighborhoods
iterativos + ejection chains) no llega al 100%. Resuelve EXACTAMENTE
-con OR-Tools CP-SAT- un vecindario LOCAL y acotado: las cajas que
faltan + lo que ya se había retirado como blocker + vecinos geométricos
cercanos. El resto del pallet queda CONGELADO -esto no es un resolver de
CD completo desde cero, es una reparación quirúrgica de una zona chica.

No usa grilla de 1cm: las posiciones candidatas en X/Y salen de bordes
del envelope, bordes de cajas congeladas, y esas mismas coordenadas
desplazadas por las dimensiones de las cajas del propio vecindario
(sección 12) -así el conjunto de posiciones queda finito y chico incluso
para vecindarios de hasta `EXACT_REPAIR_MAX_BOXES` cajas."""
from __future__ import annotations

import time

import config
from models import PalletV5
from src.rescue_solver import TOL, _blockers_para_posicion, _quedaria_flotando
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import _tiene_soporte_admisible

EXACT_REPAIR_MAX_BOXES = 24
EXACT_REPAIR_TIME_MAX_SECONDS = 30.0
# [performance -bug real encontrado probando esto contra BK52] El no-overlap
# se arma por PARES de opciones en Python puro (sección 13) -con un SKU de
# muchas unidades, cada unidad repite la MISMA lista de candidatas, así que
# el total de opciones (y los pares) explota con `unidades x candidatas`.
# Cap por SKU (no por caja individual -todas las unidades del mismo SKU
# comparten la lista) usando las de mejor ajuste (menor huella sobrante).
MAX_CANDIDATOS_POR_SKU = 40
# [performance -bug real: el cap por SKU arriba no alcanza cuando HAY
# varios SKUs de muchas unidades a la vez (ej. 15 unidades x 40
# candidatas = 600 opciones de UN SOLO SKU) -tope duro sobre el total de
# opciones aplanadas (SKU x unidad x candidata) antes de armar los pares
# de no-overlap, recortando proporcionalmente lo que haga falta.
#
# [medido contra BK52 -el cuello de botella real resultó ser la
# combinatoria de `_anclas_1d`/`_generar_candidatos`, ya corregida abajo,
# no `model.Add()`] Se mantiene igual este tope como cinturón de
# seguridad adicional sobre el tamaño del modelo CP-SAT en sí.]
MAX_OPCIONES_TOTALES = 150
# [sección 12] Cuántas veces desplazar un ancla por una dimensión del
# vecindario para generar coordenadas acumuladas (2-3 cajas seguidas) sin
# explotar el conteo de posiciones candidatas.
_MAX_DESPLAZAMIENTOS = 3


def _anclas_1d(base: set[float], dimensiones: set[float]) -> set[float]:
    """[sección 12] Coordenadas base + desplazamientos acumulados por las
    dimensiones del propio vecindario (para poder tilear 2-3 cajas
    seguidas en un hueco, no solo pegadas a lo congelado).

    [bug real de performance encontrado contra BK52] La versión anterior
    cruzaba CADA ancla base con CADA dimensión, encadenado, DOS VECES (una
    redundante) -con `|base|` en el orden de decenas y varias dimensiones
    distintas, el resultado crecía a miles de anclas por eje, y el CROSS
    PRODUCT X×Y×Z×orientaciones de `_generar_candidatos` explotaba a
    cientos de millones de combinaciones (medido: 40s+ SOLO para generar
    candidatos de un vecindario de 2 SKUs). Acá: como mucho
    `_MAX_DESPLAZAMIENTOS` pasos, encadenando SOLO la dimensión más chica
    (la que permite tilear más cajas en el mismo espacio) -alcanza para el
    caso típico (varias cajas IGUALES seguidas) sin la explosión
    combinatoria de cruzar todas las dimensiones entre sí."""
    if not dimensiones:
        return set(base)
    d_min = min(dimensiones)
    anclas = set(base)
    for a in base:
        acumulado = a
        for _ in range(_MAX_DESPLAZAMIENTOS):
            acumulado += d_min
            anclas.add(acumulado)
    return anclas


def construir_vecindario(
    pallet: PalletV5, skus_a_colocar: dict[str, int], skus_blockers: set[str],
    max_boxes: int = EXACT_REPAIR_MAX_BOXES,
) -> tuple[PalletV5, dict[str, int]]:
    """[sección 10] Arma (pallet_congelado, items_libres): saca del
    pallet las torres de `skus_blockers` CON CASCADA anti-flotación
    -mismo criterio que `packing_bloques._romper_skus_con_cascada`: si
    quitar un blocker deja a otra torre (de un SKU NO elegido) sin
    soporte real, esa también se saca y su SKU se agrega al vecindario
    (bug real encontrado probando esto: sin la cascada, `_generar_
    candidatos` trataba esa torre como "congelada" válida y el CP-SAT
    podía devolver un pallet con cajas flotando)- y devuelve además
    cuántas unidades de cada SKU hace falta ubicar (faltantes + blockers
    + lo que la cascada haya sumado). Si el total supera `max_boxes`, NO
    amplía el vecindario -devuelve tal cual, el caller decide si prueba
    otro conflict set o se rinde (sección 11)."""
    elegidos = set(skus_blockers)
    restantes = list(pallet.torres)
    while True:
        nuevas_restantes = []
        cambio = False
        for t in restantes:
            if t.sku in elegidos:
                cambio = True
                continue
            if t.z > TOL:
                soportes = [
                    o for o in restantes
                    if o is not t and o.sku not in elegidos and abs((o.z + o.altura) - t.z) <= TOL
                ]
                if not _tiene_soporte_admisible(t, soportes):
                    elegidos.add(t.sku)
                    cambio = True
                    continue
            nuevas_restantes.append(t)
        restantes = nuevas_restantes
        if not cambio:
            break

    pallet_congelado = PalletV5(
        id=pallet.id, cd=pallet.cd, torres=list(restantes),
        altura_final=config.ALTURA_PALLET_VACIO + max((t.z + t.altura for t in restantes), default=0.0),
    )
    items_libres: dict[str, int] = dict(skus_a_colocar)
    for t in pallet.torres:
        if t.sku in elegidos:
            items_libres[t.sku] = items_libres.get(t.sku, 0) + t.cantidad
    return pallet_congelado, items_libres


def _generar_candidatos(
    pallet_congelado: PalletV5, por_sku: dict[str, list[TorreCandidate]], skus: list[str], presupuesto: float,
    region: tuple[float, float, float, float] | None = None,
) -> dict[str, list[tuple[float, float, float, TorreCandidate]]]:
    """[sección 12] Posiciones candidatas por SKU -sin solapar nada
    congelado, con soporte real (piso o torre congelada), usando SOLO
    coordenadas estructurales (bordes + dimensiones acumuladas del propio
    vecindario, sección 12).

    `region` (x0, y0, x1, y1) -bug real de performance encontrado
    probando esto contra BK52 (>100 torres congeladas): generar anclas
    con los bordes de TODAS las torres del pallet, cruzadas en X e Y,
    explota a millones de combinaciones incluso para un vecindario de
    pocas cajas. `region` acota las anclas a las torres congeladas
    CERCANAS al área que de verdad importa (bounding box de los blockers
    retirados, expandido) -las torres lejanas nunca son soporte ni
    obstáculo real para una reparación local de todos modos."""
    margen = config.SOBRESALIENTE_MAX_CM

    dims_x: set[float] = set()
    dims_y: set[float] = set()
    for sku in skus:
        for cand in por_sku.get(sku, []):
            dims_x.add(cand.largo)
            dims_y.add(cand.ancho)

    if region is not None:
        rx0, ry0, rx1, ry1 = region
        torres_cercanas = [
            t for t in pallet_congelado.torres
            if t.x < rx1 + TOL and t.x + t.largo > rx0 - TOL and t.y < ry1 + TOL and t.y + t.ancho > ry0 - TOL
        ]
    else:
        torres_cercanas = list(pallet_congelado.torres)

    base_x = {-margen, 0.0, config.PALLET_LARGO + margen}
    base_y = {-margen, 0.0, config.PALLET_ANCHO + margen}
    for t in torres_cercanas:
        base_x.add(round(t.x, 4))
        base_x.add(round(t.x + t.largo, 4))
        base_y.add(round(t.y, 4))
        base_y.add(round(t.y + t.ancho, 4))

    anclas_x = _anclas_1d(base_x, dims_x)
    anclas_y = _anclas_1d(base_y, dims_y)
    anclas_z = {0.0}
    for t in torres_cercanas:
        anclas_z.add(round(t.z, 4))
        anclas_z.add(round(t.z + t.altura, 4))

    candidatos_por_sku: dict[str, list[tuple[float, float, float, TorreCandidate]]] = {sku: [] for sku in skus}
    vistos: set[tuple] = set()
    for sku in skus:
        for cand in por_sku.get(sku, []):
            for x in anclas_x:
                if x < -margen - TOL or x + cand.largo > config.PALLET_LARGO + margen + TOL:
                    continue
                for y in anclas_y:
                    if y < -margen - TOL or y + cand.ancho > config.PALLET_ANCHO + margen + TOL:
                        continue
                    for z in anclas_z:
                        if z + cand.alto_caja > presupuesto + TOL:
                            continue
                        clave = (sku, round(x, 4), round(y, 4), round(z, 4), cand.orientacion)
                        if clave in vistos:
                            continue
                        vistos.add(clave)
                        if _blockers_para_posicion(pallet_congelado, x, y, z, cand):
                            continue
                        if _quedaria_flotando(pallet_congelado, [], x, y, z, cand):
                            continue
                        candidatos_por_sku[sku].append((x, y, z, cand))

    for sku, opciones in candidatos_por_sku.items():
        if len(opciones) > MAX_CANDIDATOS_POR_SKU:
            opciones.sort(key=lambda o: o[2])  # menor Z primero -pisos más bajos, más reutilizables
            candidatos_por_sku[sku] = opciones[:MAX_CANDIDATOS_POR_SKU]
    return candidatos_por_sku


def _se_solapan_candidatos(a: tuple[float, float, float, TorreCandidate], b: tuple[float, float, float, TorreCandidate]) -> bool:
    xa, ya, za, ca = a
    xb, yb, zb, cb = b
    return (
        xa < xb + cb.largo - TOL and xb < xa + ca.largo - TOL
        and ya < yb + cb.ancho - TOL and yb < ya + ca.ancho - TOL
        and za < zb + cb.alto_caja - TOL and zb < za + ca.alto_caja - TOL
    )


def resolver_cp_sat(
    pallet_congelado: PalletV5, por_sku: dict[str, list[TorreCandidate]], items_libres: dict[str, int],
    tope_pallet_por_sku: dict[str, int], presupuesto: float,
    time_limit_s: float = EXACT_REPAIR_TIME_MAX_SECONDS,
    region: tuple[float, float, float, float] | None = None,
) -> dict:
    """[sección 13] Variables `placement_choice` (una por caja individual
    x posición candidata x orientación), restricciones de no-overlap,
    altura, overhang (ya filtrados al generar candidatos), Cajas por PH,
    y objetivo maximizar cajas colocadas con desempate por cobertura de
    SKUs completos. Devuelve {"colocado": [(sku, x, y, z, cand), ...],
    "status": str, "tiempo_s": float}."""
    from ortools.sat.python import cp_model

    t0 = time.time()
    skus = sorted(items_libres)
    candidatos_por_sku = _generar_candidatos(pallet_congelado, por_sku, skus, presupuesto, region)

    # [performance] Tope duro sobre el total de opciones APLANADAS (SKU x
    # unidad x candidata) -ver MAX_OPCIONES_TOTALES. Si una SKU de muchas
    # unidades por sí sola ya excede el tope, se recorta más su lista de
    # candidatas (proporcional a cuántas unidades tiene) antes de armar
    # los pares de no-overlap.
    total_bruto = sum(items_libres[sku] * len(candidatos_por_sku.get(sku, [])) for sku in skus)
    if total_bruto > MAX_OPCIONES_TOTALES:
        factor = MAX_OPCIONES_TOTALES / total_bruto
        for sku in skus:
            tope_sku = max(1, int(len(candidatos_por_sku.get(sku, [])) * factor))
            candidatos_por_sku[sku] = candidatos_por_sku.get(sku, [])[:tope_sku]

    # Aplanar a "cajas individuales": cada unidad demandada de un SKU
    # compite por las MISMAS posiciones candidatas de ese SKU.
    cajas: list[dict] = []
    for sku in skus:
        for _ in range(items_libres[sku]):
            cajas.append({"sku": sku, "opciones": candidatos_por_sku.get(sku, [])})

    model = cp_model.CpModel()
    variables: list[list] = []  # variables[i] = lista de BoolVar, una por opción de la caja i
    todas_opciones: list[tuple[int, int, tuple]] = []  # (idx_caja, idx_opcion, (x,y,z,cand))
    for i, caja in enumerate(cajas):
        vars_caja = []
        for j, opcion in enumerate(caja["opciones"]):
            v = model.NewBoolVar(f"x_{i}_{j}")
            vars_caja.append(v)
            todas_opciones.append((i, j, opcion))
        variables.append(vars_caja)
        if vars_caja:
            model.Add(sum(vars_caja) <= 1)  # cada caja: como mucho 1 posición elegida

    # No-overlap: pares de opciones (de cajas DISTINTAS) que se solaparían
    # en 3D no pueden estar ambas activas. Dos opciones de la MISMA caja ya
    # están cubiertas por el <=1 de arriba.
    for a_idx in range(len(todas_opciones)):
        i_a, j_a, opcion_a = todas_opciones[a_idx]
        for b_idx in range(a_idx + 1, len(todas_opciones)):
            i_b, j_b, opcion_b = todas_opciones[b_idx]
            if i_a == i_b:
                continue
            if _se_solapan_candidatos(opcion_a, opcion_b):
                model.Add(variables[i_a][j_a] + variables[i_b][j_b] <= 1)

    # Cajas por PH: ya HAY algunas cajas de este SKU colocadas afuera del
    # vecindario (en `pallet_congelado`, si sobrevivió alguna) -el tope
    # acá es lo que le queda de margen a este vecindario.
    ya_en_pallet: dict[str, int] = {}
    for t in pallet_congelado.torres:
        ya_en_pallet[t.sku] = ya_en_pallet.get(t.sku, 0) + t.cantidad
    for sku in skus:
        tope = tope_pallet_por_sku.get(sku)
        if tope is None:
            continue
        margen_ph = tope - ya_en_pallet.get(sku, 0)
        vars_sku = [variables[i][j] for i, caja in enumerate(cajas) if caja["sku"] == sku for j in range(len(variables[i]))]
        if vars_sku:
            model.Add(sum(vars_sku) <= max(0, margen_ph))

    total_colocado = sum(sum(vars_caja) for vars_caja in variables if vars_caja)
    # Desempate por cobertura: 1 por cada SKU que queda COMPLETO dentro del vecindario.
    bonus_cobertura = []
    for sku in skus:
        idxs = [i for i, caja in enumerate(cajas) if caja["sku"] == sku]
        if not idxs:
            continue
        completo = model.NewBoolVar(f"completo_{sku}")
        suma_sku = sum(v for i in idxs for v in variables[i]) if any(variables[i] for i in idxs) else 0
        model.Add(suma_sku >= len(idxs)).OnlyEnforceIf(completo)
        model.Add(suma_sku < len(idxs)).OnlyEnforceIf(completo.Not())
        bonus_cobertura.append(completo)

    model.Maximize(total_colocado * 1000 + sum(bonus_cobertura))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)

    colocado = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for i, caja in enumerate(cajas):
            for j, opcion in enumerate(caja["opciones"]):
                if solver.Value(variables[i][j]):
                    colocado.append((caja["sku"], *opcion))

    return {
        "colocado": colocado,
        "status": solver.StatusName(status),
        "tiempo_s": round(time.time() - t0, 3),
        "cajas_en_vecindario": len(cajas),
        "posiciones_candidatas": len(todas_opciones),
    }


def exact_local_repair(
    pallet: PalletV5, por_sku: dict[str, list[TorreCandidate]], sin_colocar: dict[str, int],
    skus_blockers: set[str], tope_pallet_por_sku: dict[str, int], presupuesto: float,
    max_boxes: int = EXACT_REPAIR_MAX_BOXES, time_limit_s: float = EXACT_REPAIR_TIME_MAX_SECONDS,
) -> tuple[PalletV5, dict[str, int], dict]:
    """[sección 10, 11] Punto de entrada. Arma el vecindario (sección 10),
    si supera `max_boxes` NO lo amplía (devuelve el pallet sin tocar -el
    caller decide si prueba otro conflict set más chico). Si el CP-SAT
    encuentra algo, reconstruye el pallet con las cajas congeladas +
    lo que el solver exacto decidió colocar."""
    # [performance] Región de interés: bounding box de los blockers
    # ORIGINALES (antes de retirarlos), expandida -acota las anclas de
    # `_generar_candidatos` a lo relevante, ver esa función.
    blockers_torres = [t for t in pallet.torres if t.sku in skus_blockers]
    # [performance -bug real: escalar el margen con el tamaño de la caja
    # (ej. 2x58.8cm=117.6) volvía la región casi del tamaño del pallet
    # ENTERO para SKUs grandes, anulando el filtro y volviendo a la
    # explosión original -tope FIJO, independiente del tamaño de caja; el
    # encadenado de dimensiones de `_anclas_1d` ya se encarga de alcanzar
    # posiciones más lejos DENTRO de la región cuando hace falta tilear
    # varias cajas seguidas.]
    margen_extra = 40.0
    if blockers_torres:
        region = (
            min(t.x for t in blockers_torres) - margen_extra,
            min(t.y for t in blockers_torres) - margen_extra,
            max(t.x + t.largo for t in blockers_torres) + margen_extra,
            max(t.y + t.ancho for t in blockers_torres) + margen_extra,
        )
    else:
        region = None

    pallet_congelado, items_libres = construir_vecindario(pallet, sin_colocar, skus_blockers, max_boxes)
    total_items = sum(items_libres.values())

    stats = {
        "activado": True, "cajas_en_vecindario": total_items, "excedio_max_boxes": total_items > max_boxes,
        "status": None, "tiempo_s": 0.0, "colocadas_exact": 0,
    }
    if total_items == 0 or total_items > max_boxes:
        return pallet, sin_colocar, stats

    resultado = resolver_cp_sat(
        pallet_congelado, por_sku, items_libres, tope_pallet_por_sku, presupuesto, time_limit_s, region,
    )
    stats.update({
        "status": resultado["status"], "tiempo_s": resultado["tiempo_s"],
        "colocadas_exact": len(resultado["colocado"]), "posiciones_candidatas": resultado["posiciones_candidatas"],
    })

    torres_nuevas = list(pallet_congelado.torres)
    colocadas_por_sku: dict[str, int] = {}
    for sku, x, y, z, cand in resultado["colocado"]:
        torres_nuevas.append(crear_torre(cand, x=x, y=y, z=z, cantidad=1))
        colocadas_por_sku[sku] = colocadas_por_sku.get(sku, 0) + 1

    # [bug real: `items_libres` puede traer SKUs que `skus_blockers` no
    # tenía -la cascada anti-flotación de `construir_vecindario` los
    # agregó- así que el cálculo de faltantes tiene que basarse en
    # `items_libres` (el vecindario REAL), no en el conjunto pedido
    # originalmente.]
    sin_colocar_final = {sku: cant for sku, cant in sin_colocar.items() if sku not in items_libres}
    for sku, cantidad_libre in items_libres.items():
        sin_colocar_final[sku] = cantidad_libre - colocadas_por_sku.get(sku, 0)
    sin_colocar_final = {sku: cant for sku, cant in sin_colocar_final.items() if cant > 0}

    altura_final = config.ALTURA_PALLET_VACIO + max((t.z + t.altura for t in torres_nuevas), default=0.0)
    pallet_final = PalletV5(
        id=pallet.id, cd=pallet.cd, torres=torres_nuevas, altura_final=altura_final, metadata=dict(pallet.metadata),
    )
    return pallet_final, sin_colocar_final, stats


# [sección 11] Cuántos conflict sets candidatos probar por SKU faltante
# antes de darlo por imposible en esta ronda -exact repair es caro (CP-SAT
# real), no tiene sentido una shortlist tan ancha como la del rescue
# heurístico.
EXACT_REPAIR_CONFLICT_SHORTLIST = 4


def exact_repair_orquestado(
    pallet: PalletV5, por_sku: dict[str, list[TorreCandidate]], sin_colocar: dict[str, int],
    tope_pallet_por_sku: dict[str, int], presupuesto: float,
    max_boxes: int = EXACT_REPAIR_MAX_BOXES, time_limit_s: float = EXACT_REPAIR_TIME_MAX_SECONDS,
    deadline: float | None = None,
) -> tuple[PalletV5, dict[str, int], dict]:
    """[sección 10, 11] Orquesta `exact_local_repair` sobre VARIOS conflict
    sets candidatos (mismo mecanismo de `rescue_solver._rankear_
    conflictos`, no uno solo elegido a mano) -prueba, para el SKU faltante
    más restringido, sus conflictos más baratos en orden; si el vecindario
    resultante (tras la cascada anti-flotación) supera `max_boxes`, prueba
    el SIGUIENTE conflict set en vez de ampliarlo (sección 11: "no ampliar
    automáticamente"). Un intento solo se conserva si mejora el total
    colocado -nunca peor que lo que recibió (bug real encontrado probando
    esto: un conflicto puede cascadear a un vecindario grande que el
    CP-SAT no logra recuperar del todo, perdiendo más de lo que gana -acá
    se revierte y se prueba otro conflict set en vez de aceptarlo).

    [PATCH V6.12-R2-A1] El `deadline` de ESTE orquestador (el bucle
    Python de arriba hacia abajo, que decide cuántos conflict sets
    probar) pasa a CPU-time (`time.process_time()`), mismo patrón que
    rescue_solver/repair_solver/global_rescue -`deadline` (calculado en
    `packing_bloques._empacar_n_pallets`) debe venir ya en este dominio.
    Esto NO toca `solver.parameters.max_time_in_seconds` (línea de
    `exact_local_repair` más abajo): ese es el límite NATIVO de CP-SAT,
    wall-clock por diseño de la librería (confirmado: la versión
    instalada de OR-Tools SÍ expone `max_deterministic_time` como
    alternativa, ver auditoría R2-A1 -no se activa todavía, cambio fuera
    de alcance de este parche)."""
    from src.packing_columnar import _reconstruir_en_construccion
    from src.rescue_solver import _rankear_conflictos

    reloj = time.process_time
    t0 = time.time()  # solo para stats["tiempo_s"] (diagnóstico humano, no budget)
    stats = {
        "activado": True, "intentos": 0, "exitos": 0, "excedio_max_boxes": 0,
        "cajas_recuperadas": 0, "skus_resueltos": [],
    }

    pendientes = {sku: cant for sku, cant in sin_colocar.items() if cant > 0}
    pallet_actual = pallet
    # [bug real: "si el SKU más barato no mejora, cortar TODO el loop"
    # dejaba sin probar a los demás SKUs faltantes -uno solo con
    # conflictos caros (que cascadean a un vecindario grande) bloqueaba
    # el intento de CUALQUIER otro, aunque ese otro sí tuviera una
    # reparación barata disponible (medido en BK52: 16167 sin salida
    # cortaba el intento de 21576, que sí mejoraba parcialmente).]
    skus_agotados: set[str] = set()

    while True:
        candidatos_pendientes = {s: c for s, c in pendientes.items() if c > 0 and s not in skus_agotados}
        if not candidatos_pendientes:
            break
        if deadline is not None and reloj() > deadline:
            break
        sku_objetivo = min(candidatos_pendientes, key=lambda s: candidatos_pendientes[s])
        candidatas_sku = por_sku.get(sku_objetivo, [])
        if not candidatas_sku:
            skus_agotados.add(sku_objetivo)
            continue
        construccion = [_reconstruir_en_construccion(pallet_actual)]
        conflictos = _rankear_conflictos(
            construccion, sku_objetivo, candidatas_sku, presupuesto, shortlist=EXACT_REPAIR_CONFLICT_SHORTLIST,
        )

        resuelto = False
        for _, _pidx, _x, _y, _z, _cand, blocker_skus in conflictos:
            if deadline is not None and reloj() > deadline:
                break
            stats["intentos"] += 1
            total_antes = sum(t.cantidad for t in pallet_actual.torres)
            pallet_intento, sin_colocar_intento, r_stats = exact_local_repair(
                pallet_actual, por_sku, pendientes, blocker_skus, tope_pallet_por_sku, presupuesto,
                max_boxes=max_boxes, time_limit_s=time_limit_s,
            )
            if r_stats.get("excedio_max_boxes"):
                stats["excedio_max_boxes"] += 1
                continue
            total_despues = sum(t.cantidad for t in pallet_intento.torres)
            if total_despues > total_antes:
                stats["exitos"] += 1
                stats["cajas_recuperadas"] += total_despues - total_antes
                if pendientes.get(sku_objetivo, 0) > sin_colocar_intento.get(sku_objetivo, 0):
                    stats["skus_resueltos"].append(sku_objetivo)
                pallet_actual = pallet_intento
                pendientes = sin_colocar_intento
                skus_agotados = set()  # el estado cambió -vale la pena reintentar lo que antes no daba
                resuelto = True
                break

        if not resuelto:
            # Este SKU no mejoró con ningún conflict set en el estado
            # actual -no insistir más CON ÉL, pero seguir con los demás.
            skus_agotados.add(sku_objetivo)

    stats["tiempo_s"] = round(time.time() - t0, 3)
    sin_colocar_final = {sku: cant for sku, cant in pendientes.items() if cant > 0}
    return pallet_actual, sin_colocar_final, stats
