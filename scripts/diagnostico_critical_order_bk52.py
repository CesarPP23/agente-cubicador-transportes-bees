"""[EXPERIMENTO V6.08-S3] Critical Order Counterfactual -BK52, beam=128,
estrategia "demanda". Verifica si la muerte de 22353 en la transición
depth 35->36 (encontrada en S2) es un problema de ORDEN de expansión
(MRV/lookahead, arreglable sin más beam) o de inviabilidad geométrica
genuina.

NO toca `src/global_rescue.py`. Reusa EXACTAMENTE las mismas funciones de
producción (`_expandir_estado`, `_generar_candidatos_multi_pallet_
hibrido`, `_seleccionar_top_k_diverso`, `_generar_batch_sizes`,
`_colocar_candidato_estructural`/`.colocar()`, `_evaluar_viabilidad`,
`_score_estado`, `_clave_estado`, `_ordenar_mrv`) -mismo TOP_K, score,
MRV, batch, poda, transposition, beam=128, Zero-Only Structural V6.08. Lo
único que el harness hace "distinto" es, en los contrafactuales B-E, elegir
qué SKU se expande PRIMERO en un único paso forzado (en vez de dejar que
MRV lo elija) -después de eso, el control vuelve 100% al solver normal
(mismas funciones, mismo beam, mismo timeout fresco de 180s)."""
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

CRITICAL_SKUS = ("22353", "23510")
BEAM_WIDTH = 128
ESTRATEGIA = "demanda"
DEPTH_OBJETIVO = 35
FRESH_TIMEOUT_S = 180.0

CAPTURED: dict = {}


def _stats_base() -> dict:
    """Mismo esqueleto que `global_rescue()` inicializa -varias funciones
    de `gr` indexan estas claves directamente (`+=`), no solo `.get()`."""
    return {
        "activado": True, "estados_generados": 0, "estados_pruned_no_moves": 0, "duplicados": 0,
        "transposition_hits": 0, "max_frontier": 0, "max_deferred_skus": 0,
        "raw_candidates_generados": 0, "candidates_retenidos_top_k": 0, "por_sku": {},
        "structural_exists_calls": 0, "structural_count_calls": 0, "structural_generate_calls": 0,
        "structural_time_seconds": 0.0, "false_zero_maxrects": {},
        "zero_rescue_exists_calls": 0, "zero_rescue_count_calls": 0, "zero_rescue_generate_calls": 0,
        "zero_rescue_successes": 0, "zero_rescue_failures": 0, "zero_rescue_by_sku": {},
        "placements_from_maxrects": 0, "placements_from_structural_zero_rescue": 0, "structural_rescues_used": {},
    }


def _candidatos_hibridos(estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto):
    if estado.pendientes.get(sku, 0) <= 0:
        return None
    return gr._contar_candidatos_y_registrar(
        estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        None, max_count=4, presupuesto=presupuesto, cache_estructural=None,
    )


# ---------------------------------------------------------------------------
# Fase 1 -reproducir la corrida hasta depth 35 y CAPTURAR (sin serializar
# toda la frontera, sección 2).
# ---------------------------------------------------------------------------

