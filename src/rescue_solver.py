"""[PATCH V6.02] Rescue Solver -Most-Constrained-First + branching
adaptativo + Conflict-Directed LNS.

Se activa SOLO desde `packing_bloques._empacar_n_pallets` (import LOCAL
ahí, para evitar import circular -este módulo importa funciones privadas
de `packing_bloques`, que ya está completamente cargado quien lo llama),
y SOLO cuando `pallets_objetivo` está fijado Y quedó demanda sin colocar
después del camino normal (greedy + DFS + LNS). El camino normal NUNCA se
reemplaza -este módulo solo intenta MEJORAR el resultado ya obtenido, y el
llamador se queda con el mejor de los dos (sección 3, 10, 11 del patch).

No reimplementa el motor: reusa `_cuboide_admite_candidato`,
`_capacidad_restante_en_capa`, `_cantidad_sin_solape`,
`_resolver_pallets_backtracking`, `_romper_skus_con_cascada`,
`_snapshot_estado_pallets`/`_restaurar_estado_pallets` de
`packing_bloques.py` -el rescue decide QUÉ romper y QUÉ priorizar, no
reescribe CÓMO se valida una colocación."""
from __future__ import annotations

import math
import time
from collections.abc import Callable

import config
from models import PalletV5
from src.packing_columnar import _reconstruir_en_construccion
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import _tiene_soporte_admisible

TOL = 1e-6

RESCUE_TIME_MAX_SECONDS = 90.0
# [sección 7] Branching adaptativo -SOLO dentro del rescue, y SOLO para el
# SKU crítico que se está intentando resolver en cada iteración. Nunca
# toca `COMBINACION_PALLETS_OPCIONES_POR_SKU` (el camino normal).
RESCUE_OPCIONES_SKU_CRITICO = 3
RESCUE_OPCIONES_SKU_NORMAL = 1
# [sección 9.3] Cuántos conflictos (conjuntos de blockers) distintos probar
# como máximo por SKU crítico antes de rendirse en esta ronda.
RESCUE_CONFLICT_SHORTLIST = 8
# [sección 8] No hace falta contar candidatos exactos para Most-Constrained
# -alcanza con distinguir 0/1/2/3/4+ alternativas.
MAX_CANDIDATOS_PARA_SCARCITY = 4
# Presupuesto de nodos de los backtracking chicos internos del rescue (uno
# dedicado al SKU crítico, otro para reconstruir lo que se rompió) -no
# reutiliza el presupuesto grande del DFS/LNS normal a propósito: acá se
# corre muchas veces por iteración, tiene que ser barato por corrida.
RESCUE_MAX_NODOS_CRITICO = 300
RESCUE_MAX_NODOS_RECONSTRUCCION = 3_000


def _identificar_skus_criticos(pendientes: dict[str, int]) -> set[str]:
    """[sección 4] Un SKU es crítico si tiene demanda no colocada -nada
    más específico que eso: funciona para cualquier SKU futuro, no solo
    "Pícaras"."""
    return {sku for sku, cant in pendientes.items() if cant > 0}


def _generar_batch_sizes(max_lote: int) -> list[int]:
    """[sección 6] {1, max_lote, ceil(max_lote/2)} sin duplicados -nunca
    el rango completo 1..max_lote (explotaría el árbol)."""
    if max_lote <= 0:
        return []
    return sorted({1, max_lote, math.ceil(max_lote / 2)})


def _footprint_maximo(candidatas: list[TorreCandidate]) -> float:
    return max((c.largo * c.ancho for c in candidatas), default=0.0)


