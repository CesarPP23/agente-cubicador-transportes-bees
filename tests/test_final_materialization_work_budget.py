"""[PATCH V6.12-D8A.1 -"Final materialization work budget"] La materialización
FINAL (`_empacar_optimizado`, la corrida con LNS en la N ganadora) usa sus
propios presupuestos de TRABAJO, calibrados desde los breakpoints medidos de
los 8 CDs cuya final tiene éxito (ver `busqueda_n_pallets.FINAL_*`):

    FINAL_DFS_MAX_NODES       = 6500   (DFS inicial)
    FINAL_LNS_RECON_MAX_NODES = 2650   (DFS de reconstrucción del LNS)
    FINAL_LNS_SIN_MEJORA      = 40     (iteraciones consecutivas sin mejora)

No los heredan ni el sondeo (8000 / 15000 / 24000 / 500 + 1,0) ni
`Pallets_Objetivo` fijo (30000 / 3000 / 40, constantes de módulo).

[CONVENCIÓN DE CONTEO -ver tests/test_busqueda_n_pallets_probe_dfs_budget.py]
un tope N significa N expansiones y N + 1 visitas (guard estricto `>`)."""
import inspect

import pandas as pd
import pytest

import src.busqueda_n_pallets as bnp
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from models import PalletV5
from src.torres import TorreCandidate


def _cand(sku, largo, ancho, alto, cantidad_disponible=200):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, cantidad_disponible, 1.0)


def _escenario_inalcanzable():
    por_sku = {"A": [_cand("A", 40, 30, 20)], "B": [_cand("B", 20, 15, 12)]}
    return por_sku, {"A": 200, "B": 200}


def _stubear_cascada(monkeypatch):
    monkeypatch.setattr(rs, "rescue_solver", lambda p, s, *a, **k: (p, s, {}))
    monkeypatch.setattr(rp, "repair_solver", lambda p, s, *a, **k: (p, s, {}))
    monkeypatch.setattr(er, "exact_repair_orquestado",
                        lambda p, ps, s, *a, **k: (p, s, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}))
    monkeypatch.setattr(gr, "global_rescue", lambda p, s, *a, **k: (p, s, {}))


def _visitas_dfs(monkeypatch):
    """Registra `estado["nodos"]` (visitas) de CADA `_resolver_pallets_backtracking`
    -en orden de ejecución: la primera es el DFS inicial, el resto las
    reconstrucciones del LNS. No cambia el comportamiento."""
    visitas: list[int] = []
    fuente = inspect.getsource(pb._resolver_pallets_backtracking)
    marca = '    return estado["mejor_total"]\n'
    assert fuente.count(marca) == 1
    fuente = fuente.replace(marca, '    _registro_final_test.append(estado["nodos"])\n' + marca)
    original = pb._resolver_pallets_backtracking
    pb.__dict__["_registro_final_test"] = visitas
    exec(compile(fuente, "<visitas_final_test>", "exec"), pb.__dict__)
    instrumentada = pb.__dict__["_resolver_pallets_backtracking"]
    pb.__dict__["_resolver_pallets_backtracking"] = original
    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", instrumentada)
    monkeypatch.delitem(pb.__dict__, "_registro_final_test", raising=False)
    pb.__dict__["_registro_final_test"] = visitas
    return visitas


def _final(**kw):
    por_sku, pendientes = _escenario_inalcanzable()
    return pb._empacar_n_pallets(
        dict(pendientes), por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, con_lns=True, **kw,
    )


def _firma(res):
    pallets, sin = res
    return (sorted(sin.items()), sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2))
                                        for p in pallets for t in p.torres))


# ------------------------------------------------------------------ constantes


def test_constantes_final_y_probe_conservan_sus_valores():
    assert (bnp.FINAL_DFS_MAX_NODES, bnp.FINAL_LNS_RECON_MAX_NODES, bnp.FINAL_LNS_SIN_MEJORA) == (6500, 2650, 40)
    # el sondeo no se recalibró
    assert bnp.PROBE_DFS_MAX_NODES == 8000 and bnp.PROBE_RESCUE_MAX_NODES == 15000
    assert bnp.PROBE_REPAIR_MAX_NODES == 24000
    assert bnp.PROBE_EXACT_MAX_ATTEMPTS == 500 and bnp.PROBE_EXACT_MAX_DET_TIME == 1.0
    # y las constantes de módulo (Pallets_Objetivo) tampoco
    assert pb.COMBINACION_PALLETS_MAX_NODOS == 30_000
    assert pb.COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION == 3_000
    assert pb.COMBINACION_PALLETS_LNS_SIN_MEJORA_MAX == 40