def _beam_search_hasta_depth(
    estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    presupuesto, limite_tiempo, beam_width, estrategia, stats, depth_objetivo,
):
    """Copia literal del cuerpo de `gr._beam_search` -se detiene apenas
    termina de construir la frontera de `depth_objetivo` (la misma
    convención de índice que usó S2), sin avanzar más."""
    visited: dict[tuple, tuple] = {}
    frontera = [estado_inicial]
    profundidad = 0
    while True:
        if time.time() > limite_tiempo:
            return frontera, "timeout_antes_de_capturar", profundidad
        if all(sum(c for c in e.pendientes.values() if c > 0) == 0 for e in frontera):
            return frontera, "completo_antes_de_capturar", profundidad

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

        vivos: list = []
        for hijo in candidatos_hijos:
            cache_hijo = gr.CacheEstructural() if presupuesto is not None else None
            muerto, _sku_causante = gr._evaluar_viabilidad(
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
            if muerto:
                stats["estados_pruned_no_moves"] += 1
                continue
            if si_dominado:
                continue
            vivos.append((score_hijo, hijo))

        if not vivos:
            return frontera, "estancado_antes_de_capturar", profundidad

        vivos.sort(key=lambda par: par[0], reverse=True)
        frontera = [hijo for _, hijo in vivos[:beam_width]]
        stats["max_frontier"] = max(stats["max_frontier"], len(frontera))

        if profundidad == depth_objetivo:
            return frontera, "capturado", profundidad
        profundidad += 1
        if not algun_expandido:
            return frontera, "estancado_antes_de_capturar", profundidad


def _global_rescue_capture(
    pallets, sin_colocar, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    n_pallets, cd, presupuesto, deadline=None, contador=None, oracle_sampler=None,
):
    """Monkeypatch target -reproduce la corrida beam=128/demanda hasta
    depth 35 y guarda todo lo necesario para los contrafactuales en
    `CAPTURED`. Devuelve un resultado mínimo válido (no participa del
    incumbent real del pipeline -no nos importa para S3)."""
    t0 = time.time()
    limite_tiempo = t0 + gr.GLOBAL_RESCUE_TIME_SECONDS
    if deadline is not None:
        limite_tiempo = min(limite_tiempo, deadline)
    if contador is None:
        contador = [0]

    stats = _stats_base()
    demanda_total = gr._reconstruir_demanda_total(pallets, sin_colocar, por_sku)
    estado_inicial = gr._crear_estado_inicial(n_pallets, cd, contador, demanda_total)

    frontera_35, motivo, depth_real = _beam_search_hasta_depth(
        estado_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, limite_tiempo, BEAM_WIDTH, ESTRATEGIA, stats, DEPTH_OBJETIVO,
    )

    CAPTURED["frontera_35"] = frontera_35
    CAPTURED["motivo"] = motivo
    CAPTURED["depth_real"] = depth_real
    CAPTURED["por_sku"] = por_sku
    CAPTURED["capacidad_cama_por_sku"] = capacidad_cama_por_sku
    CAPTURED["nivel_por_sku"] = nivel_por_sku
    CAPTURED["tope_pallet_por_sku"] = tope_pallet_por_sku
    CAPTURED["presupuesto"] = presupuesto

    return [], {}, {
        "activado": True, "mejor_colocado": 0, "faltantes": {}, "motivo_stop": "capturado_para_S3",
        "errores_geometricos": 0, "tiempo_s": round(time.time() - t0, 3), "reinicios": [],
    }


# ---------------------------------------------------------------------------
# Fase 2 -sección 3: tabla MRV del estado capturado.
# ---------------------------------------------------------------------------

def _tabla_mrv(estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto):
    pendientes_criticos = [sku for sku, c in estado.pendientes.items() if c > 0]
    orden = gr._ordenar_mrv(
        pendientes_criticos, estado, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        ESTRATEGIA, None, presupuesto, None,
    )
    filas = []
    for rank, sku in enumerate(orden, start=1):
        candidatas = por_sku.get(sku, [])
        candidate_count = _candidatos_hibridos(
            estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto,
        )
        filas.append({
            "sku": sku, "pendiente": estado.pendientes.get(sku, 0), "candidate_count": candidate_count,
            "footprint": gr._footprint_maximo(candidatas), "orientaciones": len({c.orientacion for c in candidatas}),
            "rank_mrv": rank,
        })
    return filas, orden


# ---------------------------------------------------------------------------
# Fase 3 -expansión forzada de un SKU específico (mismas funciones de
# producción, MRV bypaseado SOLO en el harness).
# ---------------------------------------------------------------------------

def _expandir_forzado(estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto):
    cache_estructural = gr.CacheEstructural() if presupuesto is not None else None
    opciones = gr._generar_candidatos_multi_pallet_hibrido(
        estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, None, cache_estructural,
    )
    if not opciones:
        return [], []
    seleccion = gr._seleccionar_top_k_diverso(opciones, gr.GLOBAL_BRANCH_TOP_K)
    hijos, detalles = [], []
    for pidx, idx_libre, x, y, z, cand, max_lote in seleccion:
        for batch in gr._generar_batch_sizes(max_lote):
            hijo = gr._clonar_estado(estado)
            if idx_libre is None:
                torre = gr._colocar_candidato_estructural(hijo.construcciones[pidx], cand, x, y, z, batch)
                fuente = "STRUCTURAL_ZERO_RESCUE"
            else:
                torre = hijo.construcciones[pidx].colocar(cand, batch, idx_libre)
                fuente = "MAXRECTS"
            cantidad_real = torre.cantidad
            if cantidad_real <= 0:
                continue
            hijo.pendientes[sku] = hijo.pendientes.get(sku, 0) - cantidad_real
            hijo.colocados_por_pallet[pidx][sku] = hijo.colocados_por_pallet[pidx].get(sku, 0) + cantidad_real
            hijo.cajas_colocadas += cantidad_real
            hijos.append(hijo)
            detalles.append({
                "sku": sku, "pidx": pidx, "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
                "orientacion": cand.orientacion, "batch": batch, "cantidad_real": cantidad_real, "fuente": fuente,
            })
    return hijos, detalles


def _torre_nueva(estado_padre, hijo):
    for pidx in range(len(estado_padre.construcciones)):
        antes = len(estado_padre.construcciones[pidx].pallet.torres)
        despues = hijo.construcciones[pidx].pallet.torres
        if len(despues) > antes:
            t = despues[-1]
            return {"pidx": pidx, "sku": t.sku, "x": t.x, "y": t.y, "z": t.z, "orientacion": t.orientacion, "cantidad": t.cantidad}
    return None


# ---------------------------------------------------------------------------
# Fase 4 -reanudar el solver normal desde una frontera dada (mismo cuerpo
# de `gr._beam_search`, generalizado a una frontera inicial, timeout fresco
# independiente).
# ---------------------------------------------------------------------------

def _beam_search_desde_frontera(
    frontera_inicial, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
    presupuesto, limite_tiempo, beam_width, estrategia, stats,
):
    if not frontera_inicial:
        return None, "sin_hijos_forzados"
    visited: dict[tuple, tuple] = {}
    frontera = list(frontera_inicial)
    puntuadas_iniciales = [
        (gr._score_estado(e, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, stats, presupuesto), e)
        for e in frontera
    ]
    puntuadas_iniciales.sort(key=lambda par: par[0], reverse=True)
    mejor_score, mejor_estado = puntuadas_iniciales[0]
    frontera = [e for _, e in puntuadas_iniciales[:beam_width]]

    motivo_stop = "timeout"
    while True:
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

        vivos: list = []
        for hijo in candidatos_hijos:
            cache_hijo = gr.CacheEstructural() if presupuesto is not None else None
            muerto, _sku_causante = gr._evaluar_viabilidad(
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
                continue
            if si_dominado:
                continue
            vivos.append((score_hijo, hijo))

        if not vivos:
            motivo_stop = "estancado"
            break

        vivos.sort(key=lambda par: par[0], reverse=True)
        frontera = [hijo for _, hijo in vivos[:beam_width]]
        stats["max_frontier"] = max(stats["max_frontier"], len(frontera))

        if sum(c for c in mejor_estado.pendientes.values() if c > 0) == 0:
            motivo_stop = "completo"
            break
        if not algun_expandido:
            motivo_stop = "estancado"
            break

    return mejor_estado, motivo_stop


def _correr_contrafactual(nombre, frontera_forzada, contexto, detalles_forzados):
    por_sku = contexto["por_sku"]
    capacidad_cama_por_sku = contexto["capacidad_cama_por_sku"]
    nivel_por_sku = contexto["nivel_por_sku"]
    tope_pallet_por_sku = contexto["tope_pallet_por_sku"]
    presupuesto = contexto["presupuesto"]

    stats = _stats_base()
    t0 = time.time()
    limite_tiempo = t0 + FRESH_TIMEOUT_S
    if not frontera_forzada:
        return {
            "nombre": nombre, "candidatos_probados": len(detalles_forzados), "mejor_resultado": None,
            "faltantes": None, "tiempo_s": 0.0, "motivo_stop": "sin_candidatos_forzados",
            "detalles_forzados": detalles_forzados,
        }
    mejor_estado, motivo_stop = _beam_search_desde_frontera(
        frontera_forzada, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        presupuesto, limite_tiempo, BEAM_WIDTH, ESTRATEGIA, stats,
    )
    tiempo_s = round(time.time() - t0, 3)
    faltantes = {sku: c for sku, c in mejor_estado.pendientes.items() if c > 0}
    return {
        "nombre": nombre, "candidatos_probados": len(detalles_forzados), "mejor_resultado": mejor_estado.cajas_colocadas,
        "faltantes": faltantes, "tiempo_s": tiempo_s, "motivo_stop": motivo_stop,
        "detalles_forzados": detalles_forzados,
    }


if __name__ == "__main__":
    envios, maestro, uma, pobj = cargar_dataset()
    df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
    df_bk52 = df_clasificado[df_clasificado["CD"] == "BK52"]

    original_global_rescue = gr.global_rescue
    try:
        gr.global_rescue = _global_rescue_capture
        armar_pallets_bloques(df_bk52, "BK52", pallets_objetivo=pobj["BK52"], paralelo_lns=True)
    finally:
        gr.global_rescue = original_global_rescue

    frontera_35 = CAPTURED["frontera_35"]
    por_sku = CAPTURED["por_sku"]
    capacidad_cama_por_sku = CAPTURED["capacidad_cama_por_sku"]
    nivel_por_sku = CAPTURED["nivel_por_sku"]
    tope_pallet_por_sku = CAPTURED["tope_pallet_por_sku"]
    presupuesto = CAPTURED["presupuesto"]

    print(f"--- captura: motivo={CAPTURED['motivo']} depth_real={CAPTURED['depth_real']} "
          f"frontier_size={len(frontera_35)} ---", file=sys.stderr)

    # --- sección 2: best_state_global vs best_preserver ---
    puntuadas = [
        (gr._score_estado(e, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, None, presupuesto), e)
        for e in frontera_35
    ]
    puntuadas.sort(key=lambda par: par[0], reverse=True)
    best_state_global = puntuadas[0][1]

    def _preserva_ambos(estado):
        for sku in CRITICAL_SKUS:
            c = _candidatos_hibridos(estado, sku, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
            if c is not None and c <= 0:
                return False
        return True

    preservadores = [(s, e) for s, e in puntuadas if _preserva_ambos(e)]
    best_preserver = preservadores[0][1] if preservadores else None
    mismo_estado = best_preserver is not None and best_state_global is best_preserver

    reporte: dict = {
        "depth_capturado": CAPTURED["depth_real"], "motivo_captura": CAPTURED["motivo"],
        "frontier_size": len(frontera_35),
        "best_state_cajas": best_state_global.cajas_colocadas,
        "best_state_pendientes": {k: v for k, v in best_state_global.pendientes.items() if v > 0},
        "best_state_altura": max(pc.pallet.altura_final for pc in best_state_global.construcciones),
        "mismo_estado_best_y_preserver": mismo_estado,
        "n_preservadores_en_frontier": len(preservadores),
    }
    estado_base = best_state_global  # section 2: si son el mismo, usamos ese; si no, documentamos y usamos best_state_global

    # --- sección 3: tabla MRV ---
    tabla, orden = _tabla_mrv(estado_base, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
    sku_normal = orden[0]
    rank_22353 = next(f["rank_mrv"] for f in tabla if f["sku"] == "22353")
    rank_23510 = next(f["rank_mrv"] for f in tabla if f["sku"] == "23510")
    cc_22353 = next(f["candidate_count"] for f in tabla if f["sku"] == "22353")
    cc_23510 = next(f["candidate_count"] for f in tabla if f["sku"] == "23510")
    reporte["mrv_tabla"] = tabla
    reporte["sku_elegido_normal"] = sku_normal
    reporte["rank_22353"] = rank_22353
    reporte["rank_23510"] = rank_23510
    reporte["candidate_count_22353"] = cc_22353
    reporte["candidate_count_23510"] = cc_23510
    print(f"--- sku_elegido_normal={sku_normal} rank_22353={rank_22353} rank_23510={rank_23510} "
          f"cc_22353={cc_22353} cc_23510={cc_23510} ---", file=sys.stderr)

    # --- Contrafactual A: comportamiento normal ---
    hijos_normal = gr._expandir_estado(
        estado_base, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, ESTRATEGIA, None, presupuesto,
    )
    detalles_a = []
    for hijo in hijos_normal:
        nueva = _torre_nueva(estado_base, hijo)
        c22353 = _candidatos_hibridos(hijo, "22353", por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
        c23510 = _candidatos_hibridos(hijo, "23510", por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
        detalles_a.append({"torre": nueva, "22353_after": c22353, "23510_after": c23510})
    todos_matan_22353 = all((d["22353_after"] == 0) for d in detalles_a if d["22353_after"] is not None)
    reporte["contrafactual_A"] = {
        "n_hijos": len(hijos_normal), "detalles": detalles_a, "todos_22353_muere": todos_matan_22353,
    }
    print(f"--- Contrafactual A: {len(hijos_normal)} hijos, todos matan 22353={todos_matan_22353} ---", file=sys.stderr)

    contexto = {
        "por_sku": por_sku, "capacidad_cama_por_sku": capacidad_cama_por_sku,
        "nivel_por_sku": nivel_por_sku, "tope_pallet_por_sku": tope_pallet_por_sku, "presupuesto": presupuesto,
    }

    def _log_resultado(nombre, res):
        print(f"--- {nombre}: mejor_resultado={res['mejor_resultado']} faltantes={res['faltantes']} "
              f"tiempo_s={res['tiempo_s']} motivo_stop={res['motivo_stop']} ---", file=sys.stderr)

    encontrado_114 = False

    # --- Contrafactual B: forzar 22353 primero ---
    hijos_b, det_b = _expandir_forzado(estado_base, "22353", por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
    res_b = _correr_contrafactual("B_force_22353_first", hijos_b, contexto, det_b)
    reporte["contrafactual_B"] = res_b
    _log_resultado("B (force 22353 first)", res_b)
    if res_b["mejor_resultado"] == 114:
        encontrado_114 = True

    # --- Contrafactual C: forzar 23510 primero ---
    if not encontrado_114:
        hijos_c, det_c = _expandir_forzado(estado_base, "23510", por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
        res_c = _correr_contrafactual("C_force_23510_first", hijos_c, contexto, det_c)
        reporte["contrafactual_C"] = res_c
        _log_resultado("C (force 23510 first)", res_c)
        if res_c["mejor_resultado"] == 114:
            encontrado_114 = True

    # --- Contrafactual D: 22353 -> 23510 ---
    if not encontrado_114:
        hijos_d2 = []
        det_d = []
        for h in hijos_b:
            hijos_d2_sub, det_d_sub = _expandir_forzado(h, "23510", por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
            hijos_d2.extend(hijos_d2_sub)
            det_d.extend(det_d_sub)
        res_d = _correr_contrafactual("D_22353_then_23510", hijos_d2, contexto, det_d)
        reporte["contrafactual_D"] = res_d
        _log_resultado("D (22353 -> 23510)", res_d)
        if res_d["mejor_resultado"] == 114:
            encontrado_114 = True

    # --- Contrafactual E: 23510 -> 22353 ---
    if not encontrado_114:
        hijos_c_para_e, _det_c_para_e = _expandir_forzado(estado_base, "23510", por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
        hijos_e2 = []
        det_e = []
        for h in hijos_c_para_e:
            hijos_e2_sub, det_e_sub = _expandir_forzado(h, "22353", por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
            hijos_e2.extend(hijos_e2_sub)
            det_e.extend(det_e_sub)
        res_e = _correr_contrafactual("E_23510_then_22353", hijos_e2, contexto, det_e)
        reporte["contrafactual_E"] = res_e
        _log_resultado("E (23510 -> 22353)", res_e)
        if res_e["mejor_resultado"] == 114:
            encontrado_114 = True

    reporte["encontrado_114"] = encontrado_114

    # --- sección 9: conflict graph local ---
    # % de candidatos del SKU normal (contrafactual A) que dejan 22353 en 0.
    normales_validos = [d for d in detalles_a if d["22353_after"] is not None]
    pct_normal_mata_22353 = (
        100.0 * sum(1 for d in normales_validos if d["22353_after"] == 0) / len(normales_validos)
        if normales_validos else None
    )
    # % de candidatos de 22353 (contrafactual B) que dejan al SKU normal factible.
    detalles_b_con_normal = []
    for det, hijo in zip(det_b, hijos_b):
        c_normal = _candidatos_hibridos(hijo, sku_normal, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku, presupuesto)
        detalles_b_con_normal.append({**det, f"{sku_normal}_after": c_normal})
    validos_b = [d for d in detalles_b_con_normal if d.get(f"{sku_normal}_after") is not None]
    pct_22353_deja_normal_factible = (
        100.0 * sum(1 for d in validos_b if d[f"{sku_normal}_after"] > 0) / len(validos_b)
        if validos_b else None
    )
    reporte["conflict_graph"] = {
        "normal_sku": sku_normal,
        "pct_normal_candidates_that_eliminate_all_22353_candidates": pct_normal_mata_22353,
        "pct_22353_candidates_after_which_normal_sku_remains_feasible": pct_22353_deja_normal_factible,
        "detalles_b_con_normal_after": detalles_b_con_normal,
    }
    print(f"--- conflict graph: normal_sku={sku_normal} "
          f"%normal_mata_22353={pct_normal_mata_22353} "
          f"%22353_deja_normal_factible={pct_22353_deja_normal_factible} ---", file=sys.stderr)

    out_path = sys.argv[0].rsplit("/", 1)[0] + "/critical_order_bk52_resultado.json"
    with open(out_path, "w") as f:
        json.dump(reporte, f, indent=2, default=str)
    print(f"--- reporte completo en {out_path} ---", file=sys.stderr)
