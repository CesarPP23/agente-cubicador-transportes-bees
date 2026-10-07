"""[PATCH V6.12-D7B-P3 -"Probe Repair work budget"] Repair corta por un
presupuesto de NODOS (unidad y convención de conteo: `src/medidor_trabajo.py`)
SOLO en el contexto del sondeo (`busqueda_n_pallets.probe()`):
`PROBE_REPAIR_MAX_NODES` viaja explícito `probe()` -> `_empacar_n_pallets`
(`presupuesto_repair_nodos`) -> `repair_solver(presupuesto_nodos=...)`, con
SU PROPIO medidor (independiente del de Rescue). La materialización final y
`Pallets_Objetivo` fijo no reciben el kwarg."""
import inspect
from unittest.mock import patch

import pytest

import config
import src.busqueda_n_pallets as bnp
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from models import PalletV5
from src.busqueda_n_pallets import ProbeStatus
from src.repair_solver import repair_solver
from src.rescue_solver import rescue_solver
from src.torres import TorreCandidate, crear_torre


def _cand(sku, largo, ancho, alto, cantidad_disponible=10):
    return TorreCandidate(sku, "CD", "LxA", largo, ancho, alto, 10, cantidad_disponible, 1.0)


def _escenario_ejection():
    """Repair RESUELVE rápido (ejection chain entre pallets): CRITICO no cabe
    directo, pero ejectando MOVIBLE entra. Faltante inicial 1 -> final 0."""
    relleno_cand = _cand("RELLENO", config.PALLET_LARGO, config.PALLET_ANCHO, 50.0)
    relleno = crear_torre(relleno_cand, x=0, y=0, cantidad=1)
    pallet_a = PalletV5(id="PA", cd="CD", torres=[relleno], altura_final=config.ALTURA_PALLET_VACIO + 50.0)
    movible_cand = _cand("MOVIBLE", 20, 20, 20.0, cantidad_disponible=1)
    movible = crear_torre(movible_cand, x=0, y=0, cantidad=1)
    pallet_b = PalletV5(id="PB", cd="CD", torres=[movible], altura_final=config.ALTURA_PALLET_VACIO + 20.0)
    critico_cand = _cand("CRITICO", config.PALLET_LARGO, config.PALLET_ANCHO, 20.0, cantidad_disponible=1)
    por_sku = {"RELLENO": [relleno_cand], "MOVIBLE": [movible_cand], "CRITICO": [critico_cand]}
    nivel_por_sku = {"RELLENO": 6, "MOVIBLE": 6, "CRITICO": 6}
    presupuesto = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO
    return [pallet_a, pallet_b], {"CRITICO": 1}, por_sku, nivel_por_sku, presupuesto, 2


def _escenario_sin_progreso():
    """Repair NO puede resolver (GRANDE bloqueado por 2 muros) y entra en
    rondas baratas sin progreso: solo lo detiene el presupuesto -ideal para
    medir el corte, el reloj y la repetibilidad de forma determinista."""
    presupuesto = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO
    wall1_cand = _cand("WALL1", 82.0, 104.0, presupuesto)
    wall1 = crear_torre(wall1_cand, x=40, y=-2, cantidad=1)
    wall2_cand = _cand("WALL2", 42.0, 72.0, presupuesto)
    wall2 = crear_torre(wall2_cand, x=-2, y=30, cantidad=1)
    chico_a = _cand("A", 20, 30, 15)
    chico_b = _cand("B", 20, 30, 15)
    torre_a = crear_torre(chico_a, x=0, y=0, cantidad=1)
    torre_b = crear_torre(chico_b, x=20, y=0, cantidad=1)
    pallet = PalletV5(id="P1", cd="BK31", torres=[wall1, wall2, torre_a, torre_b],
                       altura_final=config.ALTURA_PALLET_VACIO + presupuesto)
    grande = _cand("GRANDE", 40, 30, 15)
    por_sku = {"GRANDE": [grande], "A": [chico_a], "B": [chico_b], "WALL1": [wall1_cand], "WALL2": [wall2_cand]}
    nivel_por_sku = {k: 6 for k in por_sku}
    return [pallet], {"GRANDE": 1}, por_sku, nivel_por_sku, presupuesto, 1


