"""[PATCH V6.12-RC2-C1 -"Front-end DFS work cap"] El DFS del front-end de `Pallets_Objetivo` fijo con `exact_n_incumbent` corre con
un presupuesto de TRABAJO determinista (`FIXED_N_INCUMBENT_FRONTEND_DFS_MAX_NODES` = 1000 nodos):

  exact_n_incumbent existe  -> `_empacar_n_pallets(solo_frente=True, max_nodos_dfs=1000)`; si completa gana el front-end, si no el incumbent
  sin exact_n_incumbent     -> camino profundo de siempre (DFS 30000)

El tope NO se propaga a otros contextos (default de `_empacar_n_pallets`, camino profundo, sondeo, camino abierto)."""
import inspect

import pandas as pd
import pytest

import src.packing_bloques as pb
from src.torres import TorreCandidate


def _df(cantidad):
    return pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": cantidad, "Largo_Efectivo": 60.0, "Ancho_Efectivo": 50.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "T",
    }])


def _espiar_dfs(monkeypatch):
    """Registra el `max_nodos` de cada llamada real a `_resolver_pallets_backtracking` (sin alterarla)."""
    caps = []
    original = pb._resolver_pallets_backtracking

    def _espia(*a, **k):
        caps.append(k.get("max_nodos", pb.COMBINACION_PALLETS_MAX_NODOS))
        return original(*a, **k)

    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", _espia)
    return caps


def _md(pallets):
    return pallets[-1].metadata


# --------------------------------------------------------------------------------------- constantes


def test_el_tope_del_frente_es_1000_y_el_general_sigue_en_30000():
    assert pb.FIXED_N_INCUMBENT_FRONTEND_DFS_MAX_NODES == 1000
    assert pb.COMBINACION_PALLETS_MAX_NODOS == 30_000
    assert inspect.signature(pb._empacar_n_pallets).parameters["max_nodos_dfs"].default == pb.COMBINACION_PALLETS_MAX_NODOS


# ----------------------------------------------- 1. solo_frente + incumbent usa cap 1000 (y 2. sin incumbent, 30000)


def test_con_incumbent_el_frente_recibe_cap_1000_y_el_dfs_real_corre_con_1000(monkeypatch):
    kws = []
    real = pb._empacar_n_pallets

    def _espia(*a, **k):
        kws.append(dict(k))
        return real(*a, **k)

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    caps = _espiar_dfs(monkeypatch)
    pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    assert len(kws) == 1 and kws[0]["solo_frente"] is True and kws[0]["max_nodos_dfs"] == 1000
    assert caps and set(caps) == {1000}                                   # el DFS inicial real corrió con 1000


def test_sin_incumbent_el_camino_profundo_sigue_con_30000(monkeypatch):
    kws = []
    real = pb._empacar_n_pallets

    def _espia(*a, **k):
        kws.append(dict(k))
        return real(*a, **k)

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    caps = _espiar_dfs(monkeypatch)
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=3, paralelo_lns=False)   # n_greedy (2) < N (3): sin incumbent
    assert kws == [{"paralelo_lns": False, "priorizar_grandes": True}]    # ni solo_frente ni max_nodos_dfs: default de siempre
    assert caps[0] == 30_000
    assert "fixed_n_frontend_dfs_budget" not in _md(pallets)
    assert _md(pallets)["fixed_n_exact_n_incumbent"]["resultado"] == "CAMINO_PROFUNDO"


# ------------------------------------------------------------------ 3. completa antes de 1000 -> gana el front-end


def test_frente_completa_antes_de_1000_gana_el_frente_y_registra_metadata():
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    md = _md(pallets)
    assert sum(t.cantidad for p in pallets for t in p.torres) == 60 and len(pallets) == 2
    assert md["fixed_n_exact_n_incumbent"]["resultado"] == "FRENTE_COMPLETO"
    assert md["fixed_n_solution_source"] == "FRONTEND_COMPLETE"
    assert md["fixed_n_frontend_dfs_budget"] == 1000
    assert md["fixed_n_frontend_stop_reason"] == "solucion_completa" and md["fixed_n_frontend_dfs_nodes"] <= 1000


# --------------------------------- 4. llega al cap sin completar (aunque MEJORE antes del cap) -> gana el incumbent


def _frente_real_inalcanzable(cap):
    """Resultado REAL del front-end sobre una demanda inalcanzable: el DFS mejora (más cajas con más presupuesto) y se corta por `max_nodos`."""
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)]}
    info = {}
    res = pb._empacar_n_pallets({"A": 5000, "B": 5000}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, max_nodos_dfs=cap,
                                lns_recon_max_nodos=10, lns_sin_mejora_max=2, solo_frente=True, info_frente=info)
    return res, info


