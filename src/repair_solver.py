"""[PATCH V6.04] Repair Solver v2 -coverage-aware LNS + neighborhoods
conflictivos iterativos + reconstrucción multi-crítica + ejection chains
entre pallets.

Se activa DESPUÉS del Rescue V6.02 (`src/rescue_solver.py`), SOLO si éste
no llegó al 100% de la demanda -nunca lo reemplaza, solo intenta
mejorarlo con el MISMO criterio de score (`rescue_solver._score_solucion`,
ya coverage-aware desde este mismo patch) y nunca devuelve algo peor
(sección 14 del patch: baseline -> Rescue V6.02 -> Repair V6.04 -> Exact
Local Repair -> mejor solución válida).

Reusa toda la maquinaria de `rescue_solver.py` (posiciones objetivo,
blockers, ruina dirigida, backtracking chico por SKU) -lo que agrega acá
es CUÁNTO más lejos buscar (neighborhoods geométricos, más de un SKU
crítico a la vez, y movimientos entre pallets) cuando esa maquinaria base
no alcanza."""
from __future__ import annotations

import itertools
import time
from collections.abc import Callable

import config
from models import PalletV5
from src.packing_columnar import _reconstruir_en_construccion
from src.rescue_solver import (
    RESCUE_TIME_MAX_SECONDS,
    TOL,
    _aplicar_ruina_dirigida,
    _blockers_para_posicion,
    _colocar_critico_backtracking,
    _generar_posiciones_objetivo,
    _identificar_skus_criticos,
    _ordenar_most_constrained_first,
    _quedaria_flotando,
    _score_solucion,
    skus_completos,
)
from src.torres import TorreCandidate

# [sección 5] Niveles de neighborhood -margen geométrico (cm) para
# "vecinos" que no solapan directo con la posición objetivo pero pueden
# estar fragmentando el rectángulo necesario (sección 6). Nivel 1 =
# comportamiento exacto del Rescue V6.02 (solo blockers directos).
RESCUE_NEIGHBORHOOD_LEVELS = 3
_MARGEN_POR_NIVEL = {1: 0.0, 2: 2.0, 3: 20.0}

# [sección 7] Cuántos SKUs críticos atacar EN CONJUNTO (sin revertir entre
# uno y otro) antes de comparar el resultado final contra el incumbente.
RESCUE_MULTI_CRITICAL_K = 3

# [sección 8] Profundidad máxima de la ejection chain -1 salto (ejectar 1
# SKU) o 2 (ejectar una combinación de 2).
EJECTION_CHAIN_MAX_DEPTH = 2

# [sección 4] Tamaño de la shortlist Pareto (soluciones no dominadas).
RESCUE_PARETO_K = 6

# [sección 15] Reexportado con su propio nombre para que packing_bloques.py
# pueda darle al repair su PROPIO presupuesto de reloj, separado del
# rescue -mismo valor por defecto (90s), pero un deadline independiente.
REPAIR_TIME_MAX_SECONDS = RESCUE_TIME_MAX_SECONDS


def _vecinos_geometricos(
    x: float, y: float, largo: float, ancho: float, pallet: PalletV5, margen_cm: float, excluir_ids: set[int],
) -> list:
    """[sección 6] Torres cuya huella XY está a <= `margen_cm` del target
    (x, y, largo, ancho) -sin usar categoría ni SKU, solo geometría. Sirve
    para capturar piezas que no solapan directo con la posición objetivo
    pero fragmentan el rectángulo que hace falta liberar."""
    vecinos = []
    for t in pallet.torres:
        if id(t) in excluir_ids:
            continue
        gap_x = max(t.x - (x + largo), x - (t.x + t.largo), 0.0)
        gap_y = max(t.y - (y + ancho), y - (t.y + t.ancho), 0.0)
        if max(gap_x, gap_y) <= margen_cm + TOL:
            vecinos.append(t)
    return vecinos