def _contar_candidatos_factibles(
    construcciones, colocados_por_pallet: list[dict[str, int]], sku: str,
    por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    max_count: int = MAX_CANDIDATOS_PARA_SCARCITY,
) -> int:
    """[sección 8] Cuenta cuántas combinaciones (pallet, cuboide libre,
    orientación) admiten HOY al menos 1 caja de `sku` -corta apenas llega a
    `max_count` (0..4, donde 4 significa "4 o más"), no necesita enumerar
    miles."""
    from src.packing_bloques import _cuboide_admite_candidato

    tope_capa = capacidad_cama_por_sku.get(sku)
    nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
    tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
    count = 0
    for pidx, pc in enumerate(construcciones):
        if colocados_por_pallet[pidx].get(sku, 0) >= tope_pallet:
            continue
        pallet = pc.pallet
        for cand in por_sku.get(sku, []):
            for c in pc.libres:
                if _cuboide_admite_candidato(pallet, c, cand, tope_capa, nivel_sku, nivel_por_sku):
                    count += 1
                    if count >= max_count:
                        return count
    return count


def _ordenar_most_constrained_first(
    skus: list[str], skus_criticos: set[str], construcciones, colocados_por_pallet: list[dict[str, int]],
    pendientes: dict[str, int], por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
) -> list[str]:
    """[sección 5] Orden lexicográfico: 1) crítico sí/no, 2) menos
    candidatos factibles, 3) mayor footprint, 4) menos orientaciones,
    5) mayor demanda pendiente. NO es "caja más grande primero" como regla
    absoluta -es "menos alternativas primero", con el footprint como
    desempate, no como criterio principal."""
    def clave(sku: str) -> tuple:
        candidatas = por_sku.get(sku, [])
        factibles = _contar_candidatos_factibles(
            construcciones, colocados_por_pallet, sku, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        )
        return (
            0 if sku in skus_criticos else 1,
            factibles,
            -_footprint_maximo(candidatas),
            len(candidatas),
            -pendientes.get(sku, 0),
        )

    return sorted(skus, key=clave)


