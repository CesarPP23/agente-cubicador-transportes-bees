"""[PATCH V6.12-D7B-P4 -"Probe Exact deterministic hardening"] Exact deja de
usar el reloj como fuente de decisión lógica SOLO en el contexto del sondeo
(`busqueda_n_pallets.probe()`), en dos niveles independientes:

  A. Orquestador Python: tope DURO de intentos (`max_intentos`), compartido por
     todos los pallets del CD, en vez del deadline de CPU-time.
  B. CP-SAT nativo: `max_deterministic_time` (1 worker), con
     `max_time_in_seconds` reducido a watchdog operacional
     (`OPERATIONAL_TIMEOUT` si alguna vez dispara).

La materialización final y `Pallets_Objetivo` fijo NO reciben ningún override.
"""
import inspect
import logging

import pytest

import config
import src.busqueda_n_pallets as bnp
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.packing_columnar as pc
import src.repair_solver as rp
import src.rescue_solver as rs
from models import PalletV5
from src.exact_repair import (
    CP_SAT_COMPLETADO, CP_SAT_LIMITE_DETERMINISTA, CP_SAT_LIMITE_TIEMPO, CP_SAT_TIMEOUT_OPERATIVO,
    _clasificar_parada_cp_sat, exact_repair_orquestado, resolver_cp_sat,
)
from src.torres import TorreCandidate, crear_torre

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo=40.0, ancho=30.0, alto=20.0, disp=10):
    return TorreCandidate(sku, "CD", "LxA", largo, ancho, alto, 10, disp, 1.0)


def _pallet_vacio():
    return PalletV5(id="P", cd="CD", torres=[], altura_final=config.ALTURA_PALLET_VACIO)


# ============================================================= nivel B: CP-SAT


def _resolver(**kw):
    return resolver_cp_sat(
        _pallet_vacio(), {"A": [_cand("A")]}, {"A": 4}, {}, PRESUPUESTO, region=(0, 0, 80, 60), **kw,
    )


def test_cp_sat_siempre_single_worker_y_con_tope_determinista_cuando_se_pide(monkeypatch):
    from ortools.sat.python import cp_model

    vistos = []

    class _Espia(cp_model.CpSolver):
        def Solve(self, *a, **k):  # noqa: N802
            vistos.append((self.parameters.num_search_workers, self.parameters.max_time_in_seconds,
                           self.parameters.max_deterministic_time))
            return super().Solve(*a, **k)

    monkeypatch.setattr(cp_model, "CpSolver", _Espia)
    _resolver()                                   # modo clásico
    _resolver(max_deterministic_time=0.25)        # modo probe
    clasico, probe = vistos
    assert clasico[0] == probe[0] == 1            # SIEMPRE 1 worker (reproducible)
    assert clasico[2] == float("inf")             # clásico: sin tope determinista
    assert probe[2] == pytest.approx(0.25)
    assert clasico[1] == probe[1] == er.EXACT_REPAIR_TIME_MAX_SECONDS  # la pared queda como watchdog, sin cambios


def test_max_deterministic_time_es_reproducible_en_las_mismas_condiciones():
    corridas = [_resolver(max_deterministic_time=1.0) for _ in range(3)]
    claves = ("status", "objetivo", "det_time", "branches", "conflicts", "parada", "posiciones_candidatas")
    firmas = [tuple(r[k] for k in claves) + (tuple(sorted(
        (sku, round(x, 3), round(y, 3), round(z, 3)) for sku, x, y, z, _c in r["colocado"])),) for r in corridas]
    assert firmas[0] == firmas[1] == firmas[2]
    assert corridas[0]["status"] == "OPTIMAL" and corridas[0]["parada"] == CP_SAT_COMPLETADO
    assert len(corridas[0]["colocado"]) == 4


def test_tope_determinista_muy_chico_corta_siempre_igual_y_se_clasifica_como_limite_determinista():
    corridas = [_resolver(max_deterministic_time=1e-9) for _ in range(3)]
    assert {r["parada"] for r in corridas} == {CP_SAT_LIMITE_DETERMINISTA}
    assert len({(r["status"], r["det_time"], r["branches"], len(r["colocado"])) for r in corridas}) == 1


