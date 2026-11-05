"""[V6.13-P1B2-R1 -"Rescue natural exhaustion"] Rescue del camino profundo de N fijo deja de estar gobernado por su deadline de CPU de 90 s: termina
por sus condiciones naturales (solución / ronda sin progreso) y solo lo vigila un watchdog de CPU de seguridad. [R2] Sus DFS usan P1-A (su trabajo
no depende del CPU: mismo conteo de trabajo, mismo motivo de parada, mismo resultado). Repair,
Exact y Global conservan su gobernador de siempre; sondeo / materialización final no se tocan; no hay ningún presupuesto fijo de visitas."""
import inspect
import math
import time

import pandas as pd
import pytest

import config
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from models import PalletV5
from src.medidor_trabajo import MedidorTrabajo, RelojTrabajoConWatchdog
from src.packing_bloques import _resolver_pallets_backtracking
from src.packing_columnar import _PalletEnConstruccion
from src.repair_solver import repair_solver
from src.rescue_solver import rescue_solver
from src.torres import TorreCandidate, crear_torre

PRESUPUESTO_ALTURA = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10):
    return TorreCandidate(sku, "CD", "LxA", largo, ancho, alto, 10, cantidad_disponible, 1.0)


def _escenario_grande_bloqueado():
    """GRANDE queda bloqueado por dos muros; Rescue / Repair necesitan ruina dirigida (consumen visitas) para resolver / rendirse."""
    wall1_cand = _cand("WALL1", 82.0, 104.0, PRESUPUESTO_ALTURA)
    wall1 = crear_torre(wall1_cand, x=40, y=-2, cantidad=1)
    wall2_cand = _cand("WALL2", 42.0, 72.0, PRESUPUESTO_ALTURA)
    wall2 = crear_torre(wall2_cand, x=-2, y=30, cantidad=1)
    chico_a = _cand("A", 20, 30, 15)
    chico_b = _cand("B", 20, 30, 15)
    torre_a = crear_torre(chico_a, x=0, y=0, cantidad=1)
    torre_b = crear_torre(chico_b, x=20, y=0, cantidad=1)
    pallet = PalletV5(id="P1", cd="BK31", torres=[wall1, wall2, torre_a, torre_b],
                      altura_final=config.ALTURA_PALLET_VACIO + PRESUPUESTO_ALTURA)
    grande = _cand("GRANDE", 40, 30, 15)
    por_sku = {"GRANDE": [grande], "A": [chico_a], "B": [chico_b], "WALL1": [wall1_cand], "WALL2": [wall2_cand]}
    nivel = {k: 6 for k in por_sku}
    return [pallet], {"GRANDE": 1}, por_sku, nivel, PRESUPUESTO_ALTURA, 1


def _rescue(**kw):
    pallets, sin_colocar, por_sku, nivel, presupuesto, n = _escenario_grande_bloqueado()
    final, sin, stats = rescue_solver(pallets, sin_colocar, por_sku, {}, nivel, {}, n, presupuesto, **kw)
    firma = sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for t in final[0].torres)
    return sin, stats, firma


