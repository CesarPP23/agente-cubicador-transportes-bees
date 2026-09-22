"""[EXPERIMENTO V6.09-S1] Harness de diagnóstico -corrida completa de
Global Rescue con multi-start real (3 reinicios, presupuesto de 180s
COMPARTIDO entre los tres, igual que producción) pero con un beam DISTINTO
por estrategia: footprint=32, altura_critica=64, demanda=128 (en vez de la
regla productiva fija "32 en el primero, 64 en el resto").

NO modifica ninguna constante productiva ni ninguna función interna: hace
monkeypatch de `gr.global_rescue` a una copia LITERAL de su cuerpo (misma
`_reconstruir_demanda_total`, `_crear_estado_inicial`, `_beam_search` SIN
modificar, mismo cierre de pallets/errores/stats) -el único cambio es qué
`beam_width` se le pasa a `_beam_search` en cada uno de los 3 reinicios.
V6.09 Critical Lookahead, TOP_K, Zero-Only Structural, score, MRV, batch,
poda y transposition quedan exactamente como están en producción (se
llega a todos ellos vía las funciones de `gr` sin tocar)."""
import json
import sys
import time

sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees")
sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees/tests")

import src.global_rescue as gr  # noqa: E402
from fixtures.multicd_validation import cargar_dataset  # noqa: E402
from src.packing_bloques import armar_pallets_bloques  # noqa: E402
from src.validacion_multicd import preparar_demanda_por_cd  # noqa: E402
from src.validacion_v5 import validar_pallet_v5  # noqa: E402

BEAM_POR_ESTRATEGIA = {"footprint": 32, "altura_critica": 64, "demanda": 128}


def _global_rescue_beam_por_estrategia(
    pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    n_pallets, cd, presupuesto, deadline=None, contador=None, oracle_sampler=None,
):
    """Copia literal de `gr.global_rescue` -única diferencia: `beam_width`
    se lee de `BEAM_POR_ESTRATEGIA[estrategia]` en vez de la regla fija
    `GLOBAL_BEAM_WIDTH` (intento 0) / `GLOBAL_BEAM_WIDTH_HARD` (resto)."""
    t0 = time.time()
    limite_tiempo = t0 + gr.GLOBAL_RESCUE_TIME_SECONDS
    if deadline is not None:
        limite_tiempo = min(limite_tiempo, deadline)

    stats: dict = {
        "activado": True, "cd": cd, "beam_width": gr.GLOBAL_BEAM_WIDTH,
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
        "critical_lookahead_calls": 0, "precedence_constraints_detected": 0, "victims_considered": 0,
        "victim_first_children_generated": 0, "victim_first_children_viable": 0, "critical_lookahead_events": [],
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
        return [], stats["faltantes"], stats

    mejor_global: "gr._EstadoGlobal | None" = None
    mejor_score_global = None
    motivo_stop_global = "timeout"

    for intento, estrategia in enumerate(gr.GLOBAL_MULTI_START_ESTRATEGIAS[:gr.GLOBAL_MULTI_START_MAX]):
        if intento > 0 and time.time() > limite_tiempo:
            break
        beam_width = BEAM_POR_ESTRATEGIA[estrategia]
        estado_inicial = gr._crear_estado_inicial(n_pallets, cd, contador, demanda_total)
        t_reinicio = time.time()
        resultado, motivo_stop = gr._beam_search(
            estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
            presupuesto, limite_tiempo, beam_width, estrategia, stats, oracle_sampler,
        )
        tiempo_reinicio = time.time() - t_reinicio
        score = gr._score_estado(
            resultado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, presupuesto,
        )
        depth_log_este = (stats.get("depth_log_por_reinicio") or [[]])[-1]
        max_depth_este = depth_log_este[-1]["depth"] if depth_log_este else 0
        stats["reinicios"].append({
            "estrategia": estrategia, "beam_width": beam_width,
            "colocado": resultado.cajas_colocadas, "motivo_stop": motivo_stop,
            "tiempo_reinicio_s": round(tiempo_reinicio, 3), "max_depth": max_depth_este,
        })
        if mejor_score_global is None or score > mejor_score_global:
            mejor_score_global = score
            mejor_global = resultado
            motivo_stop_global = motivo_stop
        if motivo_stop == "completo":
            break

    assert mejor_global is not None

    pallets_final = [pc.pallet for pc in mejor_global.construcciones]
    sin_colocar_final = {sku: cantidad for sku, cantidad in mejor_global.pendientes.items() if cantidad > 0}

    errores_geometricos: list[str] = []
    for pallet in pallets_final:
        errores_geometricos.extend(validar_pallet_v5(pallet))

    stats["tiempo_s"] = round(time.time() - t0, 3)
    stats["mejor_colocado"] = mejor_global.cajas_colocadas
    stats["faltantes"] = dict(sin_colocar_final)
    stats["motivo_stop"] = motivo_stop_global
    stats["errores_geometricos"] = len(errores_geometricos)
    if errores_geometricos:
        stats["errores_geometricos_detalle"] = errores_geometricos

    return pallets_final, sin_colocar_final, stats


if __name__ == "__main__":
    envios, maestro, uma, pobj = cargar_dataset()
    df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
    df_bk52 = df_clasificado[df_clasificado["CD"] == "BK52"]

    original_global_rescue = gr.global_rescue
    try:
        gr.global_rescue = _global_rescue_beam_por_estrategia
        t0 = time.time()
        pallets = armar_pallets_bloques(df_bk52, "BK52", pallets_objetivo=pobj["BK52"], paralelo_lns=True)
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
    eventos = gr_stats.get("critical_lookahead_events") or []
    evento_22351_22353 = next(
        (e for e in eventos if {"22351", "22353"} <= {e.get("selected_sku"), e.get("victim_sku")}), None,
    )

    resultado = {
        "pipeline_cajas_final": cajas_final,
        "pipeline_sin_colocar_final": sin_colocar_final,
        "pipeline_errores_validacion": errores,
        "pipeline_pallets_final": len(pallets),
        "pipeline_altura_por_pallet": [p.altura_final for p in pallets],
        "tiempo_pipeline_total_s": round(tiempo_total, 3),
        "reinicios": gr_stats.get("reinicios"),
        "global_resultado": gr_stats.get("mejor_colocado"),
        "global_faltantes": gr_stats.get("faltantes"),
        "global_tiempo_s": gr_stats.get("tiempo_s"),
        "global_motivo_stop": gr_stats.get("motivo_stop"),
        "global_errores_geometricos": gr_stats.get("errores_geometricos"),
        "lookahead_calls": gr_stats.get("critical_lookahead_calls"),
        "lookahead_precedence_constraints": gr_stats.get("precedence_constraints_detected"),
        "lookahead_victim_first_children": gr_stats.get("victim_first_children_generated"),
        "lookahead_victim_first_viable": gr_stats.get("victim_first_children_viable"),
        "evento_22351_22353": evento_22351_22353,
        "n_eventos_totales": len(eventos),
        "structural_time_seconds": gr_stats.get("structural_time_seconds"),
        "estados_generados": gr_stats.get("estados_generados"),
        "estados_pruned_no_moves": gr_stats.get("estados_pruned_no_moves"),
        "transposition_hits": gr_stats.get("transposition_hits"),
        "max_frontier": gr_stats.get("max_frontier"),
    }

    out_path = sys.argv[0].rsplit("/", 1)[0] + "/beam_32_64_128_bk52_resultado.json"
    with open(out_path, "w") as f:
        json.dump(resultado, f, indent=2, default=str)
    print(json.dumps(resultado, indent=2, default=str))