def test_el_resultado_con_tope_determinista_holgado_es_identico_al_clasico():
    clasico = _resolver()
    probe = _resolver(max_deterministic_time=1.0)
    assert clasico["parada"] == CP_SAT_COMPLETADO and probe["parada"] == CP_SAT_COMPLETADO
    assert clasico["status"] == probe["status"] and clasico["objetivo"] == probe["objetivo"]
    assert sorted((s, x, y, z) for s, x, y, z, _c in clasico["colocado"]) == sorted(
        (s, x, y, z) for s, x, y, z, _c in probe["colocado"])


def test_watchdog_de_pared_que_dispara_primero_queda_registrado_como_operational_timeout():
    # watchdog imposible de cumplir + tope determinista holgado -corta la pared, no el determinista
    r = _resolver(max_deterministic_time=1000.0, time_limit_s=1e-9)
    assert r["status"] != "OPTIMAL"
    assert r["parada"] == CP_SAT_TIMEOUT_OPERATIVO


def test_clasificador_de_parada():
    assert _clasificar_parada_cp_sat(True, 0.001, 0.01, 1.0, 30.0) == CP_SAT_COMPLETADO
    assert _clasificar_parada_cp_sat(False, 1.2, 0.5, 1.0, 30.0) == CP_SAT_LIMITE_DETERMINISTA
    assert _clasificar_parada_cp_sat(False, 0.3, 30.1, 1.0, 30.0) == CP_SAT_TIMEOUT_OPERATIVO
    assert _clasificar_parada_cp_sat(False, 0.3, 30.1, None, 30.0) == CP_SAT_LIMITE_TIEMPO


# ======================================================= nivel A: orquestador


def _pallet_con_torre():
    c = _cand("X", 20.0, 20.0, 20.0)
    return PalletV5(id="P", cd="CD", torres=[crear_torre(c, x=0, y=0, cantidad=1)],
                    altura_final=config.ALTURA_PALLET_VACIO + 20.0)


def _montar_orquestador(monkeypatch, *, conflictos_por_ronda=6, resultado="excedio", parada_cp=CP_SAT_COMPLETADO):
    """Orquestador REAL con `exact_local_repair`/conflictos stub: cada intento
    queda contado en `intentos`, sin CP-SAT real (rápido y determinista)."""
    llamadas = []

    def _local(pallet, por_sku, pendientes, blockers, *a, **k):
        llamadas.append(dict(k))
        if resultado == "excedio":
            return pallet, pendientes, {"excedio_max_boxes": True}
        return pallet, pendientes, {"excedio_max_boxes": False, "det_time": 0.002, "parada": parada_cp}

    monkeypatch.setattr(er, "exact_local_repair", _local)
    monkeypatch.setattr(pc, "_reconstruir_en_construccion", lambda p: object())
    monkeypatch.setattr(rs, "_rankear_conflictos",
                        lambda *a, **k: [(0, 0, 0.0, 0.0, 0.0, None, {"X"}) for _ in range(conflictos_por_ronda)])
    return llamadas


def _correr(pendientes=None, **kw):
    return exact_repair_orquestado(
        _pallet_con_torre(), {"A": [_cand("A")]}, dict({"A": 1} if pendientes is None else pendientes), {}, PRESUPUESTO, **kw,
    )


@pytest.mark.parametrize("tope", [0, 1, 3, 5])
def test_max_intentos_corta_exactamente_en_la_frontera(monkeypatch, tope):
    llamadas = _montar_orquestador(monkeypatch, conflictos_por_ronda=6)
    _p, sin, stats = _correr(max_intentos=tope)
    assert stats["intentos"] == tope == len(llamadas)       # NUNCA el intento tope+1 (tope duro)
    assert stats["stop_reason"] == "max_attempts"
    assert sin == {"A": 1}


