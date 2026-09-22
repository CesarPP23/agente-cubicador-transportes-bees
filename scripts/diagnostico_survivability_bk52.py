"""[EXPERIMENTO V6.08-S2] Survivability Audit -BK52, beam=128, estrategia
"demanda" única. Distingue Beam Selection (A) de Candidate Branching/MRV/
TOP_K (B) para los SKUs críticos 22353 y 23510 (los 2 que quedan sin
colocar en el resultado de referencia beam=128 de S1: Global=112/114).

NO toca `src/global_rescue.py` (más allá del fix real, independiente, de
`src/diagnostico_no_colocadas.py`, aplicado por separado). Monkeypatch en
memoria de `gr.global_rescue` -reemplazado por `_global_rescue_auditado`,
que reconstruye el MISMO flujo (reconstrucción de demanda, estado inicial,
UN reinicio "demanda" a beam=128, mismo cierre de pallets/errores) pero con
un beam-search propio (`_beam_search_survivability`) que es una copia
LITERAL del cuerpo de `gr._beam_search` -mismas llamadas a `_expandir_
estado`/`_evaluar_viabilidad`/`_score_estado`/`_clave_estado`, mismo orden,
mismos criterios de poda/score/transposition/batch- con UN único agregado:
justo antes y después del corte `vivos[:beam_width]` (el punto exacto
donde production selecciona el frontier), audita la supervivencia conjunta
de 22353/23510 usando las MISMAS funciones híbridas de conteo que ya usa
production (`_contar_candidatos_y_registrar`, `_contar_candidatos_
factibles`), en llamadas de solo lectura adicionales (`stats=None`, cache
descartable) que no mutan ningún stat real ni ninguna decisión de control.

Restaura `gr.global_rescue` al original al salir (por más que el proceso
termine igual, por prolijidad)."""
import json
import sys
import time

sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees")
sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees/tests")

import src.global_rescue as gr  # noqa: E402
from fixtures.multicd_validation import cargar_dataset  # noqa: E402
from models import PalletV5  # noqa: E402
from src.packing_bloques import _capacidad_instalada, armar_pallets_bloques  # noqa: E402
from src.validacion_multicd import preparar_demanda_por_cd  # noqa: E402
from src.validacion_v5 import validar_pallet_v5  # noqa: E402

CRITICAL_SKUS = ("22353", "23510")
BEAM_WIDTH = 128
ESTRATEGIA = "demanda"
MAX_PRUNE_SAMPLES = 5


def _candidatos_hibridos(estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto):
    """Mismo conteo HÍBRIDO (MaxRects + Zero Rescue si aplica) que usan
    MRV/score en producción -`stats=None`/`cache_estructural=None` ->
    lectura pura, no incrementa ningún contador real, cache descartable de
    un solo uso (mismo default documentado en `_contar_candidatos_y_
    registrar`)."""
    return gr._contar_candidatos_y_registrar(
        estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        None, max_count=4, presupuesto=presupuesto, cache_estructural=None,
    )


def _candidatos_maxrects(estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku):
    """Conteo MaxRects PURO (sin Zero Rescue) -para clasificar la fuente
    del candidato (sección 8 del experimento)."""
    return gr._contar_candidatos_factibles(
        estado.construcciones, estado.colocados_por_pallet, sku, por_sku,
        capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, max_count=4,
    )


def _auditar_estados(vivos, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto):
    """UNA pasada sobre `vivos` (score, hijo) -devuelve, por estado, los
    conteos híbrido/MaxRects de cada SKU crítico y si preserva cada uno /
    ambos. Se computa UNA sola vez y se reusa tanto para el agregado
    pre-beam (todo `vivos`) como post-beam (el subconjunto que sobrevive al
    corte, filtrado por identidad) -nunca se mide el mismo estado dos
    veces."""
    auditados = []
    for score, hijo in vivos:
        info = {}
        for sku in CRITICAL_SKUS:
            pendiente = hijo.pendientes.get(sku, 0)
            if pendiente <= 0:
                info[sku] = {"pendiente": 0, "hibrido": None, "maxrects": None, "preserva": True}
                continue
            hib = _candidatos_hibridos(
                hijo, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto,
            )
            mr = _candidatos_maxrects(hijo, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku)
            info[sku] = {"pendiente": pendiente, "hibrido": hib, "maxrects": mr, "preserva": hib > 0}
        info["ambos"] = all(info[sku]["preserva"] for sku in CRITICAL_SKUS)
        auditados.append((score, hijo, info))
    return auditados