def _rankear_conflictos_por_nivel(
    construcciones, sku_critico: str, candidatas: list[TorreCandidate], presupuesto: float, nivel: int,
    shortlist: int,
) -> list[tuple]:
    """[sección 5] Igual que `rescue_solver._rankear_conflictos`, pero en
    niveles >1 el conjunto de blockers de cada posición objetivo se
    amplía con sus vecinos geométricos (sección 6) -más caro por posición,
    por eso se prueba nivel por nivel, no siempre el más ancho."""
    margen_geo = _MARGEN_POR_NIVEL.get(nivel, _MARGEN_POR_NIVEL[max(_MARGEN_POR_NIVEL)])
    conflictos = []
    for pidx, x, y, z, cand in _generar_posiciones_objetivo(construcciones, candidatas, presupuesto):
        pallet = construcciones[pidx].pallet
        blockers = _blockers_para_posicion(pallet, x, y, z, cand)
        if not blockers:
            continue
        if nivel > 1:
            ids_ya = {id(t) for t in blockers}
            blockers = blockers + _vecinos_geometricos(x, y, cand.largo, cand.ancho, pallet, margen_geo, ids_ya)
        blocker_skus = {t.sku for t in blockers}
        if sku_critico in blocker_skus:
            continue
        if _quedaria_flotando(pallet, blockers, x, y, z, cand):
            continue
        volumen = sum(t.largo * t.ancho * t.altura for t in blockers)
        clave = (len(blocker_skus), volumen, len(blockers))
        conflictos.append((clave, pidx, x, y, z, cand, blocker_skus))

    conflictos.sort(key=lambda c: c[0])
    vistos: set[frozenset] = set()
    resultado = []
    for conflicto in conflictos:
        clave_blockers = frozenset(conflicto[-1])
        if clave_blockers in vistos:
            continue
        vistos.add(clave_blockers)
        resultado.append(conflicto)
        if len(resultado) >= shortlist:
            break
    return resultado


def _intentar_neighborhoods_iterativos(
    construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku,
    tope_pallet_por_sku, presupuesto, n_pallets, sku_critico, limite_tiempo, shortlist: int = 8,
    reloj: Callable[[], float] = time.process_time,
) -> bool:
    """[sección 5] Prueba niveles 1..RESCUE_NEIGHBORHOOD_LEVELS EN ORDEN,
    deteniéndose apenas alguno resuelve del todo al SKU crítico -no
    destruye arbitrariamente más de lo necesario. Devuelve True si mejoró
    ALGO (parcial o total); el estado queda tal cual lo dejó el último
    intento aceptado (el caller compara score, no revierte acá).

    [PATCH V6.12-R2-A1] `reloj` -mismo dominio temporal que `limite_tiempo`
    (calculado por `repair_solver`); se pasa explícito a `_aplicar_ruina_
    dirigida`, nunca por default."""
    from src.packing_bloques import _restaurar_estado_pallets, _snapshot_estado_pallets

    candidatas_sku = por_sku.get(sku_critico, [])
    mejoro_algo = False
    for nivel in range(1, RESCUE_NEIGHBORHOOD_LEVELS + 1):
        if limite_tiempo is not None and reloj() > limite_tiempo:
            break
        if pendientes.get(sku_critico, 0) <= 0:
            break
        conflictos = _rankear_conflictos_por_nivel(
            construcciones, sku_critico, candidatas_sku, presupuesto, nivel, shortlist,
        )
        for _, pidx, x, y, z, cand, blocker_skus in conflictos:
            if limite_tiempo is not None and reloj() > limite_tiempo:
                break
            antes = pendientes.get(sku_critico, 0)
            snap = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
            _aplicar_ruina_dirigida(
                construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku,
                nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, sku_critico, blocker_skus,
                limite_tiempo, reloj=reloj,
            )
            if pendientes.get(sku_critico, 0) < antes:
                mejoro_algo = True
                if pendientes.get(sku_critico, 0) <= 0:
                    return True
            else:
                _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)
        if pendientes.get(sku_critico, 0) <= 0:
            break
    return mejoro_algo