def _opciones_directas_para_sku(
    construcciones, colocados_por_pallet: list[dict[str, int]], pendientes: dict[str, int], sku: str,
    por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], opciones_max: int,
) -> list[tuple]:
    """Hasta `opciones_max` cuboides DISTINTOS que admiten `sku` hoy, cada
    uno con su mejor orientación y el lote MÁXIMO que cabría ahí -el
    llamador (`_colocar_critico_backtracking`) es quien decide, además del
    máximo, tamaños de lote parciales (sección 6)."""
    from src.packing_bloques import _cantidad_sin_solape, _capacidad_restante_en_capa, _cuboide_admite_candidato

    tope_capa = capacidad_cama_por_sku.get(sku)
    nivel_sku = nivel_por_sku.get(sku, config.NIVEL_REMATE)
    tope_pallet = tope_pallet_por_sku.get(sku, float("inf"))
    pendiente = pendientes.get(sku, 0)
    if pendiente <= 0:
        return []

    opciones = []
    for pidx, pc in enumerate(construcciones):
        ya_en_pallet = colocados_por_pallet[pidx].get(sku, 0)
        if ya_en_pallet >= tope_pallet:
            continue
        pallet = pc.pallet
        for idx_libre, c in enumerate(pc.libres):
            mejor = None
            for cand in por_sku.get(sku, []):
                if not _cuboide_admite_candidato(pallet, c, cand, tope_capa, nivel_sku, nivel_por_sku):
                    continue
                max_lote = min(
                    pendiente, tope_pallet - ya_en_pallet,
                    _capacidad_restante_en_capa(pallet, sku, c.z, tope_capa),
                    int((c.d + TOL) // cand.alto_caja),
                )
                max_lote = _cantidad_sin_solape(pallet, c, cand, max_lote)
                if max_lote <= 0:
                    continue
                sobra = c.w * c.h - cand.largo * cand.ancho
                if mejor is None or sobra < mejor[0]:
                    mejor = (sobra, cand, max_lote)
            if mejor is not None:
                sobra, cand, max_lote = mejor
                opciones.append(((c.z, sobra), pidx, idx_libre, cand, max_lote))

    opciones.sort(key=lambda o: o[0])
    return opciones[:opciones_max]


def _colocar_critico_backtracking(
    construcciones, colocados_por_pallet: list[dict[str, int]], pendientes: dict[str, int], sku: str,
    por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int],
    opciones_max: int = RESCUE_OPCIONES_SKU_CRITICO, max_nodos: int = RESCUE_MAX_NODOS_CRITICO,
    limite_tiempo: float | None = None,
    reloj: Callable[[], float] = time.process_time,
) -> int:
    """[secciones 5, 6, 7] Backtracking chico, dedicado a UN sku -en cada
    nodo prueba hasta `opciones_max` cuboides distintos (branching
    adaptativo) y, en cada uno, tamaños de lote {1, max, ceil(max/2)} en
    vez de forzar siempre la columna completa (sección 6: "no comprometer
    siempre una columna completa"). Deja `construcciones`/`colocados_por_
    pallet`/`pendientes` en el MEJOR estado encontrado (mismo mecanismo de
    snapshot/restore que el backtracking general). Devuelve cuántas
    unidades de `sku` logró colocar.

    [PATCH V6.12-R2-A1] `reloj` default `time.process_time` -mismo dominio
    temporal que `limite_tiempo` (calculado por el caller, `rescue_solver`,
    con ESTE mismo `reloj`). `deadline` y `reloj` deben pertenecer siempre
    al mismo dominio: nunca pasar `limite_tiempo` sin también pasar el
    `reloj` que lo produjo."""
    from src.packing_bloques import _restaurar_estado_pallets, _snapshot_estado_pallets

    inicial = pendientes.get(sku, 0)
    nodos = [0]
    mejor = {
        "colocado": 0,
        "snapshot": _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes),
    }

    def _tiempo_agotado() -> bool:
        return limite_tiempo is not None and reloj() > limite_tiempo

    def _dfs(colocado: int) -> None:
        nodos[0] += 1
        if colocado > mejor["colocado"]:
            mejor["colocado"] = colocado
            mejor["snapshot"] = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
        if nodos[0] > max_nodos or _tiempo_agotado() or pendientes.get(sku, 0) <= 0:
            return
        opciones = _opciones_directas_para_sku(
            construcciones, colocados_por_pallet, pendientes, sku, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, opciones_max,
        )
        for _, pidx, idx_libre, cand, max_lote in opciones:
            # [aquí, más grande primero -maximiza SOLO lo que este SKU
            # logra colocar, que es el único objetivo de esta función. La
            # exploración de lotes PARCIALES para dejar lugar a otros SKUs
            # (sección 6) se hace aparte, en `_aplicar_ruina_dirigida`
            # -acá adentro, con un solo SKU en juego, tomar menos de lo
            # necesario nunca ayuda: ver docstring del módulo.]
            for batch in reversed(_generar_batch_sizes(max_lote)):
                snap = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
                construcciones[pidx].colocar(cand, batch, idx_libre)
                pendientes[sku] -= batch
                colocados_por_pallet[pidx][sku] = colocados_por_pallet[pidx].get(sku, 0) + batch
                _dfs(colocado + batch)
                _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)
                if nodos[0] > max_nodos or _tiempo_agotado():
                    return

    _dfs(0)
    _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, mejor["snapshot"])
    return inicial - pendientes.get(sku, 0)