def _repair(**kw):
    pallets, sin_colocar, por_sku, nivel, presupuesto, n = _escenario_grande_bloqueado()
    final, sin, stats = repair_solver(pallets, sin_colocar, por_sku, {}, nivel, {}, n, presupuesto, **kw)
    firma = sorted((p.id, t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for p in final for t in p.torres)
    return sin, stats, firma



def _escenario_sin_solucion():
    """El SKU crítico no cabe en el pallet (huella > pallet): Rescue no puede progresar nunca => termina por `sin_progreso`."""
    pallets, _, por_sku, nivel, presupuesto, n = _escenario_grande_bloqueado()
    enorme = _cand("ENORME", 500.0, 500.0, 15)
    por_sku = {**por_sku, "ENORME": [enorme]}
    return pallets, {"ENORME": 1}, {**por_sku}, {**nivel, "ENORME": 6}, presupuesto, n


# ------------------------------------------------------------------------------------------------ contrato


def test_no_hay_presupuesto_fijo_de_visitas_ni_logica_por_cd():
    assert not hasattr(pb, "FIXED_N_DEEP_RESCUE_MAX_NODES")
    assert not hasattr(pb, "FIXED_N_DEEP_REPAIR_MAX_NODES")
    assert not hasattr(pb, "FIXED_N_DEEP_EXACT_MAX_ATTEMPTS")
    codigo = inspect.getsource(pb._empacar_n_pallets) + inspect.getsource(rescue_solver)
    for cd in ("BK31", "BK52", "BK53"):
        assert cd not in codigo
    # el watchdog de seguridad es holgado: 5,4x el CPU natural de BK52 (~335 s medidos sin P1-A) y mucho mayor que el viejo deadline funcional de 90 s
    assert pb.FIXED_N_DEEP_RESCUE_WATCHDOG_SECONDS == 1800.0
    assert pb.FIXED_N_DEEP_RESCUE_WATCHDOG_SECONDS >= 5 * 335  # barrera extrema: >= 5x el CPU natural medido de BK52 (no un budget)


def test_defaults_no_cambian_el_comportamiento_de_siempre():
    assert inspect.signature(rescue_solver).parameters["watchdog_cpu_segundos"].default is None
    assert inspect.signature(rescue_solver).parameters["presupuesto_nodos"].default is None
    assert inspect.signature(pb._empacar_n_pallets).parameters["gobernador_profundo"].default is False
    assert "watchdog_cpu_segundos" not in inspect.signature(repair_solver).parameters  # Repair no se migra en R1


# ------------------------------------------------------------------------------------------------ el reloj


def test_reloj_con_watchdog_cuenta_trabajo_y_sin_tope_nunca_corta():
    r = RelojTrabajoConWatchdog(time.process_time() + 3600.0)
    limite = RelojTrabajoConWatchdog.SIN_TOPE
    assert r() == 0.0 and r() < limite and not (r() > limite)
    r.registrar_nodos(10**9)
    assert r.nodos == 10**9 and r() < limite and not (r() > limite) and r.watchdog_disparado is False


def test_reloj_con_watchdog_vencido_devuelve_inf_y_queda_marcado():
    r = RelojTrabajoConWatchdog(time.process_time() - 1.0)
    assert r.watchdog_disparado is False
    assert r() == math.inf and r.watchdog_disparado is True
    limite = RelojTrabajoConWatchdog.SIN_TOPE
    assert r() > limite and not (r() < limite)  # ambos chequeos de las etapas cortan


def test_el_reloj_con_watchdog_hereda_p1a_del_medidor_de_trabajo():
    assert MedidorTrabajo.permite_p1a is True
    assert RelojTrabajoConWatchdog.permite_p1a is True
    assert isinstance(RelojTrabajoConWatchdog(0.0), MedidorTrabajo)  # mismo contrato de registro de nodos


# ------------------------------------------------------------------------------------------------ P1-A queda ENCENDIDO en el Rescue (R2)


def _dfs_escenario(reloj, espia):
    def _c(sku, largo, ancho, alto, cant, peso):
        return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, cant, peso)

    por_sku = {"A": [_c("A", 40, 30, 20, 60, 0.1)], "B": [_c("B", 20, 15, 12, 90, 0.37)], "C": [_c("C", 30, 40, 15, 40, 1.13)]}
    pendientes = {"A": 60, "B": 90, "C": 40}
    construcciones = [_PalletEnConstruccion(pallet=PalletV5(id=f"PV5-TEST-{i:03d}", cd="TEST")) for i in range(2)]
    colocados = [{}, {}]
    _resolver_pallets_backtracking(construcciones, colocados, pendientes, por_sku, {}, {}, {}, PRESUPUESTO_ALTURA, 2, max_nodos=80, reloj=reloj)
    return sorted((p.pallet.id, t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2),
                   p.pallet.altura_final, p.pallet.peso_estimado, p.pallet.ocupacion_xy, p.pallet.volumen_utilizado)
                  for p in construcciones for t in p.pallet.torres)


@pytest.mark.parametrize("clase,difiere", [("trabajo", True), ("trabajo_b2", True), ("cpu", False)])
def test_p1a_se_activa_con_medidor_de_trabajo_y_con_el_reloj_del_rescue_pero_no_con_cpu(monkeypatch, clase, difiere):
    original = pb._restaurar_estado_pallets
    llamadas = []
    monkeypatch.setattr(pb, "_restaurar_estado_pallets", lambda *a, **k: (llamadas.append(k.get("diferir_metricas", False)), original(*a, **k))[1])
    memos = []
    original_memo = pb._area_union_memoizada
    monkeypatch.setattr(pb, "_area_union_memoizada", lambda: (memos.append(1), original_memo())[1])

    reloj = {"trabajo": MedidorTrabajo, "trabajo_b2": lambda: RelojTrabajoConWatchdog(time.process_time() + 3600.0),
             "cpu": lambda: time.process_time}[clase]()
    foto = _dfs_escenario(reloj, None)
    assert any(llamadas) is difiere
    assert bool(memos) is difiere  # el memo del área sigue al mismo interruptor
    assert foto == _dfs_escenario(time.process_time, None)  # mismo estado de salida