def _agregar(auditados_subset):
    agg = {sku: {"con_candidato": 0, "sin_candidato": 0, "max_count": 0, "con_maxrects": 0} for sku in CRITICAL_SKUS}
    both = 0
    pendientes_both = {sku: [] for sku in CRITICAL_SKUS}
    for _score, _hijo, info in auditados_subset:
        for sku in CRITICAL_SKUS:
            d = info[sku]
            if d["hibrido"] is None:
                continue  # SKU ya completo en este estado -no aplica a los buckets con/sin candidato
            if d["preserva"]:
                agg[sku]["con_candidato"] += 1
            else:
                agg[sku]["sin_candidato"] += 1
            agg[sku]["max_count"] = max(agg[sku]["max_count"], d["hibrido"])
            if d["maxrects"] and d["maxrects"] > 0:
                agg[sku]["con_maxrects"] += 1
        if info["ambos"]:
            both += 1
            for sku in CRITICAL_SKUS:
                pendientes_both[sku].append(info[sku]["pendiente"])
    return agg, both, pendientes_both


def _beam_search_survivability(
    estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    presupuesto, limite_tiempo, beam_width, estrategia, stats, audit,
):
    """Copia literal del cuerpo de `gr._beam_search` (mismas funciones,
    mismo orden, misma poda/score/transposition/batch) con el agregado de
    auditoría de supervivencia justo antes/después del corte `vivos[:
    beam_width]`. Ver docstring del módulo."""
    visited: dict[tuple, tuple] = {}
    frontera = [estado_inicial]
    mejor_estado = estado_inicial
    mejor_score = gr._score_estado(
        estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, presupuesto,
    )
    motivo_stop = "timeout"
    profundidad = 0

    while True:
        stats["_depth_actual"] = profundidad
        frontier_in = len(frontera)

        if time.time() > limite_tiempo:
            motivo_stop = "timeout"
            break
        if all(sum(c for c in e.pendientes.values() if c > 0) == 0 for e in frontera):
            motivo_stop = "completo"
            break

        candidatos_hijos: list = []
        algun_expandido = False
        for estado in frontera:
            if sum(c for c in estado.pendientes.values() if c > 0) == 0:
                candidatos_hijos.append(estado)
                continue
            hijos = gr._expandir_estado(
                estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, estrategia, stats,
                presupuesto,
            )
            stats["estados_generados"] += len(hijos)
            if not hijos:
                candidatos_hijos.append(estado)
                continue
            algun_expandido = True
            candidatos_hijos.extend(hijos)

        vivos: list[tuple[tuple, "gr._EstadoGlobal"]] = []
        for hijo in candidatos_hijos:
            cache_hijo = gr.CacheEstructural() if presupuesto is not None else None
            muerto, sku_causante = gr._evaluar_viabilidad(
                hijo, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto, stats,
                None, cache_hijo,
            )
            score_hijo = gr._score_estado(
                hijo, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, presupuesto,
                cache_hijo,
            )
            clave = gr._clave_estado(hijo)
            si_dominado = False
            if clave in visited:
                stats["duplicados"] += 1
                stats["transposition_hits"] += 1
                if score_hijo <= visited[clave]:
                    si_dominado = True
            if not si_dominado and len(visited) < gr.GLOBAL_VISITED_MAX:
                visited[clave] = score_hijo

            if not si_dominado and score_hijo > mejor_score:
                mejor_score = score_hijo
                mejor_estado = hijo

            if muerto:
                stats["estados_pruned_no_moves"] += 1
                if sku_causante is not None and sku_causante in CRITICAL_SKUS:
                    audit["pruned_by_sku"][sku_causante] += 1
                    if audit["first_prune_depth"][sku_causante] is None:
                        audit["first_prune_depth"][sku_causante] = profundidad
                    if len(audit["prune_samples"][sku_causante]) < MAX_PRUNE_SAMPLES:
                        # [sección 9] MaxRects=0 Y Structural=0 por construcción -es
                        # exactamente la condición que `_evaluar_viabilidad` ya
                        # verificó para llegar acá (candidatos<=0 -sección 3),
                        # así que no hace falta re-consultar Structural.
                        capacidad_residual = sum(
                            _capacidad_instalada(pc.pallet, sku_causante, presupuesto) for pc in hijo.construcciones
                        )
                        audit["prune_samples"][sku_causante].append({
                            "depth": profundidad, "cajas_colocadas": hijo.cajas_colocadas,
                            "pendiente_sku": hijo.pendientes.get(sku_causante, 0),
                            "maxrects_candidates": 0, "structural_candidates": 0,
                            "capacidad_instalada": capacidad_residual,
                        })
                continue
            if si_dominado:
                continue
            vivos.append((score_hijo, hijo))

        # [AUDIT, sección 3-7] Snapshot PRE-BEAM -sobre TODO `vivos`, antes
        # del sort+corte real.
        auditados = _auditar_estados(
            vivos, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto,
        )
        preservadores = [t for t in auditados if t[2]["ambos"]]
        mejor_preservador = max(preservadores, key=lambda t: t[0], default=None)
        pre_agg, pre_both, pre_pend = _agregar(auditados)
        best_boxes_pre = max((h.cajas_colocadas for _, h, _ in auditados), default=None)

        if not vivos:
            _registrar_depth(
                audit, profundidad, frontier_in, 0, 0, best_boxes_pre, None,
                pre_agg, pre_both, pre_pend, pre_agg, pre_both, pre_pend, None, None, False,
            )
            motivo_stop = "estancado"
            break

        # [sección 7] mismo criterio de "primera pérdida" que el resto del
        # reporte: si ya en el universo PRE-beam no queda ningún
        # preservador conjunto, es pérdida de branching/MRV/poda, no de
        # selección del beam.
        if pre_both == 0 and audit["first_depth_no_pre_beam_both"] is None:
            audit["first_depth_no_pre_beam_both"] = profundidad

        vivos.sort(key=lambda par: par[0], reverse=True)
        frontera = [hijo for _, hijo in vivos[:beam_width]]
        stats["max_frontier"] = max(stats["max_frontier"], len(frontera))
        frontera_ids = {id(h) for h in frontera}
        post_auditados = [t for t in auditados if id(t[1]) in frontera_ids]
        post_agg, post_both, post_pend = _agregar(post_auditados)
        best_boxes_post = max((h.cajas_colocadas for _, h, _ in post_auditados), default=None)

        if post_both == 0 and audit["first_depth_no_post_beam_both"] is None:
            audit["first_depth_no_post_beam_both"] = profundidad

        rank = None
        if mejor_preservador is not None:
            target_id = id(mejor_preservador[1])
            for i, (_, hijo) in enumerate(vivos):
                if id(hijo) == target_id:
                    rank = i + 1
                    break
        did_survive = rank is not None and rank <= beam_width

        # [sección 10] muestra mínima: mejor preservador global, y el
        # primer preservador que el corte del beam efectivamente descarta
        # (rank > beam_width pese a preservar ambos críticos).
        if mejor_preservador is not None:
            score_bp, hijo_bp, _info_bp = mejor_preservador
            if audit["best_preserver_overall"] is None or score_bp > audit["best_preserver_overall"]["score"]:
                audit["best_preserver_overall"] = {
                    "depth": profundidad, "score": score_bp, "cajas_colocadas": hijo_bp.cajas_colocadas,
                    "pendiente_22353": hijo_bp.pendientes.get("22353", 0),
                    "pendiente_23510": hijo_bp.pendientes.get("23510", 0), "rank": rank, "survived": did_survive,
                }
            if not did_survive and audit["first_dropped_preserver"] is None:
                audit["first_dropped_preserver"] = {
                    "depth": profundidad, "score": score_bp, "cajas_colocadas": hijo_bp.cajas_colocadas,
                    "pendiente_22353": hijo_bp.pendientes.get("22353", 0),
                    "pendiente_23510": hijo_bp.pendientes.get("23510", 0), "rank": rank,
                }

        _registrar_depth(
            audit, profundidad, frontier_in, len(vivos), len(frontera), best_boxes_pre, best_boxes_post,
            pre_agg, pre_both, pre_pend, post_agg, post_both, post_pend, rank, did_survive,
            mejor_preservador[0] if mejor_preservador else None,
        )

        profundidad += 1
        if sum(c for c in mejor_estado.pendientes.values() if c > 0) == 0:
            motivo_stop = "completo"
            break
        if not algun_expandido:
            motivo_stop = "estancado"
            break

    return mejor_estado, motivo_stop