def _generar_posiciones_objetivo(
    construcciones, candidatas: list[TorreCandidate], presupuesto: float,
) -> list[tuple[int, float, float, float, TorreCandidate]]:
    """[sección 9.1] Posiciones candidatas usando SOLO coordenadas
    estructurales: bordes del envelope, bordes X/Y de torres y cuboides
    libres YA existentes, topes Z reales -nunca barrido centímetro a
    centímetro."""
    margen = config.SOBRESALIENTE_MAX_CM
    posiciones = []
    vistos = set()
    for pidx, pc in enumerate(construcciones):
        anclas_xy = {(0.0, 0.0)}
        anclas_z = {0.0}
        for t in pc.pallet.torres:
            anclas_xy.add((round(t.x, 4), round(t.y, 4)))
            anclas_z.add(round(t.z, 4))
            anclas_z.add(round(t.z + t.altura, 4))
        for c in pc.libres:
            anclas_xy.add((round(c.x, 4), round(c.y, 4)))
            anclas_z.add(round(c.z, 4))

        for (x, y) in anclas_xy:
            if x < -margen - TOL or y < -margen - TOL:
                continue
            for z in anclas_z:
                if z >= presupuesto - TOL:
                    continue
                for cand in candidatas:
                    if z + cand.alto_caja > presupuesto + TOL:
                        continue
                    if x + cand.largo > config.PALLET_LARGO + margen + TOL:
                        continue
                    if y + cand.ancho > config.PALLET_ANCHO + margen + TOL:
                        continue
                    clave = (pidx, x, y, z, cand.orientacion)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    posiciones.append((pidx, x, y, z, cand))
    return posiciones


def _blockers_para_posicion(pallet: PalletV5, x: float, y: float, z: float, cand: TorreCandidate) -> list:
    """[sección 9.2] Torres que habría que retirar para que esta posición
    quede libre de overlap -overlap AABB 3D, mismo criterio que
    `packing_bloques._solapa_con_torres`."""
    return [
        t for t in pallet.torres
        if (t.x < x + cand.largo - TOL and x < t.x + t.largo - TOL
            and t.y < y + cand.ancho - TOL and y < t.y + t.ancho - TOL
            and t.z < z + cand.alto_caja - TOL and z < t.z + t.altura - TOL)
    ]


def _quedaria_flotando(pallet: PalletV5, blockers: list, x: float, y: float, z: float, cand: TorreCandidate) -> bool:
    """[sección 9.2, bug real encontrado probando esto contra BK31: MaxRects
    nunca genera un cuboide libre a media altura sin soporte real debajo
    -"nunca abajo en Z", ver packing_columnar.py- así que una posición
    objetivo que solo queda libre de OVERLAP pero SIN soporte real (sin
    contar los propios blockers que se están por retirar) nunca va a
    aparecer como cuboide libre después de la ruina: `_opciones_directas_
    para_sku` la va a rechazar igual, gastando el intento en el shortlist
    para nada. Se descarta ACÁ, antes de proponerla como conflicto."""
    if z <= TOL:
        return False
    ids_blockers = {id(t) for t in blockers}
    soportes = [
        t for t in pallet.torres
        if id(t) not in ids_blockers and abs((t.z + t.altura) - z) <= TOL
    ]
    torre_candidata = crear_torre(cand, x=x, y=y, z=z, cantidad=1)
    return not _tiene_soporte_admisible(torre_candidata, soportes)


def _rankear_conflictos(
    construcciones, sku_critico: str, candidatas: list[TorreCandidate], presupuesto: float,
    shortlist: int = RESCUE_CONFLICT_SHORTLIST,
) -> list[tuple]:
    """[sección 9.2, 9.3] Para cada posición objetivo, identifica los
    blockers (torres a retirar) y arma una shortlist priorizando menos
    cajas / menor volumen a retirar. Nunca propone desplazar cajas del
    propio SKU crítico (no tendría sentido), ni una posición que quedaría
    flotando incluso después de retirar los blockers (`_quedaria_
    flotando`). Devuelve entradas (clave_ranking, pidx, x, y, z, cand,
    blocker_skus)."""
    conflictos = []
    for pidx, x, y, z, cand in _generar_posiciones_objetivo(construcciones, candidatas, presupuesto):
        pallet = construcciones[pidx].pallet
        blockers = _blockers_para_posicion(pallet, x, y, z, cand)
        if not blockers:
            continue  # sin blockers ya lo hubiera encontrado la colocación directa
        blocker_skus = {t.sku for t in blockers}
        if sku_critico in blocker_skus:
            continue
        if _quedaria_flotando(pallet, blockers, x, y, z, cand):
            continue
        volumen = sum(t.largo * t.ancho * t.altura for t in blockers)
        clave = (len(blocker_skus), volumen, len(blockers))
        conflictos.append((clave, pidx, x, y, z, cand, blocker_skus))

    conflictos.sort(key=lambda c: c[0])
    vistos_blockers: set[frozenset] = set()
    resultado = []
    for conflicto in conflictos:
        clave_blockers = frozenset(conflicto[-1])
        if clave_blockers in vistos_blockers:
            continue
        vistos_blockers.add(clave_blockers)
        resultado.append(conflicto)
        if len(resultado) >= shortlist:
            break
    return resultado