def test_si_el_espacio_se_agota_antes_del_tope_termina_por_espacio_agotado(monkeypatch):
    llamadas = _montar_orquestador(monkeypatch, conflictos_por_ronda=2)
    _p, sin, stats = _correr(max_intentos=500)
    assert stats["intentos"] == len(llamadas) == 2
    assert stats["stop_reason"] == "espacio_agotado" and sin == {"A": 1}


def test_si_no_quedan_pendientes_termina_por_solucion(monkeypatch):
    _montar_orquestador(monkeypatch)
    _p, sin, stats = _correr(pendientes={}, max_intentos=500)
    assert stats["intentos"] == 0 and stats["stop_reason"] == "solucion" and sin == {}


def test_sin_max_intentos_el_orquestador_es_el_de_siempre(monkeypatch):
    llamadas = _montar_orquestador(monkeypatch, conflictos_por_ronda=6)
    _p, _s, stats = _correr()
    assert stats["intentos"] == 6 == len(llamadas)
    assert stats["stop_reason"] == "espacio_agotado"
    assert all("max_deterministic_time" in k and k["max_deterministic_time"] is None for k in llamadas)


def test_el_tope_determinista_de_cp_sat_llega_a_cada_intento(monkeypatch):
    llamadas = _montar_orquestador(monkeypatch, conflictos_por_ronda=3)
    _correr(max_intentos=500, max_deterministic_time=0.7)
    assert [k["max_deterministic_time"] for k in llamadas] == [0.7] * 3


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_reloj_rapido_o_lento_no_cambia_los_intentos_en_modo_determinista(monkeypatch, reloj):
    """Sin `deadline` el orquestador no consulta el reloj para decidir nada: con
    un reloj congelado en 0 o disparado a 1e12 el resultado es idéntico."""
    monkeypatch.setattr(er.time, "process_time", reloj)
    _montar_orquestador(monkeypatch, conflictos_por_ronda=6)
    _p, sin, stats = _correr(max_intentos=500)
    assert (stats["intentos"], stats["stop_reason"], sin) == (6, "espacio_agotado", {"A": 1})


def test_en_modo_clasico_un_reloj_disparado_si_corta_por_deadline(monkeypatch):
    """Contraste (fuera del probe): con `deadline` el reloj SÍ decide -es lo que
    P4 elimina dentro del sondeo."""
    monkeypatch.setattr(er.time, "process_time", lambda: 1e12)
    llamadas = _montar_orquestador(monkeypatch)
    _p, _s, stats = _correr(deadline=1.0)
    assert stats["intentos"] == 0 == len(llamadas) and stats["stop_reason"] == "deadline"


def test_mismo_input_mismos_intentos_y_residual(monkeypatch):
    _montar_orquestador(monkeypatch, conflictos_por_ronda=4)
    corridas = [_correr(max_intentos=500)[1:] for _ in range(3)]
    claves = ("intentos", "exitos", "excedio_max_boxes", "stop_reason", "cajas_recuperadas")
    firmas = [(c[0], tuple(c[1][k] for k in claves)) for c in corridas]
    assert firmas[0] == firmas[1] == firmas[2]


def test_operational_timeout_se_registra_y_se_loguea_sin_confundirse_con_un_resultado_normal(monkeypatch, caplog):
    _montar_orquestador(monkeypatch, conflictos_por_ronda=2, resultado="cp", parada_cp=CP_SAT_TIMEOUT_OPERATIVO)
    with caplog.at_level(logging.WARNING, logger="src.exact_repair"):
        _p, _s, stats = _correr(max_intentos=500, max_deterministic_time=1.0)
    assert stats["operational_timeouts"] == 2
    assert any("OPERATIONAL_TIMEOUT" in r.message for r in caplog.records)


def test_los_limites_deterministas_alcanzados_se_cuentan_aparte(monkeypatch):
    _montar_orquestador(monkeypatch, conflictos_por_ronda=2, resultado="cp", parada_cp=CP_SAT_LIMITE_DETERMINISTA)
    _p, _s, stats = _correr(max_intentos=500, max_deterministic_time=1.0)
    assert stats["cp_deterministic_limit_hits"] == 2 and stats["operational_timeouts"] == 0
    assert stats["cp_solves"] == 2 and stats["cp_det_time_max"] == pytest.approx(0.002)