def _registrar_depth(
    audit, depth, frontier_in, children_pre, children_post, best_pre, best_post,
    pre_agg, pre_both, pre_pend, post_agg, post_both, post_pend, rank, survived, best_score,
):
    audit["depth_table"].append({
        "depth": depth, "frontier_in": frontier_in,
        "children_pre_beam": children_pre, "children_post_beam": children_post,
        "beam_dropped": children_pre - children_post,
        "best_boxes_pre": best_pre, "best_boxes_post": best_post,
        "pre_both": pre_both, "post_both": post_both, "dropped_both": pre_both - post_both,
        "best_score_among_preservers": list(best_score) if best_score else None,
        "rank_of_best_preserver_before_beam_cut": rank, "did_best_preserver_survive": survived,
        "pendientes_both_min": {sku: (min(pre_pend[sku]) if pre_pend[sku] else None) for sku in CRITICAL_SKUS},
        "pendientes_both_max": {sku: (max(pre_pend[sku]) if pre_pend[sku] else None) for sku in CRITICAL_SKUS},
        "sku_detail": {
            sku: {
                "pre_con_candidato": pre_agg[sku]["con_candidato"], "pre_sin_candidato": pre_agg[sku]["sin_candidato"],
                "pre_max_count": pre_agg[sku]["max_count"], "pre_con_maxrects": pre_agg[sku]["con_maxrects"],
                "post_con_candidato": post_agg[sku]["con_candidato"],
                "post_sin_candidato": post_agg[sku]["sin_candidato"],
                "post_max_count": post_agg[sku]["max_count"], "post_con_maxrects": post_agg[sku]["con_maxrects"],
            } for sku in CRITICAL_SKUS
        },
    })