def test_los_breakpoints_medidos_quedan_por_debajo_de_los_topes_finales():
    """Los topes tienen que quedar por encima de los breakpoints de D8A (por
    debajo el layout de BK43/SJ86 cambia): DFS 4274, recon 2464, sin mejora 39."""
    assert bnp.FINAL_DFS_MAX_NODES >= 4274 * 1.5
    assert bnp.FINAL_LNS_RECON_MAX_NODES >= 2464 + 150
    assert bnp.FINAL_LNS_SIN_MEJORA >= 39
    assert bnp.FINAL_LNS_RECON_MAX_NODES < pb.COMBINACION_PALLETS_LNS_MAX_NODOS_RECONSTRUCCION


def test_defaults_de_las_funciones_siguen_en_none_o_en_las_constantes():
    firma = inspect.signature(pb._empacar_n_pallets).parameters
    assert firma["lns_recon_max_nodos"].default is None and firma["lns_sin_mejora_max"].default is None
    assert firma["max_nodos_dfs"].default == pb.COMBINACION_PALLETS_MAX_NODOS
    firma = inspect.signature(pb._lns_mejorar_pallets).parameters
    assert firma["max_nodos_reconstruccion"].default is None and firma["sin_mejora_max"].default is None
    firma = inspect.signature(pb._lns_una_semilla_worker).parameters
    assert firma["max_nodos_reconstruccion"].default is None and firma["sin_mejora_max"].default is None


# ----------------------------------------------------- propagación del contexto


def _espiar_empacar_n(monkeypatch):
    llamadas = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append(dict(kw))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    return llamadas


def test_final_usa_6500_2650_40_y_el_probe_conserva_8000_sin_kwargs_de_lns(monkeypatch):
    llamadas = _espiar_empacar_n(monkeypatch)
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: [PalletV5(id=f"PV5-X-{i}", cd="X") for i in range(2)])
    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_optimizado({"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0], paralelo_lns=False)

    sondeos = [kw for kw in llamadas if kw.get("con_lns") is False]
    finales = [kw for kw in llamadas if kw.get("con_lns", True) is True]
    assert sondeos and finales
    for kw in sondeos:
        assert kw["max_nodos_dfs"] == 8000
        assert kw["presupuesto_rescue_nodos"] == 15000 and kw["presupuesto_repair_nodos"] == 24000
        assert kw["presupuesto_exact_intentos"] == 500 and kw["exact_max_deterministic_time"] == 1.0
        assert "lns_recon_max_nodos" not in kw and "lns_sin_mejora_max" not in kw
        assert "omitir_repair" not in kw and "presupuesto_global_expansiones" not in kw
    for kw in finales:
        assert kw["max_nodos_dfs"] == 6500
        assert kw["lns_recon_max_nodos"] == 2650 and kw["lns_sin_mejora_max"] == 40
        # el final no hereda NINGÚN presupuesto del sondeo: tiene los suyos (D8B-7.2)
        assert kw["presupuesto_rescue_nodos"] == 3250 and "presupuesto_repair_nodos" not in kw
        assert kw["omitir_repair"] is True
        assert kw["presupuesto_exact_intentos"] == 14 and kw["exact_max_deterministic_time"] == 1.0
        assert kw["presupuesto_global_expansiones"] == 9500


def test_pallets_objetivo_no_hereda_el_budget_final(monkeypatch):
    llamadas = _espiar_empacar_n(monkeypatch)
    df = pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": 3, "Largo_Efectivo": 30.0, "Ancho_Efectivo": 20.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "BK31",
    }])
    try:
        pb.armar_pallets_bloques(df, "BK31", pallets_objetivo=1, paralelo_lns=False)
    except Exception:  # el espía devuelve vacío -solo importan los kwargs
        pass
    assert llamadas
    for kw in llamadas:
        assert "max_nodos_dfs" not in kw and "lns_recon_max_nodos" not in kw and "lns_sin_mejora_max" not in kw
        assert not any(k.startswith("presupuesto_") for k in kw)
        assert "omitir_repair" not in kw and "exact_max_deterministic_time" not in kw


