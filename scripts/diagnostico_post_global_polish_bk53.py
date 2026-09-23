"""[EXPERIMENTO V6.10-S1] Post-Global Polish -BK53. Verifica si el layout
que Global Rescue produce (207/208, falta 22949) es más reparable con las
capas locales EXISTENTES (Repair V6.04, Exact Local Repair) que el
incumbent pre-global (207/208, falta 22787) que el pipeline conserva hoy
-aunque ambos empaten en cantidad y el gate actual (`score_global >
score_pre_global`) rechace a Global por no superarlo ESTRICTAMENTE.

NO modifica producción: monkeypatchea `gr.global_rescue` a un wrapper que
llama a la función REAL sin cambiar nada de su comportamiento -solo
observa y guarda (deepcopy) sus argumentos de entrada (el incumbent tal
como llega a Global Rescue) y su resultado (el layout Global, antes de que
`packing_bloques.py` lo compare y probablemente lo descarte). El pipeline
productivo sigue exactamente su curso normal -la captura es un efecto
secundario de solo lectura, nunca cambia qué devuelve `global_rescue`.

Repair V6.04 (`repair_solver`) y Exact Local Repair
(`exact_repair_orquestado`) se aplican DESPUÉS, sobre una copia
independiente del layout Global -mismos parámetros/límites que usa
`packing_bloques.py` en producción (mismo `RESCUE_TIME_MAX_SECONDS` de
repair_solver.py, mismo `EXACT_REPAIR_TIME_MAX_SECONDS` de
exact_repair.py, mismo criterio de aceptación `_score_solucion`), pero con
presupuestos de reloj FRESCOS para este experimento aislado -nunca se
tocan constantes ni se inventa un generador/heurística nueva."""
import copy
import json
import sys
import time

sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees")
sys.path.insert(0, "/Users/omaravalosr/Documents/Agent Cubicador/agente-cubicador-transportes-bees/tests")

import src.diagnostico_no_colocadas as diagnostico_no_colocadas  # noqa: E402
import src.global_rescue as gr  # noqa: E402
from fixtures.multicd_validation import cargar_dataset  # noqa: E402
from src.packing_bloques import _capacidad_instalada, armar_pallets_bloques  # noqa: E402
from src.rescue_solver import _contar_candidatos_factibles, _score_solucion, skus_completos  # noqa: E402
from src.validacion_multicd import preparar_demanda_por_cd  # noqa: E402
from src.validacion_v5 import validar_pallet_v5  # noqa: E402

CAPTURED: dict = {}


def _global_rescue_capturando(
    pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    n_pallets, cd, presupuesto, deadline=None, contador=None, oracle_sampler=None,
):
    """[sección 2] Envoltorio de solo lectura -llama a la función REAL sin
    ningún cambio de comportamiento; guarda (deepcopy) el incumbent tal
    como llega y el layout Global tal como sale, ANTES de que el pipeline
    lo compare y probablemente lo descarte."""
    CAPTURED["incumbent_pallets"] = copy.deepcopy(pallets)
    CAPTURED["incumbent_sin_colocar"] = dict(sin_colocar)
    CAPTURED["por_sku"] = por_sku
    CAPTURED["capacidad_cama_por_sku"] = capacidad_cama_por_sku
    CAPTURED["nivel_por_sku"] = nivel_por_sku
    CAPTURED["tope_pallet_por_sku"] = tope_pallet_por_sku
    CAPTURED["n_pallets"] = n_pallets
    CAPTURED["cd"] = cd
    CAPTURED["presupuesto"] = presupuesto

    pallets_global, sin_colocar_global, stats_global = gr.global_rescue.__wrapped_original__(
        pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        n_pallets, cd, presupuesto, deadline=deadline, contador=contador, oracle_sampler=oracle_sampler,
    )
    CAPTURED["global_pallets"] = copy.deepcopy(pallets_global)
    CAPTURED["global_sin_colocar"] = dict(sin_colocar_global)
    CAPTURED["global_stats"] = {k: v for k, v in stats_global.items() if k != "critical_lookahead_events"}
    return pallets_global, sin_colocar_global, stats_global


def _diagnostico_sku(pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
                      presupuesto, sku):
    """[sección 5] candidate_count / motivos (NO_FREE_RECT_FIT, HEIGHT_
    LIMIT, ...) / capacidad instalada para UN SKU faltante, sobre UN
    layout concreto -reusa `diagnostico_no_colocadas.diagnosticar` (ya
    arreglado en V6.09) y `_capacidad_instalada`, ambos de solo lectura."""
    from src.packing_columnar import _reconstruir_en_construccion

    diag = diagnostico_no_colocadas.diagnosticar(
        pallets, {sku: sin_colocar.get(sku, 0)}, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    )
    construcciones = [_reconstruir_en_construccion(p) for p in pallets]
    candidate_count = _contar_candidatos_factibles(
        construcciones, [{} for _ in pallets], sku, por_sku, capacidad_cama_por_sku, nivel_por_sku,
        tope_pallet_por_sku, max_count=4,
    )
    capacidad_residual = sum(_capacidad_instalada(p, sku, presupuesto) for p in pallets)
    return {
        "candidate_count": candidate_count,
        "motivos": diag.get(sku, {}),
        "capacidad_instalada": capacidad_residual,
    }