# ------------------------------------------------------------------------------------------------ Rescue real


def test_rescue_agotamiento_natural_registra_trabajo_motivo_y_watchdog():
    sin, stats, _ = _rescue(watchdog_cpu_segundos=3600.0)
    assert sin == {}
    p = stats["presupuesto"]
    assert p["modo"] == "agotamiento_natural" and p["nodos_trabajo"] > 0 and "tope" not in p
    assert p["watchdog_cpu_segundos"] == 3600.0 and p["watchdog_disparado"] is False and p["motivo_stop"] == "solucion"


def test_rescue_sin_solucion_posible_termina_por_sin_progreso():
    pallets, sin_colocar, por_sku, nivel, presupuesto, n = _escenario_sin_solucion()
    _, sin, stats = rescue_solver(pallets, sin_colocar, por_sku, {}, nivel, {}, n, presupuesto, watchdog_cpu_segundos=3600.0)
    assert sin == {"ENORME": 1}
    assert stats["presupuesto"]["motivo_stop"] == "sin_progreso" and stats["presupuesto"]["watchdog_disparado"] is False


def test_rescue_natural_da_el_mismo_resultado_que_el_modo_tiempo_de_siempre():
    sin_t, st_t, firma_t = _rescue()
    sin_n, st_n, firma_n = _rescue(watchdog_cpu_segundos=3600.0)
    assert (sin_n, firma_n) == (sin_t, firma_t)
    assert st_n["iteraciones"] == st_t["iteraciones"] and st_n["conflictos_evaluados"] == st_t["conflictos_evaluados"]
    assert st_t["presupuesto"] == {"modo": "tiempo"}  # el modo de siempre no publica nada nuevo


def test_el_trabajo_natural_es_repetible_y_no_depende_del_reloj_del_proceso(monkeypatch):
    ref = _rescue(watchdog_cpu_segundos=3600.0)
    otra = _rescue(watchdog_cpu_segundos=3600.0)
    assert otra[1]["presupuesto"]["nodos_trabajo"] == ref[1]["presupuesto"]["nodos_trabajo"] and otra[2] == ref[2]
    # un process_time "rápido/lento" lejos del watchdog no mueve nada: manda el agotamiento natural
    for reloj in (lambda: 0.0, lambda: 1e12):
        monkeypatch.setattr(time, "process_time", reloj)
        got = _rescue(watchdog_cpu_segundos=1e15)
        assert (got[0], got[2]) == (ref[0], ref[2])
        assert got[1]["presupuesto"]["nodos_trabajo"] == ref[1]["presupuesto"]["nodos_trabajo"]


@pytest.mark.parametrize("escenario", ["con_solucion", "sin_solucion"])
def test_p1a_en_el_rescue_no_cambia_trabajo_motivo_ni_resultado(monkeypatch, escenario):
    """R2: encender P1-A dentro de Rescue conserva exactamente el conteo de trabajo, el motivo de parada y la solución (solo cambia el CPU)."""
    def _correr():
        if escenario == "con_solucion":
            sin, stats, firma = _rescue(watchdog_cpu_segundos=3600.0)
        else:
            pallets, sin_colocar, por_sku, nivel, presupuesto, n = _escenario_sin_solucion()
            final, sin, stats = rescue_solver(pallets, sin_colocar, por_sku, {}, nivel, {}, n, presupuesto, watchdog_cpu_segundos=3600.0)
            firma = sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for t in final[0].torres)
        p = stats["presupuesto"]
        return sin, firma, p["nodos_trabajo"], p["motivo_stop"], p["watchdog_disparado"], stats["iteraciones"], stats["conflictos_evaluados"]

    con_p1a = _correr()
    monkeypatch.setattr(RelojTrabajoConWatchdog, "permite_p1a", False)  # el comportamiento de R1
    sin_p1a = _correr()
    assert con_p1a == sin_p1a
    assert con_p1a[2] > 0 and con_p1a[4] is False