def _correr_repair(escenario, **kw):
    pallets, sin_colocar, por_sku, nivel, presupuesto, n_pallets = escenario()
    pallets_final, sin_colocar_final, stats = repair_solver(
        pallets, sin_colocar, por_sku, {}, nivel, {}, n_pallets, presupuesto, **kw,
    )
    firma = sorted((p.id, t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2))
                   for p in pallets_final for t in p.torres)
    return sin_colocar_final, stats, firma


# --------------------------------------------------------- constantes y firmas


def test_constantes_y_defaults():
    assert bnp.PROBE_REPAIR_MAX_NODES == 24000
    assert inspect.signature(repair_solver).parameters["presupuesto_nodos"].default is None
    assert inspect.signature(pb._empacar_n_pallets).parameters["presupuesto_repair_nodos"].default is None


# ----------------------------------------------------- propagación del contexto


def test_probe_pasa_los_tres_presupuestos(monkeypatch):
    capturado = {}

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        capturado.update(kw)
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    bnp.probe(1, {"A": 5}, {"A": [_cand("A", 30, 20, 20)]}, {}, {"A": 1}, {}, "TEST", [0], False)

    assert capturado["presupuesto_repair_nodos"] == bnp.PROBE_REPAIR_MAX_NODES == 24000
    assert capturado["presupuesto_rescue_nodos"] == bnp.PROBE_RESCUE_MAX_NODES == 15000
    assert capturado["max_nodos_dfs"] == bnp.PROBE_DFS_MAX_NODES == 8000


def test_final_y_pallets_objetivo_no_reciben_el_presupuesto_de_repair(monkeypatch):
    llamadas = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append(dict(kw))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: [PalletV5(id=f"PV5-X-{i}", cd="X") for i in range(2)])
    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_optimizado({"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0], paralelo_lns=False)
    sondeos = [kw for kw in llamadas if kw.get("con_lns") is False]
    finales = [kw for kw in llamadas if kw.get("con_lns", True) is True]
    assert sondeos and all(kw["presupuesto_repair_nodos"] == 24000 for kw in sondeos)
    assert finales and all("presupuesto_repair_nodos" not in kw for kw in finales)

    llamadas.clear()
    import pandas as pd

    df = pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": 3, "Largo_Efectivo": 30.0, "Ancho_Efectivo": 20.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "BK31",
    }])
    try:
        pb.armar_pallets_bloques(df, "BK31", pallets_objetivo=1, paralelo_lns=False)
    except Exception:  # el espía devuelve vacío -solo importan los kwargs recibidos
        pass
    assert llamadas and all("presupuesto_repair_nodos" not in kw for kw in llamadas)


def _stub_exact_global(monkeypatch, entradas_exact=None, entradas_global=None):
    def _exact(pallet, por_sku, sin_colocar, *a, **k):
        if entradas_exact is not None:
            entradas_exact.append(dict(sin_colocar))
        return pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}

    def _global(pallets, sin_colocar, *a, **k):
        if entradas_global is not None:
            entradas_global.append(dict(sin_colocar))
        return pallets, sin_colocar, {}

    monkeypatch.setattr(er, "exact_repair_orquestado", _exact)
    monkeypatch.setattr(gr, "global_rescue", _global)


def _empacar_n_inalcanzable(**kw):
    por_sku = {
        "A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)],
        "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)],
    }
    return pb._empacar_n_pallets(
        {"A": 200, "B": 200}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1,
        paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw,
    )