def _buscar_ejection_chain(
    construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku,
    tope_pallet_por_sku, presupuesto, n_pallets, sku_critico, limite_tiempo, max_depth: int = EJECTION_CHAIN_MAX_DEPTH,
    reloj: Callable[[], float] = time.process_time,
) -> bool:
    """[sección 8, 9] Para un SKU crítico sin blockers directos ni
    vecinos que ayuden (típicamente cuando el problema es entre pallets,
    no dentro de uno), prueba "ejectar" -sacar del pallet donde estén
    hoy, sin importar si solapan la posición objetivo- otros SKUs ya
    colocados (uno solo, profundidad 1; pares, profundidad 2, acotado a
    los de menor volumen para no explotar) y, tras cada intento, deja que
    `_colocar_critico_backtracking` busque un lugar para el crítico EN
    CUALQUIER PALLET -si entra, reconstruye lo ejectado con el
    backtracking general (que también puede ubicarlo en un pallet
    distinto al original, un verdadero movimiento entre pallets). Cada
    movimiento pasa por las mismas funciones de admisión reales
    (overhang, altura, overlap, soporte, Cajas por PH, orientación,
    nivel) -nunca una cadena parcialmente válida: si el crítico no entra,
    se revierte TODO antes de probar la siguiente combinación."""
    from src.packing_bloques import (
        COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION,
        _resolver_pallets_backtracking,
        _restaurar_estado_pallets,
        _romper_skus_con_cascada,
        _snapshot_estado_pallets,
    )

    if n_pallets < 2 or not por_sku.get(sku_critico):
        return False

    skus_presentes = sorted({
        t.sku for pc in construcciones for t in pc.pallet.torres if t.sku != sku_critico
    })
    if not skus_presentes:
        return False

    def _volumen_sku(sku: str) -> float:
        cands = por_sku.get(sku, [])
        return min((c.largo * c.ancho * c.alto_caja for c in cands), default=float("inf"))

    skus_presentes.sort(key=_volumen_sku)

    combinaciones: list[tuple[str, ...]] = [(s,) for s in skus_presentes]
    if max_depth >= 2:
        combinaciones += list(itertools.combinations(skus_presentes[:10], 2))

    for combo in combinaciones:
        if limite_tiempo is not None and reloj() > limite_tiempo:
            break
        snap = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
        _romper_skus_con_cascada(construcciones, colocados_por_pallet, pendientes, set(combo), n_pallets)

        antes = pendientes.get(sku_critico, 0)
        _colocar_critico_backtracking(
            construcciones, colocados_por_pallet, pendientes, sku_critico, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, limite_tiempo=limite_tiempo,
            reloj=reloj,
        )
        if pendientes.get(sku_critico, 0) < antes:
            # [sección 9] Reconstruir lo ejectado -si algo de `combo` no
            # vuelve a entrar, el score de afuera (coverage-aware) es quien
            # decide si esta cadena valió la pena o no frente al incumbente.
            _resolver_pallets_backtracking(
                construcciones, colocados_por_pallet, pendientes, por_sku,
                capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets,
                max_nodos=COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION, limite_tiempo=limite_tiempo,
                reloj=reloj,
            )
            return True
        _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)

    return False


def _reconstruccion_multi_critica(
    construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku,
    tope_pallet_por_sku, presupuesto, n_pallets, skus_top_k: list[str], limite_tiempo,
    reloj: Callable[[], float] = time.process_time,
) -> bool:
    """[sección 7] Ataca los `skus_top_k` SKUs más restringidos EN
    CONJUNTO -sin revertir entre uno y otro- para que la reconstrucción
    de uno pueda apoyarse en el espacio que dejó libre resolver el
    anterior. El caller compara el resultado COMBINADO contra el
    incumbente por score, no a mitad de camino."""
    progreso = False
    for sku in skus_top_k:
        if limite_tiempo is not None and reloj() > limite_tiempo:
            break
        if pendientes.get(sku, 0) <= 0:
            continue
        antes = pendientes.get(sku, 0)
        _colocar_critico_backtracking(
            construcciones, colocados_por_pallet, pendientes, sku, por_sku,
            capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, limite_tiempo=limite_tiempo,
            reloj=reloj,
        )
        if pendientes.get(sku, 0) < antes:
            progreso = True
        if pendientes.get(sku, 0) > 0:
            if _intentar_neighborhoods_iterativos(
                construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku,
                nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, sku, limite_tiempo,
                reloj=reloj,
            ):
                progreso = True
    return progreso


class _ArchivoPareto:
    """[sección 4] Shortlist de soluciones NO dominadas -A domina a B si
    A coloca >= cajas, satisface >= SKUs completos, y genera <= SKUs
    nuevos faltantes, con al menos una mejora estricta. Evita perder una
    configuración prometedora solo porque otra empate en cajas totales
    con peor distribución de cobertura."""

    def __init__(self, k: int = RESCUE_PARETO_K):
        self.k = k
        self.items: list[tuple[tuple, object]] = []  # (score, snapshot)

    @staticmethod
    def _domina(a: tuple, b: tuple) -> bool:
        # Compara SOLO las 3 primeras dimensiones del score (cajas, SKUs
        # completos, -SKUs con faltantes) -las últimas (volumen, altura)
        # son desempates finos, no criterios de dominancia por sí solos.
        a3, b3 = a[:3], b[:3]
        return all(x >= y for x, y in zip(a3, b3)) and any(x > y for x, y in zip(a3, b3))

    def considerar(self, score: tuple, snapshot) -> None:
        if any(self._domina(s, score) for s, _ in self.items):
            return
        self.items = [(s, snap) for s, snap in self.items if not self._domina(score, s)]
        self.items.append((score, snapshot))
        self.items.sort(key=lambda item: item[0], reverse=True)
        self.items = self.items[: self.k]

    def mejor(self):
        return self.items[0] if self.items else None

    def segundo_mejor(self):
        return self.items[1] if len(self.items) > 1 else None