def _aplicar_ruina_dirigida(
    construcciones, colocados_por_pallet: list[dict[str, int]], pendientes: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]], capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int], tope_pallet_por_sku: dict[str, int], presupuesto: float, n_pallets: int,
    sku_critico: str, blocker_skus: set[str], limite_tiempo: float | None,
    reloj: Callable[[], float] = time.process_time,
) -> int:
    """[sección 9.4] Retira `blocker_skus` (con cascada anti-flotación,
    `_romper_skus_con_cascada`), prueba distintos lotes del `sku_critico`
    en su mejor posición (sección 6), y para cada uno reconstruye el resto
    (blockers + lo que ya faltaba) con el backtracking general -se
    conserva la variante con más cajas colocadas EN TOTAL al final
    (sección 10: la comparación se hace después de reconstruir todo, nunca
    a mitad de camino). El caller decide si este resultado mejora el
    incumbente o si revierte.

    [PATCH V6.12-R2-A1, cierre R2-A0] `reloj` default `time.process_time`
    -antes de este patch, las dos llamadas a `_resolver_pallets_
    backtracking` de abajo NO pasaban `reloj=`, heredando ese mismo default
    mientras `limite_tiempo` (calculado en `rescue_solver`/`repair_solver`)
    era de `time.time()` -mismatch de dominio que dejaba inerte el corte
    por tiempo ahí (ver auditoría R2-A0: en la práctica equivalente, porque
    `max_nodos` ya cortaba antes en todos los casos medidos, aislado y bajo
    contención). Ahora `reloj` se pasa explícito, sin depender del
    default -mismo dominio temporal en todo el camino."""
    from src.packing_bloques import (
        COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION,
        _resolver_pallets_backtracking,
        _restaurar_estado_pallets,
        _romper_skus_con_cascada,
        _snapshot_estado_pallets,
    )

    _romper_skus_con_cascada(construcciones, colocados_por_pallet, pendientes, set(blocker_skus), n_pallets)

    def _total_colocado() -> int:
        return sum(sum(d.values()) for d in colocados_por_pallet)

    snap_post_ruina = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)

    # [sección 6] "No comprometer siempre una columna completa": antes de
    # reconstruir todo junto, se prueba comprometer distintos tamaños de
    # lote {1, max, ceil(max/2)} del SKU crítico en su MEJOR posición -no
    # siempre el lote máximo- y se deja que el backtracking general
    # (`_resolver_pallets_backtracking`, prioridad normal, compite con
    # TODO lo que quedó pendiente -blockers incluidos) complete el resto
    # sobre lo que quede libre. Se conserva el resultado FINAL (después de
    # reconstruir todo, sección 10) con más cajas totales -un lote máximo
    # que deja el mejor cuboide sin nada para los blockers puede perder
    # contra un lote parcial que sí les deja lugar, aunque el SKU crítico
    # por sí solo coloque menos en esta posición puntual.
    opciones = _opciones_directas_para_sku(
        construcciones, colocados_por_pallet, pendientes, sku_critico, por_sku,
        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, opciones_max=1,
    )
    if not opciones:
        _resolver_pallets_backtracking(
            construcciones, colocados_por_pallet, pendientes, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
            max_nodos=COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION, limite_tiempo=limite_tiempo,
            reloj=reloj,
        )
        return _total_colocado()

    _, pidx, idx_libre, cand, max_lote = opciones[0]
    mejor_total = -1
    mejor_snapshot = None
    for batch in reversed(_generar_batch_sizes(max_lote)):
        _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap_post_ruina)
        construcciones[pidx].colocar(cand, batch, idx_libre)
        pendientes[sku_critico] -= batch
        colocados_por_pallet[pidx][sku_critico] = colocados_por_pallet[pidx].get(sku_critico, 0) + batch
        _resolver_pallets_backtracking(
            construcciones, colocados_por_pallet, pendientes, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
            max_nodos=COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION, limite_tiempo=limite_tiempo,
            reloj=reloj,
        )
        total_actual = _total_colocado()
        if total_actual > mejor_total:
            mejor_total = total_actual
            mejor_snapshot = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
        if limite_tiempo is not None and reloj() > limite_tiempo:
            break

    _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, mejor_snapshot)
    return mejor_total