def test_empacar_n_pallets_envia_presupuesto_a_repair_solo_si_se_pide_y_separado_del_de_rescue(monkeypatch):
    rescue_kw, repair_kw = [], []
    monkeypatch.setattr(rs, "rescue_solver", lambda p, s, *a, **k: (rescue_kw.append(dict(k)), (p, s, {}))[1])
    monkeypatch.setattr(rp, "repair_solver", lambda p, s, *a, **k: (repair_kw.append(dict(k)), (p, s, {}))[1])
    _stub_exact_global(monkeypatch)

    _empacar_n_inalcanzable()
    _empacar_n_inalcanzable(presupuesto_rescue_nodos=111)
    _empacar_n_inalcanzable(presupuesto_rescue_nodos=111, presupuesto_repair_nodos=222)

    assert "presupuesto_nodos" not in repair_kw[0] and "presupuesto_nodos" not in rescue_kw[0]
    assert rescue_kw[1]["presupuesto_nodos"] == 111 and "presupuesto_nodos" not in repair_kw[1]
    # cada etapa recibe SU valor: no se mezclan los contadores
    assert rescue_kw[2]["presupuesto_nodos"] == 111
    assert repair_kw[2]["presupuesto_nodos"] == 222


def test_etapa_posterior_recibe_exactamente_el_residual_de_repair(monkeypatch):
    entradas_exact, entradas_global = [], []
    monkeypatch.setattr(rs, "rescue_solver", lambda p, s, *a, **k: (p, {"A": 40}, {}))
    monkeypatch.setattr(rp, "repair_solver", lambda p, s, *a, **k: (p, {"A": 7}, {}))
    _stub_exact_global(monkeypatch, entradas_exact, entradas_global)
    monkeypatch.setattr(rs, "_score_solucion", lambda total, *a, **k: (total,))  # acepta toda mejora

    _empacar_n_inalcanzable(presupuesto_rescue_nodos=15000, presupuesto_repair_nodos=24000)

    assert entradas_exact and entradas_exact[0] == {"A": 7}  # Exact parte del residual de Repair, no del de Rescue


def test_si_repair_completa_las_etapas_posteriores_no_corren_y_el_probe_es_feasible(monkeypatch):
    entradas_exact, entradas_global = [], []
    monkeypatch.setattr(rs, "rescue_solver", lambda p, s, *a, **k: (p, {"A": 3}, {}))
    monkeypatch.setattr(rp, "repair_solver", lambda p, s, *a, **k: (p, {}, {}))  # 3 -> 0
    _stub_exact_global(monkeypatch, entradas_exact, entradas_global)
    monkeypatch.setattr(rs, "_score_solucion", lambda total, *a, **k: (total,))
    monkeypatch.setattr(bnp, "PROBE_DFS_MAX_NODES", 30)

    por_sku = {
        "A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)],
        "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)],
    }
    r = bnp.probe(1, {"A": 200, "B": 200}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], False)

    assert r.status is ProbeStatus.FEASIBLE
    assert entradas_exact == [] and entradas_global == []


# ------------------------------------------------------- Repair real: el corte


def test_repair_sin_presupuesto_nodos_sigue_en_modo_tiempo(monkeypatch):
    monkeypatch.setattr(rp, "REPAIR_TIME_MAX_SECONDS", 0.05)
    sin_colocar, stats, _ = _correr_repair(_escenario_ejection)
    assert sin_colocar == {}
    assert stats["presupuesto"] == {"modo": "tiempo"}


def test_repair_completa_dentro_del_budget_y_es_igual_al_modo_tiempo():
    """Análogo a BK65 n=4 (3 -> 0 dentro del presupuesto): con el tope de
    producción Repair resuelve el faltante, con el mismo resultado que el modo
    tiempo; y consume trabajo medible."""
    sc_t, _, firma_t = _correr_repair(_escenario_ejection)
    sc_n, st_n, firma_n = _correr_repair(_escenario_ejection, presupuesto_nodos=bnp.PROBE_REPAIR_MAX_NODES)
    assert sc_t == sc_n == {}
    assert firma_n == firma_t
    assert st_n["presupuesto"]["modo"] == "nodos"
    assert 0 < st_n["presupuesto"]["nodos_trabajo"] <= bnp.PROBE_REPAIR_MAX_NODES