def repair_solver(
    pallets: list[PalletV5],
    sin_colocar: dict[str, int],
    por_sku: dict[str, list[TorreCandidate]],
    capacidad_cama_por_sku: dict[str, int],
    nivel_por_sku: dict[str, int],
    tope_pallet_por_sku: dict[str, int],
    n_pallets: int,
    presupuesto: float,
    skus_protegidos: frozenset[str] = frozenset(),
    deadline: float | None = None,
) -> tuple[list[PalletV5], dict[str, int], dict]:
    """[sección 14] Punto de entrada del Repair Solver v2. Recibe lo que
    dejó el Rescue V6.02 (`pallets` + `sin_colocar`, que puede ya venir
    con `skus_protegidos` -SKUs completos en el baseline ORIGINAL, antes
    de rescue Y de repair) y trata de mejorarlo con neighborhoods
    iterativos, reconstrucción multi-crítica y ejection chains. Nunca
    peor: el caller compara por score antes de aceptar el resultado.

    [PATCH V6.12-R2-A1] Mismo patrón que `rescue_solver`: `reloj =
    time.process_time` explícito, calculado UNA vez acá y pasado a todo lo
    que recibe `limite_tiempo` -deadline y checker en el mismo dominio
    temporal siempre, nunca por default implícito."""
    from src.packing_bloques import _restaurar_estado_pallets, _snapshot_estado_pallets

    reloj: Callable[[], float] = time.process_time
    t0_wall = time.time()  # solo para stats["tiempo_segundos"] (diagnóstico humano, no budget)
    limite_tiempo = reloj() + REPAIR_TIME_MAX_SECONDS
    if deadline is not None:
        limite_tiempo = min(limite_tiempo, deadline)

    stats = {
        "activado": True,
        "rondas": 0,
        "neighborhoods_usados": set(),
        "ejection_chains_intentadas": 0,
        "ejection_chains_exitosas": 0,
        "multi_criticas_intentadas": 0,
        "pareto_alternativas": 0,
    }

    construcciones = [_reconstruir_en_construccion(p) for p in pallets]
    colocados_por_pallet = [
        {sku: sum(t.cantidad for t in pc.pallet.torres if t.sku == sku) for sku in {t.sku for t in pc.pallet.torres}}
        for pc in construcciones
    ]
    pendientes: dict[str, int] = {sku: 0 for sku in por_sku}
    pendientes.update(sin_colocar)

    total_inicial = sum(sum(d.values()) for d in colocados_por_pallet)
    archivo = _ArchivoPareto()
    score_inicial = _score_solucion(
        total_inicial, pendientes, por_sku, [pc.pallet for pc in construcciones], skus_protegidos,
    )
    snap_inicial = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
    archivo.considerar(score_inicial, snap_inicial)
    mejor_total = total_inicial

    def _score_actual() -> tuple:
        total = sum(sum(d.values()) for d in colocados_por_pallet)
        return _score_solucion(total, pendientes, por_sku, [pc.pallet for pc in construcciones], skus_protegidos)

    while reloj() < limite_tiempo:
        criticos = _identificar_skus_criticos(pendientes)
        if not criticos:
            break  # 100% -detenerse ya, no seguir "optimizando" estética (sección 13)
        stats["rondas"] += 1

        orden = _ordenar_most_constrained_first(
            sorted(criticos), criticos, construcciones, colocados_por_pallet, pendientes,
            por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        )

        progreso_en_ronda = False

        # [sección 7] Multi-critical: los top-K más restringidos, EN CONJUNTO.
        top_k = orden[:RESCUE_MULTI_CRITICAL_K]
        if len(top_k) > 1 and any(pendientes.get(s, 0) > 0 for s in top_k):
            snap = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
            stats["multi_criticas_intentadas"] += 1
            _reconstruccion_multi_critica(
                construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku,
                nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, top_k, limite_tiempo,
                reloj=reloj,
            )
            score_actual = _score_actual()
            archivo.considerar(score_actual, _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes))
            mejor_actual = archivo.mejor()
            if score_actual < mejor_actual[0]:
                _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)
            else:
                progreso_en_ronda = progreso_en_ronda or (score_actual > score_inicial)

        # [sección 5, 8] SKU por SKU: neighborhoods iterativos, y si eso no
        # alcanza (típicamente 0 blockers ni siquiera en nivel 3), ejection
        # chain entre pallets.
        for sku in orden:
            if reloj() > limite_tiempo:
                break
            if pendientes.get(sku, 0) <= 0:
                continue

            snap = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
            score_antes_sku = _score_actual()
            _intentar_neighborhoods_iterativos(
                construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku,
                nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, sku, limite_tiempo,
                reloj=reloj,
            )
            stats["neighborhoods_usados"].add(sku)
            # [bug real encontrado probando esto contra BK53: los
            # neighborhoods pueden "resolver" el SKU crítico a costa de
            # perder MÁS cajas de otros SKUs de las que gana -acá se mide
            # por SCORE (que ya compara total primero), no por si el
            # pendiente de este SKU puntual bajó, para decidir si de
            # verdad valió la pena o si además hace falta ejection chain.]
            mejoro = _score_actual() > score_antes_sku
            if not mejoro:
                # [bug real: si esto solo se revertía DENTRO del `if
                # pendientes.get(sku, 0) > 0`, un neighborhood que "resolvía"
                # el SKU (pendiente=0) a costa de perder más cajas de otros
                # nunca se revertía acá NI le daba paso a la ejection chain
                # -el pendiente en 0 hacía parecer que no hacía falta nada
                # más, aunque el score ya hubiera empeorado.]
                _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, snap)
            if pendientes.get(sku, 0) > 0:
                stats["ejection_chains_intentadas"] += 1
                if _buscar_ejection_chain(
                    construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku,
                    nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, sku, limite_tiempo,
                    reloj=reloj,
                ):
                    mejoro = _score_actual() > score_antes_sku
                    if mejoro:
                        stats["ejection_chains_exitosas"] += 1

            score_actual = _score_actual()
            snap_actual = _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes)
            archivo.considerar(score_actual, snap_actual)
            mejor_actual = archivo.mejor()
            if score_actual < mejor_actual[0]:
                _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, mejor_actual[1])
            elif mejoro:
                progreso_en_ronda = True

        if not progreso_en_ronda:
            # [sección 4] Antes de rendirse, probar retomar desde la
            # SEGUNDA mejor solución del archivo Pareto -un punto de
            # partida distinto puede desbloquear un movimiento que el
            # mejor incumbente por sí solo no permitía.
            segundo = archivo.segundo_mejor()
            if segundo is None:
                break
            stats["pareto_alternativas"] += 1
            _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, segundo[1])
            criticos_desde_segundo = _identificar_skus_criticos(pendientes)
            si_hubo_cambio = False
            for sku in sorted(criticos_desde_segundo):
                if reloj() > limite_tiempo:
                    break
                if _intentar_neighborhoods_iterativos(
                    construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku,
                    nivel_por_sku, tope_pallet_por_sku, presupuesto, n_pallets, sku, limite_tiempo,
                    reloj=reloj,
                ):
                    si_hubo_cambio = True
            score_actual = _score_actual()
            archivo.considerar(score_actual, _snapshot_estado_pallets(construcciones, colocados_por_pallet, pendientes))
            if not si_hubo_cambio:
                break

    mejor = archivo.mejor()
    _restaurar_estado_pallets(construcciones, colocados_por_pallet, pendientes, mejor[1])
    mejor_total = mejor[0][0]

    pallets_final = [pc.pallet for pc in construcciones]
    sin_colocar_final = {sku: cant for sku, cant in pendientes.items() if cant > 0}

    stats["neighborhoods_usados"] = sorted(stats["neighborhoods_usados"])
    stats["mejor_mejora"] = mejor_total - total_inicial
    stats["colocadas"] = mejor_total
    stats["pareto_alternativas_en_archivo"] = len(archivo.items)
    stats["tiempo_segundos"] = round(time.time() - t0_wall, 3)

    return pallets_final, sin_colocar_final, stats