def _volumen_sin_colocar(pendientes: dict[str, int], por_sku: dict[str, list[TorreCandidate]]) -> float:
    total = 0.0
    for sku, cant in pendientes.items():
        if cant <= 0:
            continue
        candidatas = por_sku.get(sku, [])
        if not candidatas:
            continue
        vol_min = min(c.largo * c.ancho * c.alto_caja for c in candidatas)
        total += cant * vol_min
    return total


def skus_completos(pendientes: dict[str, int], por_sku: dict[str, list[TorreCandidate]]) -> frozenset[str]:
    """[PATCH V6.04, sección 3] SKUs 100% colocados en un estado dado -se
    usa para capturar `skus_completos_en_baseline` ANTES de que rescue/
    repair toquen nada, y así poder detectar en el score si una solución
    "swapea" uno de esos SKUs por otro sin ganancia real."""
    return frozenset(sku for sku in por_sku if pendientes.get(sku, 0) <= 0)


def _score_solucion(
    total_colocado: int, pendientes: dict[str, int], por_sku: dict[str, list[TorreCandidate]],
    pallets: list[PalletV5], skus_protegidos: frozenset[str] = frozenset(),
) -> tuple:
    """[PATCH V6.04, sección 2] Score lexicográfico coverage-aware.
    Primario: demanda total colocada (nunca cambia -sigue siendo lo que
    manda). Desempates, en orden: 1) más SKUs completamente satisfechos,
    2) menos SKUs con faltantes, 3) menos cajas de SKUs que ESTABAN
    completos en baseline (`skus_protegidos`) y pasaron a faltantes -sin
    esto, dos soluciones con el mismo total podían preferir una que
    "cambia" un SKU ya resuelto por otro, en vez de simplemente sumar
    cobertura (bug real encontrado en BK52: el rescue V6.02 recuperó 10
    SKUs pero rompió 3 que ya estaban completos, y el score viejo no tenía
    forma de penalizar eso), 4) menos volumen sin colocar, 5) menor altura
    máxima."""
    skus_con_faltantes = {sku for sku, cant in pendientes.items() if cant > 0}
    skus_completamente_satisfechos = len(por_sku) - len(skus_con_faltantes)
    cajas_nuevos_faltantes = sum(
        cant for sku, cant in pendientes.items() if cant > 0 and sku in skus_protegidos
    )
    altura_max = max((p.altura_final for p in pallets), default=0.0)
    return (
        total_colocado,
        skus_completamente_satisfechos,
        -len(skus_con_faltantes),
        -cajas_nuevos_faltantes,
        -_volumen_sin_colocar(pendientes, por_sku),
        -altura_max,
    )