def test_la_unidad_en_curso_termina_aunque_cruce_el_tope():
    """Convención (src/medidor_trabajo.py): el chequeo es ENTRE unidades. Con
    presupuesto 1 la primera unidad arranca (0 > 1 es falso), consume más que
    el tope y TERMINA: el faltante queda resuelto igual."""
    sc, st, _ = _correr_repair(_escenario_ejection, presupuesto_nodos=1)
    assert sc == {}
    assert st["presupuesto"]["nodos_trabajo"] > 1


def test_cutoff_con_presupuesto_cero_repair_no_arranca_nada():
    sc, st, _ = _correr_repair(_escenario_ejection, presupuesto_nodos=0)
    assert st["rondas"] == 0
    assert st["presupuesto"]["nodos_trabajo"] == 0
    assert sc == {"CRITICO": 1}


@pytest.mark.parametrize("tope", [500, 1500, 3000])
def test_cutoff_exacto_por_presupuesto_en_repair_sin_progreso(tope):
    """Rondas de ~1-2 nodos: el consumo queda en [tope, tope + una unidad]."""
    _, st, _ = _correr_repair(_escenario_sin_progreso, presupuesto_nodos=tope)
    nodos = st["presupuesto"]["nodos_trabajo"]
    assert tope <= nodos <= tope + 5
    assert st["presupuesto"]["tope"] == tope


def test_mas_presupuesto_mas_trabajo():
    nodos = [_correr_repair(_escenario_sin_progreso, presupuesto_nodos=t)[1]["presupuesto"]["nodos_trabajo"]
             for t in (200, 800, 2000)]
    assert nodos[0] < nodos[1] < nodos[2]


# ------------------------------------------------ el reloj no decide el trabajo


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_reloj_rapido_o_lento_no_cambia_el_trabajo_de_repair(reloj):
    ref = _correr_repair(_escenario_sin_progreso, presupuesto_nodos=1500)
    with patch("time.process_time", side_effect=lambda: reloj()):
        sc, st, firma = _correr_repair(_escenario_sin_progreso, presupuesto_nodos=1500)
    assert (sc, firma) == (ref[0], ref[2])
    assert st["presupuesto"] == ref[1]["presupuesto"]
    assert st["rondas"] == ref[1]["rondas"]


def test_mismo_input_mismos_nodos_y_residual():
    corridas = [_correr_repair(_escenario_sin_progreso, presupuesto_nodos=1500) for _ in range(3)]
    assert len({(c[1]["presupuesto"]["nodos_trabajo"], c[1]["rondas"], tuple(sorted(c[0].items())), tuple(c[2]))
                for c in corridas}) == 1


# --------------------------------------------- cada etapa tiene su propio medidor


def test_repair_no_hereda_el_trabajo_de_rescue():
    """El `nodos_trabajo` de Repair es el mismo corra o no Rescue antes: los
    medidores son independientes (cada entry point crea el suyo)."""
    _, st_solo, _ = _correr_repair(_escenario_sin_progreso, presupuesto_nodos=1000)

    pallets, sin_colocar, por_sku, nivel, presupuesto, n_pallets = _escenario_sin_progreso()
    _, _, st_rescue = rescue_solver(
        pallets, sin_colocar, por_sku, {}, nivel, {}, n_pallets, presupuesto, presupuesto_nodos=1000,
    )
    assert st_rescue["presupuesto"]["nodos_trabajo"] > 0

    _, st_despues, _ = _correr_repair(_escenario_sin_progreso, presupuesto_nodos=1000)
    assert st_despues["presupuesto"]["nodos_trabajo"] == st_solo["presupuesto"]["nodos_trabajo"]