# =================================================== propagación del contexto


def test_constantes_y_defaults():
    assert bnp.PROBE_EXACT_MAX_ATTEMPTS == 500
    assert 0.05 <= bnp.PROBE_EXACT_MAX_DET_TIME <= 1.0
    firma = inspect.signature(exact_repair_orquestado).parameters
    assert firma["max_intentos"].default is None and firma["max_deterministic_time"].default is None
    firma = inspect.signature(pb._empacar_n_pallets).parameters
    assert firma["presupuesto_exact_intentos"].default is None and firma["exact_max_deterministic_time"].default is None


def test_probe_pasa_el_presupuesto_de_exact(monkeypatch):
    capturado = {}

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        capturado.update(kw)
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    bnp.probe(1, {"A": 5}, {"A": [_cand("A")]}, {}, {"A": 1}, {}, "TEST", [0], False)
    assert capturado["presupuesto_exact_intentos"] == bnp.PROBE_EXACT_MAX_ATTEMPTS == 500
    assert capturado["exact_max_deterministic_time"] == bnp.PROBE_EXACT_MAX_DET_TIME


def test_final_y_pallets_objetivo_no_reciben_override_de_exact(monkeypatch):
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
    assert sondeos and all(kw["presupuesto_exact_intentos"] == 500 for kw in sondeos)
    assert finales and all("presupuesto_exact_intentos" not in kw and "exact_max_deterministic_time" not in kw
                           for kw in finales)

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
    assert llamadas and all("presupuesto_exact_intentos" not in kw for kw in llamadas)


def _stub_etapas_previas(monkeypatch, sin_colocar_repair=None):
    monkeypatch.setattr(rs, "rescue_solver", lambda p, s, *a, **k: (p, s, {}))
    monkeypatch.setattr(rp, "repair_solver", lambda p, s, *a, **k: (p, s if sin_colocar_repair is None else sin_colocar_repair, {}))
    monkeypatch.setattr(gr, "global_rescue", lambda p, s, *a, **k: (p, s, {}))


def _empacar_n_con_exact(**kw):
    por_sku = {
        "A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)],
        "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)],
    }
    return pb._empacar_n_pallets(
        {"A": 5000, "B": 5000}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 3,
        paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw,
    )


def test_empacar_n_pallets_envia_kwargs_de_exact_solo_en_modo_determinista(monkeypatch):
    _stub_etapas_previas(monkeypatch)
    vistos = []

    def _exact(pallet, por_sku, sin_colocar, *a, **k):
        vistos.append(dict(k))
        return pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}

    monkeypatch.setattr(er, "exact_repair_orquestado", _exact)

    _empacar_n_con_exact()                                                    # clásico (final / Pallets_Objetivo)
    _empacar_n_con_exact(presupuesto_exact_intentos=500, exact_max_deterministic_time=0.5)  # probe

    clasico, probe = vistos[:3], vistos[3:]
    assert len(clasico) == len(probe) == 3
    assert all("deadline" in k and "max_intentos" not in k and "max_deterministic_time" not in k for k in clasico)
    assert all(k["max_intentos"] == 500 and k["max_deterministic_time"] == 0.5 and "deadline" not in k for k in probe)


def test_el_tope_de_intentos_es_compartido_entre_los_pallets_del_cd(monkeypatch):
    _stub_etapas_previas(monkeypatch)
    restantes = []

    def _exact(pallet, por_sku, sin_colocar, *a, max_intentos=None, **k):
        restantes.append(max_intentos)
        return pallet, sin_colocar, {"intentos": 4, "exitos": 0, "cajas_recuperadas": 0}

    monkeypatch.setattr(er, "exact_repair_orquestado", _exact)
    _empacar_n_con_exact(presupuesto_exact_intentos=10, exact_max_deterministic_time=0.5)
    assert restantes == [10, 6, 2]  # cada pallet recibe lo que queda del presupuesto del CD