def _global_rescue_auditado(
    pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    n_pallets, cd, presupuesto, deadline=None, contador=None, oracle_sampler=None,
):
    """Reemplazo de `gr.global_rescue` -mismo contrato de entrada/salida,
    UN solo reinicio ("demanda", beam=128) en vez del multi-start completo,
    usando `_beam_search_survivability` en vez de `gr._beam_search`. TOP_K,
    score, MRV, batch, poda, transposition: sin cambios (se llega a ellos
    exclusivamente vía las funciones de `gr` sin modificar)."""
    t0 = time.time()
    limite_tiempo = t0 + gr.GLOBAL_RESCUE_TIME_SECONDS
    if deadline is not None:
        limite_tiempo = min(limite_tiempo, deadline)

    stats: dict = {
        "activado": True, "cd": cd, "beam_width": BEAM_WIDTH,
        "estados_generados": 0, "estados_pruned_no_moves": 0, "duplicados": 0, "transposition_hits": 0,
        "max_frontier": 0, "max_deferred_skus": 0,
        "raw_candidates_generados": 0, "candidates_retenidos_top_k": 0,
        "reinicios": [], "por_sku": {},
        "structural_exists_calls": 0, "structural_count_calls": 0, "structural_generate_calls": 0,
        "structural_positions_tested": 0,
        "structural_positions_rejected_bounds": 0, "structural_positions_rejected_overlap": 0,
        "structural_positions_rejected_support": 0,
        "structural_early_exit_exists": 0, "structural_early_exit_count": 0,
        "structural_cache_hits": 0, "structural_cache_misses": 0, "structural_time_seconds": 0.0,
        "structural_candidates_valid_before_dedupe": 0, "structural_candidates_unique_new_vs_maxrects": 0,
        "false_zero_maxrects": {},
        "zero_rescue_exists_calls": 0, "zero_rescue_count_calls": 0, "zero_rescue_generate_calls": 0,
        "zero_rescue_successes": 0, "zero_rescue_failures": 0, "zero_rescue_by_sku": {},
        "placements_from_maxrects": 0, "placements_from_structural_zero_rescue": 0,
        "structural_rescues_used": {},
    }
    audit = {
        "depth_table": [], "first_depth_no_pre_beam_both": None, "first_depth_no_post_beam_both": None,
        "pruned_by_sku": {sku: 0 for sku in CRITICAL_SKUS}, "first_prune_depth": {sku: None for sku in CRITICAL_SKUS},
        "prune_samples": {sku: [] for sku in CRITICAL_SKUS},
        "best_preserver_overall": None, "first_dropped_preserver": None,
    }

    demanda_total = gr._reconstruir_demanda_total(pallets, sin_colocar, por_sku)
    if contador is None:
        contador = [0]

    if n_pallets <= 0 or not any(cantidad > 0 for cantidad in demanda_total.values()):
        stats.update({
            "tiempo_s": round(time.time() - t0, 3), "mejor_colocado": 0,
            "faltantes": {sku: cantidad for sku, cantidad in demanda_total.items() if cantidad > 0},
            "motivo_stop": "sin_demanda_o_sin_pallets", "errores_geometricos": 0,
        })
        stats["survivability"] = audit
        return [], stats["faltantes"], stats

    estado_inicial = gr._crear_estado_inicial(n_pallets, cd, contador, demanda_total)
    resultado, motivo_stop = _beam_search_survivability(
        estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, limite_tiempo, BEAM_WIDTH, ESTRATEGIA, stats, audit,
    )
    stats["reinicios"].append({
        "estrategia": ESTRATEGIA, "beam_width": BEAM_WIDTH, "colocado": resultado.cajas_colocadas,
        "motivo_stop": motivo_stop,
    })

    pallets_final = [pc.pallet for pc in resultado.construcciones]
    sin_colocar_final = {sku: cantidad for sku, cantidad in resultado.pendientes.items() if cantidad > 0}

    errores_geometricos: list[str] = []
    for pallet in pallets_final:
        errores_geometricos.extend(validar_pallet_v5(pallet))

    stats["tiempo_s"] = round(time.time() - t0, 3)
    stats["mejor_colocado"] = resultado.cajas_colocadas
    stats["faltantes"] = dict(sin_colocar_final)
    stats["motivo_stop"] = motivo_stop
    stats["errores_geometricos"] = len(errores_geometricos)
    if errores_geometricos:
        stats["errores_geometricos_detalle"] = errores_geometricos
    stats["survivability"] = audit

    return pallets_final, sin_colocar_final, stats