def test_lns_secuencial_recibe_los_topes_y_sin_kwargs_usa_las_constantes(monkeypatch):
    _stubear_cascada(monkeypatch)
    vistos = []
    original = pb._lns_mejorar_pallets

    def _espia(*a, **k):
        vistos.append((k.get("max_nodos_reconstruccion"), k.get("sin_mejora_max")))
        return original(*a, **k)

    monkeypatch.setattr(pb, "_lns_mejorar_pallets", _espia)
    _final(max_nodos_dfs=20, lns_recon_max_nodos=15, lns_sin_mejora_max=2)
    _final(max_nodos_dfs=20)
    assert vistos == [(15, 2), (None, None)]  # None => las constantes de módulo dentro de _lns_mejorar_pallets


def test_el_worker_paralelo_reenvia_los_topes(monkeypatch):
    capturado = {}

    def _espia(*a, **k):
        capturado.update(k)
        return 7

    monkeypatch.setattr(pb, "_lns_mejorar_pallets", _espia)
    por_sku, pendientes = _escenario_inalcanzable()
    total, *_ = pb._lns_una_semilla_worker(
        [], [], dict(pendientes), por_sku, {}, {}, {}, 100.0, 1, "sem", None, frozenset(),
        max_nodos_reconstruccion=2650, sin_mejora_max=40,
    )
    assert total == 7
    assert capturado["max_nodos_reconstruccion"] == 2650 and capturado["sin_mejora_max"] == 40


# ------------------------------------------------------- el corte es por trabajo


def test_cutoff_exacto_dfs_inicial_y_reconstruccion_siguen_la_convencion(monkeypatch):
    """Tope N => N + 1 visitas. El DFS inicial corta en `max_nodos_dfs` + 1 y TODA
    reconstrucción del LNS en `lns_recon_max_nodos` + 1 (el escenario es
    inalcanzable: ningún DFS agota el espacio antes)."""
    _stubear_cascada(monkeypatch)
    visitas = _visitas_dfs(monkeypatch)
    _final(max_nodos_dfs=21, lns_recon_max_nodos=13, lns_sin_mejora_max=3)
    assert visitas[0] == 21 + 1
    recon = visitas[1:]
    assert len(recon) >= 3                       # el LNS corrió
    assert all(v <= 13 + 1 for v in recon)       # nunca por encima del tope documentado
    assert max(recon) == 13 + 1                  # y llega exactamente a él


def test_sin_mejora_corta_el_lns_por_conteo_de_iteraciones(monkeypatch):
    _stubear_cascada(monkeypatch)
    visitas = _visitas_dfs(monkeypatch)
    _final(max_nodos_dfs=15, lns_recon_max_nodos=5, lns_sin_mejora_max=2)
    iteraciones_chico = len(visitas) - 1
    visitas.clear()
    _final(max_nodos_dfs=15, lns_recon_max_nodos=5, lns_sin_mejora_max=6)
    iteraciones_grande = len(visitas) - 1
    assert 2 <= iteraciones_chico <= iteraciones_grande
    assert iteraciones_grande >= 6


def test_mismo_input_final_mismo_trabajo_y_mismo_resultado(monkeypatch):
    _stubear_cascada(monkeypatch)
    visitas = _visitas_dfs(monkeypatch)
    corridas = []
    for _ in range(3):
        visitas.clear()
        res = _final(max_nodos_dfs=30, lns_recon_max_nodos=17, lns_sin_mejora_max=4)
        corridas.append((tuple(visitas), _firma(res)))
    assert corridas[0] == corridas[1] == corridas[2]


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_reloj_rapido_o_lento_no_cambia_el_trabajo_final(monkeypatch, reloj):
    """Ni el DFS inicial ni el LNS de la final deciden nada con el reloj."""
    _stubear_cascada(monkeypatch)
    visitas = _visitas_dfs(monkeypatch)
    _final(max_nodos_dfs=30, lns_recon_max_nodos=17, lns_sin_mejora_max=4)
    esperado = tuple(visitas)
    visitas.clear()
    monkeypatch.setattr(pb.time, "process_time", reloj)
    monkeypatch.setattr(pb.time, "monotonic", reloj)
    _final(max_nodos_dfs=30, lns_recon_max_nodos=17, lns_sin_mejora_max=4)
    assert tuple(visitas) == esperado