def test_el_tope_compartido_corta_las_llamadas_siguientes_en_la_frontera(monkeypatch):
    _stub_etapas_previas(monkeypatch)
    restantes = []

    def _exact(pallet, por_sku, sin_colocar, *a, max_intentos=None, **k):
        restantes.append(max_intentos)
        return pallet, sin_colocar, {"intentos": max_intentos, "exitos": 0, "cajas_recuperadas": 0,
                                     "stop_reason": "max_attempts"}

    monkeypatch.setattr(er, "exact_repair_orquestado", _exact)
    pallets, _sin = _empacar_n_con_exact(presupuesto_exact_intentos=7, exact_max_deterministic_time=0.5)
    assert restantes == [7]  # agotado: el segundo y tercer pallet ni se intentan
    assert pallets[-1].metadata["exact_repair_stats"]["stop_reason"] == "max_attempts"
    assert pallets[-1].metadata["exact_repair_stats"]["intentos"] == 7


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_reloj_rapido_o_lento_no_cambia_los_intentos_de_exact_en_el_probe(monkeypatch, reloj):
    """Con `process_time` congelado o disparado, el probe produce los mismos
    intentos: ni el lazo por pallets ni el orquestador consultan el reloj."""
    _stub_etapas_previas(monkeypatch)
    _montar_orquestador(monkeypatch, conflictos_por_ronda=5)
    monkeypatch.setattr(pb.time, "process_time", reloj)
    monkeypatch.setattr(er.time, "process_time", reloj)
    pallets, _sin = _empacar_n_con_exact(presupuesto_exact_intentos=500, exact_max_deterministic_time=0.5)
    st = pallets[-1].metadata["exact_repair_stats"]
    # 5 conflictos x 2 SKUs faltantes x pallets
    assert st["intentos"] == 5 * 2 * len(pallets) and st["stop_reason"] == "espacio_agotado"


def test_mismo_input_mismos_intentos_y_residual_en_el_probe(monkeypatch):
    _stub_etapas_previas(monkeypatch)
    _montar_orquestador(monkeypatch, conflictos_por_ronda=5)
    corridas = []
    for _ in range(3):
        pallets, sin = _empacar_n_con_exact(presupuesto_exact_intentos=500, exact_max_deterministic_time=0.5)
        st = pallets[-1].metadata["exact_repair_stats"]
        corridas.append((st["intentos"], st["stop_reason"], tuple(sorted(sin.items()))))
    assert corridas[0] == corridas[1] == corridas[2]


def test_global_recibe_exactamente_el_residual_de_exact(monkeypatch):
    entradas_global = []
    _stub_etapas_previas(monkeypatch, sin_colocar_repair={"A": 9})
    monkeypatch.setattr(er, "exact_repair_orquestado",
                        lambda pallet, por_sku, sin, *a, **k: (pallet, {"A": 5}, {"intentos": 1, "exitos": 1, "cajas_recuperadas": 4}))
    monkeypatch.setattr(gr, "global_rescue", lambda p, s, *a, **k: (entradas_global.append(dict(s)), (p, s, {}))[1])
    monkeypatch.setattr(rs, "_score_solucion", lambda total, *a, **k: (total,))
    _empacar_n_con_exact(presupuesto_exact_intentos=500, exact_max_deterministic_time=0.5)
    assert entradas_global and entradas_global[0] == {"A": 5}


def test_exact_clasico_conserva_deadline_de_cpu_y_watchdog_de_30s():
    """No se tocó el camino clásico: el orquestador sigue recibiendo `deadline`
    de CPU-time y CP-SAT conserva `max_time_in_seconds = time_limit_s` (30 s)."""
    fuente = inspect.getsource(er)
    assert "solver.parameters.max_time_in_seconds = time_limit_s" in fuente
    assert er.EXACT_REPAIR_TIME_MAX_SECONDS == 30.0
    assert inspect.signature(resolver_cp_sat).parameters["time_limit_s"].default == 30.0
