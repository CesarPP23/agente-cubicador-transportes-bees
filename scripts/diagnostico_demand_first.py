"""[EXPERIMENTO V6.10-S2] Demand-First Portfolio -reordena el multi-start
a (demanda, altura_critica, footprint) en vez del orden productivo
(footprint, altura_critica, demanda). Único cambio: el ORDEN de
`GLOBAL_MULTI_START_ESTRATEGIAS` -el beam de cada estrategia ya está
centralizado por NOMBRE (V6.10, `GLOBAL_BEAM_WIDTH_BY_STRATEGY`), así que
reordenar la tupla no requiere tocar ninguna otra lógica: demanda sigue
usando beam=128, altura_critica 64, footprint 32, estén en el orden que
estén. TOP_K, Critical Lookahead, Zero-Only Structural, score, MRV, batch,
poda, transposition, timeout (180s compartido): sin cambios -se llega a
todos vía las funciones de producción sin tocar.

`global_rescue()` YA se detiene apenas un reinicio llega a "completo"
(`if motivo_stop == "completo": break`), así que si `demanda` (ahora
primero) resuelve el 100%, los otros dos reinicios NUNCA se ejecutan -sin
necesidad de lógica adicional en el harness.

Uso: python scripts/diagnostico_demand_first.py <CD>"""
import json
import sys
import time

sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees")
sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees/tests")

import src.global_rescue as gr  # noqa: E402

gr.GLOBAL_MULTI_START_ESTRATEGIAS = ("demanda", "altura_critica", "footprint")
gr.GLOBAL_MULTI_START_MAX = len(gr.GLOBAL_MULTI_START_ESTRATEGIAS)

from fixtures.multicd_validation import cargar_dataset  # noqa: E402
from src.packing_bloques import armar_pallets_bloques  # noqa: E402
from src.validacion_multicd import preparar_demanda_por_cd  # noqa: E402
from src.validacion_v5 import validar_pallet_v5  # noqa: E402

if __name__ == "__main__":
    cd = sys.argv[1] if len(sys.argv) > 1 else "BK53"

    envios, maestro, uma, pobj = cargar_dataset()
    df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
    df_cd = df_clasificado[df_clasificado["CD"] == cd]

    t0 = time.time()
    pallets = armar_pallets_bloques(df_cd, cd, pallets_objetivo=pobj[cd], paralelo_lns=True)
    tiempo_total = time.time() - t0

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
    depth_logs = gr_stats.get("depth_log_por_reinicio") or []
    max_depth_por_reinicio = [
        (dl[-1]["depth"] if dl else None) for dl in depth_logs
    ]

    resultado = {
        "cd": cd,
        "orden_estrategias": list(gr.GLOBAL_MULTI_START_ESTRATEGIAS),
        "tiempo_total_pipeline_s": round(tiempo_total, 3),
        "pipeline_cajas_final": cajas_final,
        "pipeline_sin_colocar_final": sin_colocar_final,
        "pipeline_errores_validacion": errores,
        "pipeline_pallets_final": len(pallets),
        "pipeline_altura_por_pallet": [p.altura_final for p in pallets],
        "reinicios": gr_stats.get("reinicios"),
        "max_depth_por_reinicio": max_depth_por_reinicio,
        "global_resultado": gr_stats.get("mejor_colocado"),
        "global_faltantes": gr_stats.get("faltantes"),
        "global_tiempo_s": gr_stats.get("tiempo_s"),
        "global_motivo_stop": gr_stats.get("motivo_stop"),
        "global_errores_geometricos": gr_stats.get("errores_geometricos"),
        "estados_generados": gr_stats.get("estados_generados"),
        "estados_pruned_no_moves": gr_stats.get("estados_pruned_no_moves"),
        "transposition_hits": gr_stats.get("transposition_hits"),
        "structural_time_seconds": gr_stats.get("structural_time_seconds"),
        "lookahead_calls": gr_stats.get("critical_lookahead_calls"),
        "precedence_constraints_detected": gr_stats.get("precedence_constraints_detected"),
        "victim_first_children_generated": gr_stats.get("victim_first_children_generated"),
        "victim_first_children_viable": gr_stats.get("victim_first_children_viable"),
    }

    out_path = sys.argv[0].rsplit("/", 1)[0] + f"/demand_first_{cd.lower()}_resultado.json"
    with open(out_path, "w") as f:
        json.dump(resultado, f, indent=2, default=str)
    print(json.dumps(resultado, indent=2, default=str))