def test_el_rescue_usa_realmente_las_metricas_diferidas(monkeypatch):
    original = pb._restaurar_estado_pallets
    llamadas = []
    monkeypatch.setattr(pb, "_restaurar_estado_pallets", lambda *a, **k: (llamadas.append(k.get("diferir_metricas", False)), original(*a, **k))[1])
    _rescue(watchdog_cpu_segundos=3600.0)
    assert any(llamadas)  # R2: P1-A activo dentro del Rescue profundo
    llamadas.clear()
    monkeypatch.setattr(RelojTrabajoConWatchdog, "permite_p1a", False)
    _rescue(watchdog_cpu_segundos=3600.0)
    assert not any(llamadas)


def test_watchdog_vencido_corta_y_queda_registrado():
    sin, st, _ = _rescue(watchdog_cpu_segundos=-1.0)
    p = st["presupuesto"]
    assert p["watchdog_disparado"] is True and p["motivo_stop"] == "watchdog"
    assert st["iteraciones"] == 0 and p["nodos_trabajo"] == 0 and sin == {"GRANDE": 1}


def test_argumentos_incompatibles_se_rechazan():
    with pytest.raises(ValueError):
        _rescue(watchdog_cpu_segundos=3600.0, presupuesto_nodos=10)


# ------------------------------------------------------------------------------------------------ cableado en _empacar_n_pallets


def _stub_cascada(monkeypatch, recibidos, rescue_stats=None, repair_stats=None, exact=None, global_stats=None):
    def _rescue_espia(pallets, sin_colocar, *a, **k):
        recibidos["rescue"] = dict(k)
        return pallets, sin_colocar, dict(rescue_stats or {})

    def _repair_espia(pallets, sin_colocar, *a, **k):
        recibidos["repair"] = dict(k)
        return pallets, sin_colocar, dict(repair_stats or {})

    def _exact_espia(pallet, por_sku, sin_colocar, *a, **k):
        recibidos.setdefault("exact", []).append(dict(k))
        return pallet, sin_colocar, dict(exact.pop(0) if exact else {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0})

    def _global_espia(pallets, sin_colocar, *a, **k):
        recibidos["global"] = dict(k)
        return pallets, sin_colocar, dict(global_stats or {"motivo_stop": "completo", "estados_generados": 7})

    monkeypatch.setattr(rs, "rescue_solver", _rescue_espia)
    monkeypatch.setattr(rp, "repair_solver", _repair_espia)
    monkeypatch.setattr(er, "exact_repair_orquestado", _exact_espia)
    monkeypatch.setattr(gr, "global_rescue", _global_espia)


def _sin_deadline(kw):
    return {k: v for k, v in kw.items() if k != "deadline"}


def _empacar_n(n_pallets=1, **kw):
    por_sku = {
        "A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)],
        "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 400, 1.0)],
    }
    return pb._empacar_n_pallets(
        {"A": 400, "B": 400}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], n_pallets,
        paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw,
    )


def test_gobernador_profundo_solo_cambia_rescue_y_deja_repair_exact_global_como_siempre(monkeypatch):
    rec = {}
    _stub_cascada(monkeypatch, rec, rescue_stats={"presupuesto": {"modo": "agotamiento_natural", "nodos_trabajo": 55677,
                                                                "watchdog_disparado": False, "motivo_stop": "sin_progreso"}})
    pallets, _ = _empacar_n(gobernador_profundo=True)

    # Rescue: sin presupuesto de visitas ni de tiempo, solo el watchdog (`deadline` viaja por firma pero ese modo lo IGNORA)
    assert _sin_deadline(rec["rescue"]) == {"watchdog_cpu_segundos": 1800.0}
    # Repair / Exact / Global: exactamente lo de siempre (deadlines de CPU, nada de trabajo)
    assert _sin_deadline(rec["repair"]) == {} and 80 < rec["repair"]["deadline"] - time.process_time() < 91
    assert all(set(k) == {"deadline"} and 80 < k["deadline"] - time.process_time() < 91 for k in rec["exact"])
    # Global: desde V6.13-P1B2-R4 también por terminación natural + watchdog (tests/test_p1b2r4_global_natural_termination.py); acá solo se fija
    # que NO recibe presupuesto de expansiones
    assert "presupuesto_expansiones" not in rec["global"] and rec["global"]["watchdog_cpu_segundos"] == 1800.0

    gob = pallets[-1].metadata["fixed_n_deep_governor"]
    assert gob["activo"] is True and gob["modo"] == "rescue_global_terminacion_natural"
    assert gob["watchdog_triggered"] is False and gob["watchdog_stages"] == [] and gob["watchdog_cpu_segundos"] == 1800.0
    assert gob["etapas"]["rescue"] == {"trabajo": 55677, "unidad": "visitas", "stop_reason": "sin_progreso", "watchdog_triggered": False}