def test_el_dfs_real_mejora_antes_del_cap_pero_no_completa_y_se_corta_por_max_nodos():
    (p_chico, _), i_chico = _frente_real_inalcanzable(40)
    (p_cap, sin_cap), i_cap = _frente_real_inalcanzable(1000)
    colocadas = lambda ps: sum(t.cantidad for p in ps for t in p.torres)
    assert colocadas(p_cap) > colocadas(p_chico) > 0                      # sigue mejorando antes de llegar a 1000...
    assert sin_cap and i_cap == {"nodos": 1001, "motivo_parada": "max_nodos"}   # ...pero no completa: se corta exactamente por el tope


def test_contrato_mejora_antes_del_cap_sin_completar_gana_el_incumbent(monkeypatch):
    (parciales, sin), info_real = _frente_real_inalcanzable(1000)         # front-end que mejora pero queda incompleto
    colocadas_frente = sum(t.cantidad for p in parciales for t in p.torres)
    assert colocadas_frente > 0 and sin

    def _frente(*a, **k):
        k["info_frente"].update(info_real)
        return parciales, sin

    monkeypatch.setattr(pb, "_empacar_n_pallets", _frente)
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    md = _md(pallets)
    assert len(pallets) == 2 and sum(t.cantidad for p in pallets for t in p.torres) == 60     # gana el incumbent (100 %), no el parcial
    assert md["fixed_n_exact_n_incumbent"]["resultado"] == "INCUMBENT_USADO"
    assert md["fixed_n_exact_n_incumbent"]["frente_colocadas"] == colocadas_frente
    assert md["fixed_n_solution_source"] == "EXACT_N_GREEDY_INCUMBENT"
    assert md["fixed_n_frontend_dfs_budget"] == 1000 and md["fixed_n_frontend_stop_reason"] == "max_nodos"
    assert md["fixed_n_frontend_dfs_nodes"] == 1001


# --------------------------------------------------------------------------- 5. el resultado no depende del reloj


def _firma(pallets):
    return sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for p in pallets for t in p.torres)


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_el_resultado_con_cap_no_depende_del_reloj(monkeypatch, reloj):
    esperado_real = _frente_real_inalcanzable(1000)
    esperado_armar = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    monkeypatch.setattr(pb.time, "process_time", reloj)
    monkeypatch.setattr(pb.time, "monotonic", reloj)
    monkeypatch.setattr(pb.time, "time", reloj)
    (p, sin), info = _frente_real_inalcanzable(1000)
    assert (_firma(p), sin, info) == (_firma(esperado_real[0][0]), esperado_real[0][1], esperado_real[1])
    armar = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    assert _firma(armar) == _firma(esperado_armar)
    assert _md(armar)["fixed_n_frontend_dfs_nodes"] == _md(esperado_armar)["fixed_n_frontend_dfs_nodes"]


# --------------------------------------------------------------------- 6. el cap no se propaga a otros contextos


def test_el_cap_no_se_propaga_a_otros_contextos(monkeypatch):
    caps = _espiar_dfs(monkeypatch)
    # (a) default directo de `_empacar_n_pallets` (sin `solo_frente`): 30000
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 60.0, 50.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_n_pallets({"A": 60}, por_sku, {}, {"A": 1}, {}, "T", [0], 2, paralelo_lns=False, solo_frente=True)
    assert caps == [30_000]
    # (b) camino abierto (sin Pallets_Objetivo): no usa el front-end con incumbent ni el tope
    caps.clear()
    monkeypatch.setattr(pb, "_exact_n_incumbent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe correr")))
    pb.armar_pallets_bloques(_df(60), "T", paralelo_lns=False)
    assert 1000 not in caps
    # (c) el sondeo de busqueda_n_pallets mantiene su propio tope
    import src.busqueda_n_pallets as bn
    assert bn.PROBE_DFS_MAX_NODES == 8000


def test_info_frente_es_opcional_y_no_altera_la_llamada_al_dfs(monkeypatch):
    kws = []
    original = pb._resolver_pallets_backtracking
    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", lambda *a, **k: (kws.append(set(k)), original(*a, **k))[1])
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 60.0, 50.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_n_pallets({"A": 60}, por_sku, {}, {"A": 1}, {}, "T", [0], 2, paralelo_lns=False)
    assert "info_salida" not in kws[0]                                    # sin `info_frente` la llamada es idéntica a la de siempre