def _correr_repair(pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
                    n_pallets, presupuesto, demanda_total):
    from src.repair_solver import RESCUE_TIME_MAX_SECONDS as REPAIR_TIME_MAX_SECONDS
    from src.repair_solver import repair_solver

    pallets_copia = copy.deepcopy(pallets)
    sin_colocar_copia = dict(sin_colocar)
    pendientes_pre = {**{sku: 0 for sku in por_sku}, **sin_colocar_copia}
    skus_protegidos = skus_completos(pendientes_pre, por_sku)
    total_pre = demanda_total - sum(sin_colocar_copia.values())
    score_pre = _score_solucion(total_pre, pendientes_pre, por_sku, pallets_copia, skus_protegidos)

    t0 = time.time()
    deadline = t0 + REPAIR_TIME_MAX_SECONDS
    pallets_repair, sin_colocar_repair, stats_repair = repair_solver(
        pallets_copia, sin_colocar_copia, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        n_pallets, presupuesto, skus_protegidos, deadline=deadline,
    )
    tiempo = time.time() - t0
    total_repair = demanda_total - sum(sin_colocar_repair.values())
    pendientes_repair = {**{sku: 0 for sku in por_sku}, **sin_colocar_repair}
    score_repair = _score_solucion(total_repair, pendientes_repair, por_sku, pallets_repair, skus_protegidos)
    mejora = score_repair > score_pre
    pallets_final = pallets_repair if mejora else pallets_copia
    sin_colocar_final = sin_colocar_repair if mejora else sin_colocar_copia
    errores = []
    for p in pallets_final:
        errores += validar_pallet_v5(p)
    return {
        "cajas_antes": total_pre, "cajas_despues": total_repair if mejora else total_pre,
        "faltantes_antes": dict(sin_colocar_copia), "faltantes_despues": dict(sin_colocar_final),
        "mejoro": mejora, "tiempo_s": round(tiempo, 3), "errores": errores, "stats_repair": stats_repair,
    }, pallets_final, sin_colocar_final


def _correr_exact(pallets, sin_colocar, por_sku, tope_pallet_por_sku, presupuesto, demanda_total):
    from src.exact_repair import EXACT_REPAIR_TIME_MAX_SECONDS, exact_repair_orquestado

    pallets_final = copy.deepcopy(pallets)
    sin_colocar_final = dict(sin_colocar)
    pendientes_pre = {**{sku: 0 for sku in por_sku}, **sin_colocar_final}
    skus_protegidos = skus_completos(pendientes_pre, por_sku)

    t0 = time.time()
    deadline = t0 + EXACT_REPAIR_TIME_MAX_SECONDS * 3
    stats_total = {"activado": True, "intentos": 0, "exitos": 0, "cajas_recuperadas": 0}
    for idx in range(len(pallets_final)):
        if not sin_colocar_final or time.time() > deadline:
            break
        total_pre_exact = demanda_total - sum(sin_colocar_final.values())
        pendientes_pre_exact = {**{sku: 0 for sku in por_sku}, **sin_colocar_final}
        score_pre_exact = _score_solucion(total_pre_exact, pendientes_pre_exact, por_sku, pallets_final, skus_protegidos)
        pallet_exact, sin_colocar_exact, stats_exact = exact_repair_orquestado(
            pallets_final[idx], por_sku, sin_colocar_final, tope_pallet_por_sku, presupuesto, deadline=deadline,
        )
        total_exact = total_pre_exact + stats_exact.get("cajas_recuperadas", 0)
        pallets_intento = list(pallets_final)
        pallets_intento[idx] = pallet_exact
        score_exact = _score_solucion(
            total_exact, {**{sku: 0 for sku in por_sku}, **sin_colocar_exact}, por_sku, pallets_intento, skus_protegidos,
        )
        stats_total["intentos"] += stats_exact.get("intentos", 0)
        stats_total["exitos"] += stats_exact.get("exitos", 0)
        stats_total["cajas_recuperadas"] += stats_exact.get("cajas_recuperadas", 0)
        if score_exact > score_pre_exact:
            pallets_final = pallets_intento
            sin_colocar_final = sin_colocar_exact
    tiempo = time.time() - t0
    total_final = demanda_total - sum(sin_colocar_final.values())
    errores = []
    for p in pallets_final:
        errores += validar_pallet_v5(p)
    return {
        "cajas_despues": total_final, "faltantes_despues": dict(sin_colocar_final),
        "tiempo_s": round(tiempo, 3), "errores": errores, "stats_exact": stats_total,
    }, pallets_final, sin_colocar_final