def test_sin_la_bandera_la_cascada_sigue_por_cpu_como_siempre(monkeypatch):
    rec = {}
    _stub_cascada(monkeypatch, rec)
    pallets, _ = _empacar_n()
    assert _sin_deadline(rec["rescue"]) == {} and _sin_deadline(rec["repair"]) == {}
    assert 80 < rec["rescue"]["deadline"] - time.process_time() < 91 and 80 < rec["repair"]["deadline"] - time.process_time() < 91
    assert "fixed_n_deep_governor" not in pallets[-1].metadata


def test_los_presupuestos_de_sondeo_o_final_tienen_prioridad_y_no_activan_el_gobernador(monkeypatch):
    for kw in ({"presupuesto_rescue_nodos": 777}, {"presupuesto_repair_nodos": 5}, {"presupuesto_exact_intentos": 3},
               {"presupuesto_global_expansiones": 9}):
        rec = {}
        _stub_cascada(monkeypatch, rec)
        pallets, _ = _empacar_n(gobernador_profundo=True, **kw)
        assert "watchdog_cpu_segundos" not in rec["rescue"] and "fixed_n_deep_governor" not in pallets[-1].metadata
    assert _sin_deadline(rec["rescue"]) == {}  # el último caso (global) deja a Rescue por CPU


def test_si_dispara_el_watchdog_queda_en_la_metadata_y_en_el_log(monkeypatch, caplog):
    rec = {}
    _stub_cascada(monkeypatch, rec, rescue_stats={"presupuesto": {"modo": "agotamiento_natural", "nodos_trabajo": 5,
                                                                "watchdog_disparado": True, "motivo_stop": "watchdog"}})
    with caplog.at_level("WARNING", logger=pb.__name__):
        pallets, _ = _empacar_n(gobernador_profundo=True)
    gob = pallets[-1].metadata["fixed_n_deep_governor"]
    assert gob["watchdog_triggered"] is True and gob["watchdog_stages"] == ["rescue"]
    assert gob["etapas"]["rescue"]["watchdog_triggered"] is True and gob["etapas"]["rescue"]["stop_reason"] == "watchdog"
    assert any("WATCHDOG" in r.message and "rescue" in r.message for r in caplog.records)


# ------------------------------------------------------------------------------------------------ quién activa el gobernador


def _df_pallets_objetivo():
    return pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": 3, "Largo_Efectivo": 30.0, "Ancho_Efectivo": 20.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "BK31",
    }])


def test_solo_el_camino_profundo_de_n_fijo_pide_el_gobernador(monkeypatch):
    llamadas = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append(dict(kw))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)

    # sin incumbent => camino profundo => gobernador_profundo=True
    monkeypatch.setattr(pb, "_exact_n_incumbent", lambda *a, **k: (None, {"incumbent": False, "motivo": "test"}))
    try:
        pb.armar_pallets_bloques(_df_pallets_objetivo(), "BK31", pallets_objetivo=1, paralelo_lns=False)
    except Exception:  # el espía devuelve vacío: solo importan los kwargs
        pass
    assert llamadas and llamadas[-1].get("gobernador_profundo") is True and llamadas[-1].get("no_reserve_fallback") is True

    # con incumbent => solo el front-end determinista (solo_frente): nunca el gobernador
    llamadas.clear()
    incumbent = [PalletV5(id="PV5-X-0", cd="BK31")]
    monkeypatch.setattr(pb, "_exact_n_incumbent", lambda *a, **k: (incumbent, {"incumbent": True}))
    try:
        pb.armar_pallets_bloques(_df_pallets_objetivo(), "BK31", pallets_objetivo=1, paralelo_lns=False)
    except Exception:
        pass
    assert llamadas and all("gobernador_profundo" not in kw for kw in llamadas)


def test_sondeo_y_final_no_reciben_el_gobernador(monkeypatch):
    import src.busqueda_n_pallets as bnp

    llamadas = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append(dict(kw))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: [PalletV5(id=f"PV5-X-{i}", cd="X") for i in range(2)])
    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_optimizado({"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0], paralelo_lns=False)
    assert llamadas and all("gobernador_profundo" not in kw for kw in llamadas)