def rescue_solver(
    pallets: list[PalletV5],
    sin_colocar: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    n_pallets: int,
    presupuesto: float,
    deadline: float | None = None,
) -> tuple[list[PalletV5], dict[str, int], dict]:
    """[sección 3] Punto de entrada. Recibe el MEJOR resultado ya obtenido
    por el camino normal (`pallets` + `sin_colocar`) y trata de mejorarlo
    -nunca puede devolver algo peor (sección 11: se compara por score antes
    de aceptar cualquier cambio). `deadline` es un tope de reloj absoluto
    adicional (p.ej. el mismo deadline de LNS del llamador); el propio
    presupuesto de `RESCUE_TIME_MAX_SECONDS` (sección 12) siempre aplica
    encima.

    Devuelve (pallets, sin_colocar, stats) -`stats` es la instrumentación
    de la sección 16.

    [PATCH V6.12-R2-A1] `reloj = time.process_time` explícito -mismo
    patrón de V6.11-R3 (`_search_budget_now`), corregido para este módulo
    tras la auditoría R2-A0: antes, `limite_tiempo` se calculaba con
    `time.time()` (reloj de pared) mientras `_resolver_pallets_
    backtracking` (llamada desde `_aplicar_ruina_dirigida`) usaba su
    default `reloj=time.process_time` -mismatch de dominio que dejaba
    inerte el corte por tiempo ahí. Ahora `reloj` se calcula UNA vez acá y
    se pasa explícito a TODO lo que recibe `limite_tiempo`
    (`_colocar_critico_backtracking`, `_aplicar_ruina_dirigida`, y de ahí
    a `_resolver_pallets_backtracking`) -deadline y checker siempre en el
    mismo dominio temporal, nunca por default implícito. `deadline`
    (parámetro externo, ver `packing_bloques._empacar_n_pallets`) también
    debe venir ya en este mismo dominio (CPU-time)."""
    from src.packing_bloques import _restaurar_estado_pallets, _snapshot_estado_pallets

    reloj: Callable[[], float] = time.process_time
    t0_wall = time.time()  # solo para stats["tiempo_segundos"] (diagnóstico humano, no budget)
    limite_tiempo = reloj() + RESCUE_TIME_MAX_SECONDS
    if deadline is not None:
        limite_tiempo = min(limite_tiempo, deadline)

    stats = {
        "activado": True,
        "iteraciones": 0,
        "skus_criticos": set(),
        "candidatos_explorados": 0,
        "conflictos_evaluados": 0,
        "blockers_retirados": 0,
        "por_sku_critico": {},
    }

    construcciones = [_reconstruir_en_construccion(p) for p in pallets]
    colocados_por_pallet = [
        {sku: sum(t.cantidad for t in pc.pallet.torres if t.sku == sku) for sku in {t.sku for t in pc.pallet.torres}}
        for pc in construcciones
    ]
    pendientes: dict[str, int] = {sku: 0 for sku in por_sku}
    pendientes.update(sin_colocar)
    # [PATCH V6.04, sección 3] Capturado ANTES de que rescue toque nada
    # -"protegido" no significa "congelado": estos SKUs SÍ pueden romperse
    # temporalmente durante una ruina, pero una solución FINAL que deja
    # alguno de ellos con faltantes nuevos no debe preferirse sobre otra
    # con la misma cantidad total y mejor cobertura (ver `_score_solucion`).
    skus_protegidos = skus_completos(pendientes, por_sku)

    total_inicial = sum(sum(d.values()) for d in colocados_por_pallet)
    mejor_total = total_inicial
    mejor_score = _score_solucion(
        total_inicial, pendientes, por_sku, [pc.pallet for pc in construcciones], skus_protegidos,
    )
    mejor_snapshot = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)

    for sku, cant in sin_colocar.items():
        stats["por_sku_critico"][sku] = {"candidatos_antes": _contar_candidatos_factibles(
            construcciones, colocados_por_pallet, sku, por_sku, capacidad_cama_por_sku,
            nivel_por_sku, tope_pallet_por_sku,
        ), "candidatos_despues_ruina": 0, "colocadas": 0}

    while reloj() < limite_tiempo:
        criticos = _identificar_skus_criticos(pendientes)
        if not criticos:
            break  # [sección 12] 100% de demanda -detenerse ya, sin seguir "optimizando"
        stats["skus_criticos"] |= criticos

        orden = _ordenar_most_constrained_first(
            sorted(criticos), criticos, construcciones, colocados_por_pallet, pendientes,
            por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        )

        progreso_en_ronda = False
        for sku in orden:
            if reloj() > limite_tiempo:
                break
            if pendientes.get(sku, 0) <= 0:
                continue
            stats["iteraciones"] += 1
            candidatas_sku = por_sku.get(sku, [])

            antes = pendientes[sku]
            _colocar_critico_backtracking(
                construcciones, colocados_por_pallet, pendientes, sku, por_sku,
                capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
                limite_tiempo=limite_tiempo, reloj=reloj,
            )
            if pendientes[sku] < antes:
                # [bug real encontrado escribiendo esto: un progreso PARCIAL
                # (pendiente baja pero no llega a 0) también sube `total_
                # colocado` -si no se registra ACÁ como posible mejor_score,
                # y ningún paso posterior vuelve a superarlo estrictamente,
                # `_restaurar_estado_pallets(mejor_snapshot)` al final
                # revierte ESTE progreso real por no haber quedado guardado.]
                progreso_en_ronda = True
                total_actual = sum(sum(d.values()) for d in colocados_por_pallet)
                score_actual = _score_solucion(total_actual, pendientes, por_sku, [pc.pallet for pc in construcciones], skus_protegidos)
                if score_actual > mejor_score:
                    mejor_score = score_actual
                    mejor_total = total_actual
                    mejor_snapshot = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)

            if pendientes.get(sku, 0) <= 0:
                continue

            # [sección 9] Colocación directa no alcanzó -conflict-directed ruin.
            conflictos = _rankear_conflictos(construcciones, sku, candidatas_sku, presupuesto)
            stats["conflictos_evaluados"] += len(conflictos)
            stats["candidatos_explorados"] += sum(
                len(pc.libres) * len(candidatas_sku) for pc in construcciones
            )

            for _, pidx, x, y, z, cand, blocker_skus in conflictos:
                if reloj() > limite_tiempo:
                    break
                snap = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
                total_resultante = _aplicar_ruina_dirigida(
                    construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku,
                    nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, sku, blocker_skus, limite_tiempo,
                    reloj=reloj,
                )
                score_resultante = _score_solucion(total_resultante, pendientes, por_sku, [pc.pallet for pc in construcciones], skus_protegidos)
                if score_resultante > mejor_score:
                    mejor_score = score_resultante
                    mejor_total = total_resultante
                    mejor_snapshot = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
                    progreso_en_ronda = True
                    stats["blockers_retirados"] += len(blocker_skus)
                    stats["por_sku_critico"].setdefault(sku, {})["candidatos_despues_ruina"] = (
                        _contar_candidatos_factibles(
                            construcciones, colocados_por_pallet, sku, por_sku, capacidad_cama_por_sku,
                            nivel_por_sku, tope_pallet_por_sku,
                        )
                    )
                    break  # esta mejora alcanza para esta ronda -reevaluar most-constrained-first desde cero
                else:
                    _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)

        if not progreso_en_ronda:
            break  # una ronda completa sin mejorar nada -no hay más que el rescue pueda hacer ahora

    _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, mejor_snapshot)
    pallets_final = [pc.pallet for pc in construcciones]
    sin_colocar_final = {sku: cant for sku, cant in pendientes.items() if cant > 0}

    stats["skus_criticos"] = sorted(stats["skus_criticos"])
    stats["mejor_mejora"] = mejor_total - total_inicial
    stats["colocadas"] = mejor_total
    stats["tiempo_segundos"] = round(time.time() - t0_wall, 3)
    for sku, d in stats["por_sku_critico"].items():
        pendiente_final = sin_colocar_final.get(sku, 0)
        d["pendiente_final"] = pendiente_final
        d["colocadas"] = sin_colocar.get(sku, 0) - pendiente_final

    return pallets_final, sin_colocar_final, stats