def _cargar_bk52():
    envios, maestro, uma, pobj = cargar_dataset()
    df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
    df_bk52 = df_clasificado[df_clasificado["CD"] == "BK52"]
    return df_bk52, pobj["BK52"]


if __name__ == "__main__":
    df_bk52, pallets_objetivo = _cargar_bk52()
    original_global_rescue = gr.global_rescue
    try:
        gr.global_rescue = _global_rescue_auditado
        t0 = time.time()
        pallets = armar_pallets_bloques(df_bk52, "BK52", pallets_objetivo=pallets_objetivo, paralelo_lns=True)
        tiempo_total = time.time() - t0
    finally:
        gr.global_rescue = original_global_rescue

    cajas_final = sum(t.cantidad for p in pallets for t in p.torres)
    sin_colocar_final: dict[str, int] = {}
    for p in pallets:
        for sku, cant in p.metadata.get("sin_colocar", {}).items():
            sin_colocar_final[sku] = sin_colocar_final.get(sku, 0) + cant
    errores = []
    for p in pallets:
        errores += validar_pallet_v5(p)

    meta = pallets[-1].metadata
    gr_stats = meta.get("global_rescue_stats") or {}
    audit = gr_stats.get("survivability") or {}
    reinicio0 = (gr_stats.get("reinicios") or [{}])[0]

    resultado = {
        "pipeline_cajas_final": cajas_final,
        "pipeline_sin_colocar_final": sin_colocar_final,
        "pipeline_errores_validacion": errores,
        "tiempo_pipeline_total_s": round(tiempo_total, 3),
        "global_resultado": reinicio0.get("colocado"),
        "global_motivo_stop": reinicio0.get("motivo_stop"),
        "global_faltantes": gr_stats.get("faltantes"),
        "global_tiempo_s": gr_stats.get("tiempo_s"),
        "max_depth": (audit.get("depth_table") or [{}])[-1].get("depth") if audit.get("depth_table") else None,
        "survivability": audit,
    }

    out_path = sys.argv[0].rsplit("/", 1)[0] + "/survivability_bk52_resultado.json"
    with open(out_path, "w") as f:
        json.dump(resultado, f, indent=2, default=str)
    print(json.dumps({k: v for k, v in resultado.items() if k != "survivability"}, indent=2, default=str))
    print(f"--- reporte completo (con depth_table) en {out_path} ---")
