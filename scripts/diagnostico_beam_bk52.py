"""[EXPERIMENTO V6.08-S1] Harness de diagnóstico -sensibilidad del beam
width de Global Rescue sobre BK52, estrategia única "demanda".

NO modifica ninguna constante productiva en `src/global_rescue.py`: hace
monkeypatch en memoria de `GLOBAL_BEAM_WIDTH` / `GLOBAL_BEAM_WIDTH_HARD` /
`GLOBAL_MULTI_START_ESTRATEGIAS` / `GLOBAL_MULTI_START_MAX` sobre el
módulo ya importado (el resto del código -TOP_K, score, poda, batch,
transposition, Zero-Only Structural, timeout- permanece exactamente como
está en V6.08) y las restaura al terminar cada experimento. Corre la
tubería completa vía `armar_pallets_bloques` (mismo camino real que usa
el pipeline en producción) para que Global Rescue reciba exactamente los
mismos datos/parámetros que en la corrida BK52 real.

Uso:
    python scripts/diagnostico_beam_bk52.py 64 128 256
"""
import json
import resource
import sys
import time

sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees")
sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees/tests")

import src.global_rescue as gr  # noqa: E402
from fixtures.multicd_validation import cargar_dataset  # noqa: E402
from src.packing_bloques import armar_pallets_bloques  # noqa: E402
from src.validacion_multicd import preparar_demanda_por_cd  # noqa: E402
from src.validacion_v5 import validar_pallet_v5  # noqa: E402

ESTRATEGIA_UNICA = ("demanda",)


def _cargar_bk52():
    envios, maestro, uma, pobj = cargar_dataset()
    df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
    df_bk52 = df_clasificado[df_clasificado["CD"] == "BK52"]
    return df_bk52, pobj["BK52"]


def correr_experimento(beam_width: int, df_bk52, pallets_objetivo: int) -> dict:
    """Un experimento = 1 corrida completa de `armar_pallets_bloques` con
    Global Rescue forzado a un único reinicio ("demanda") al `beam_width`
    dado. Restaura las constantes originales del módulo al salir, incluso
    si la corrida lanza una excepción."""
    orig = {
        "GLOBAL_BEAM_WIDTH": gr.GLOBAL_BEAM_WIDTH,
        "GLOBAL_BEAM_WIDTH_HARD": gr.GLOBAL_BEAM_WIDTH_HARD,
        "GLOBAL_MULTI_START_ESTRATEGIAS": gr.GLOBAL_MULTI_START_ESTRATEGIAS,
        "GLOBAL_MULTI_START_MAX": gr.GLOBAL_MULTI_START_MAX,
    }
    try:
        gr.GLOBAL_BEAM_WIDTH = beam_width
        gr.GLOBAL_BEAM_WIDTH_HARD = beam_width  # sin efecto real (1 solo intento), fijado por consistencia
        gr.GLOBAL_MULTI_START_ESTRATEGIAS = ESTRATEGIA_UNICA
        gr.GLOBAL_MULTI_START_MAX = 1

        rss_antes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        t0 = time.time()
        pallets = armar_pallets_bloques(df_bk52, "BK52", pallets_objetivo=pallets_objetivo, paralelo_lns=True)
        tiempo_total = time.time() - t0
        rss_despues = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    finally:
        gr.GLOBAL_BEAM_WIDTH = orig["GLOBAL_BEAM_WIDTH"]
        gr.GLOBAL_BEAM_WIDTH_HARD = orig["GLOBAL_BEAM_WIDTH_HARD"]
        gr.GLOBAL_MULTI_START_ESTRATEGIAS = orig["GLOBAL_MULTI_START_ESTRATEGIAS"]
        gr.GLOBAL_MULTI_START_MAX = orig["GLOBAL_MULTI_START_MAX"]

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
    depth_logs = gr_stats.get("depth_log_por_reinicio") or [[]]
    depth_log = depth_logs[0] if depth_logs else []

    beam_dropped_total = sum(d.get("beam_dropped", 0) for d in depth_log)
    mejor_colocado_por_depth = [
        {"depth": d["depth"], "cajas_colocadas_best": d["cajas_colocadas_best"]} for d in depth_log
    ]
    max_depth = depth_log[-1]["depth"] if depth_log else 0
    reinicio0 = (gr_stats.get("reinicios") or [{}])[0]

    return {
        "beam_width": beam_width,
        "pipeline_cajas_final": cajas_final,
        "pipeline_sin_colocar_final": sin_colocar_final,
        "pipeline_errores_validacion": errores,
        "tiempo_pipeline_total_s": round(tiempo_total, 3),
        "global_resultado": reinicio0.get("colocado"),
        "global_motivo_stop": reinicio0.get("motivo_stop"),
        "global_faltantes": gr_stats.get("faltantes"),
        "global_faltantes_skus": sorted((gr_stats.get("faltantes") or {}).keys()),
        "global_tiempo_s": gr_stats.get("tiempo_s"),
        "max_depth": max_depth,
        "estados_generados": gr_stats.get("estados_generados"),
        "estados_pruned_no_moves": gr_stats.get("estados_pruned_no_moves"),
        "beam_dropped_total": beam_dropped_total,
        "transposition_hits": gr_stats.get("transposition_hits"),
        "max_frontier": gr_stats.get("max_frontier"),
        "raw_candidates_generados": gr_stats.get("raw_candidates_generados"),
        "candidates_retenidos_top_k": gr_stats.get("candidates_retenidos_top_k"),
        "zero_rescue_exists_calls": gr_stats.get("zero_rescue_exists_calls"),
        "zero_rescue_count_calls": gr_stats.get("zero_rescue_count_calls"),
        "zero_rescue_generate_calls": gr_stats.get("zero_rescue_generate_calls"),
        "zero_rescue_successes": gr_stats.get("zero_rescue_successes"),
        "zero_rescue_failures": gr_stats.get("zero_rescue_failures"),
        "structural_time_seconds": gr_stats.get("structural_time_seconds"),
        "peak_rss_kb_delta": rss_despues - rss_antes,
        "peak_rss_kb_absoluto": rss_despues,
        "mejor_colocado_por_depth": mejor_colocado_por_depth,
    }


if __name__ == "__main__":
    beams = [int(a) for a in sys.argv[1:]] or [64]
    df_bk52, pallets_objetivo = _cargar_bk52()
    resultados = []
    for b in beams:
        print(f"--- corriendo beam_width={b} ---", file=sys.stderr)
        r = correr_experimento(b, df_bk52, pallets_objetivo)
        resultados.append(r)
        print(json.dumps(r, indent=2, default=str), file=sys.stderr)

    out_path = sys.argv[0].rsplit("/", 1)[0] + "/beam_sensitivity_resultado.json"
    with open(out_path, "w") as f:
        json.dump(resultados, f, indent=2, default=str)
    print(json.dumps(resultados, default=str))