if __name__ == "__main__":
    envios, maestro, uma, pobj = cargar_dataset()
    df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
    df_bk53 = df_clasificado[df_clasificado["CD"] == "BK53"]

    original = gr.global_rescue
    gr.global_rescue = _global_rescue_capturando
    gr.global_rescue.__wrapped_original__ = original
    try:
        armar_pallets_bloques(df_bk53, "BK53", pallets_objetivo=pobj["BK53"], paralelo_lns=True)
    finally:
        gr.global_rescue = original

    por_sku = CAPTURED["por_sku"]
    capacidad_cama_por_sku = CAPTURED["capacidad_cama_por_sku"]
    nivel_por_sku = CAPTURED["nivel_por_sku"]
    tope_pallet_por_sku = CAPTURED["tope_pallet_por_sku"]
    presupuesto = CAPTURED["presupuesto"]
    n_pallets = CAPTURED["n_pallets"]

    demanda_total_dict = gr._reconstruir_demanda_total(
        CAPTURED["incumbent_pallets"], CAPTURED["incumbent_sin_colocar"], por_sku,
    )
    demanda_total = sum(demanda_total_dict.values())

    # --- sección 2: verificación de la captura ---
    global_pallets = CAPTURED["global_pallets"]
    global_sin_colocar = CAPTURED["global_sin_colocar"]
    global_cajas = sum(t.cantidad for p in global_pallets for t in p.torres)
    global_errores = []
    for p in global_pallets:
        global_errores += validar_pallet_v5(p)

    reproduce_esperado = (
        global_cajas == 207 and len(global_pallets) == 2
        and global_sin_colocar == {"22949": 1} and global_errores == []
    )

    reporte: dict = {
        "captura_reproduce_lo_esperado": reproduce_esperado,
        "global_capturado": {
            "cajas": global_cajas, "pallets": len(global_pallets), "faltante": global_sin_colocar,
            "errores": global_errores,
        },
        "incumbent_capturado": {
            "cajas": sum(t.cantidad for p in CAPTURED["incumbent_pallets"] for t in p.torres),
            "faltante": CAPTURED["incumbent_sin_colocar"],
        },
    }

    if not reproduce_esperado:
        out_path = sys.argv[0].rsplit("/", 1)[0] + "/post_global_polish_bk53_resultado.json"
        with open(out_path, "w") as f:
            json.dump(reporte, f, indent=2, default=str)
        print(json.dumps(reporte, indent=2, default=str))
        print("--- LA CAPTURA NO REPRODUJO LO ESPERADO -DETENIENDO, per sección 2 ---", file=sys.stderr)
        sys.exit(1)

    # --- diagnóstico de cada faltante ANTES de reparar ---
    reporte["diagnostico_22787_en_incumbent"] = _diagnostico_sku(
        CAPTURED["incumbent_pallets"], CAPTURED["incumbent_sin_colocar"], por_sku, capacidad_cama_por_sku,
        nivel_por_sku, tope_pallet_por_sku, presupuesto, "22787",
    )
    reporte["diagnostico_22949_en_global"] = _diagnostico_sku(
        global_pallets, global_sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, "22949",
    )

    # --- Contrafactual A: Repair V6.04 sobre copia del layout Global ---
    resultado_repair, pallets_post_repair, sin_colocar_post_repair = _correr_repair(
        global_pallets, global_sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        n_pallets, presupuesto, demanda_total,
    )
    reporte["post_global_repair"] = resultado_repair

    llego_208 = resultado_repair["cajas_despues"] >= demanda_total
    reporte["post_global_exact"] = {"ejecutado": False}

    if not llego_208:
        # --- Contrafactual B: Exact Local Repair sobre el mejor de A ---
        resultado_exact, pallets_post_exact, sin_colocar_post_exact = _correr_exact(
            pallets_post_repair, sin_colocar_post_repair, por_sku, tope_pallet_por_sku, presupuesto, demanda_total,
        )
        reporte["post_global_exact"] = {"ejecutado": True, **resultado_exact}
        llego_208 = resultado_exact["cajas_despues"] >= demanda_total

    reporte["demanda_total"] = demanda_total
    reporte["208_alcanzado"] = llego_208

    out_path = sys.argv[0].rsplit("/", 1)[0] + "/post_global_polish_bk53_resultado.json"
    with open(out_path, "w") as f:
        json.dump(reporte, f, indent=2, default=str)
    print(json.dumps(reporte, indent=2, default=str))
