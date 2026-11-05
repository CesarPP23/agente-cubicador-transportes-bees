"""[V6.13-P1B2-R4 -"Global FIXED_N natural termination"] Global del camino profundo de N fijo deja de estar gobernado por su deadline de CPU
(180 s): termina por sus condiciones naturales (`completo` / `estancado`) y solo lo vigila un watchdog de CPU de seguridad. Tests rápidos y
sintéticos (sin segundos reales: relojes falsos). Los gates con BK52/BK53/Golden 6 viven en el informe de validación."""
import inspect
import time

import pytest

import config
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from src.medidor_trabajo import RelojTrabajoConWatchdog
from src.torres import TorreCandidate

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, cantidad_disponible, 1.0)


_POR_SKU = {"A": [_cand("A", 60, 50, 20, 3)], "B": [_cand("B", 40, 30, 15, 5)], "C": [_cand("C", 25, 25, 10, 8)], "D": [_cand("D", 80, 90, 25, 2)]}
_SIN = {"A": 3, "B": 5, "C": 8, "D": 2}


def _global(por_sku=None, sin=None, n=2, **kw):
    por_sku = _POR_SKU if por_sku is None else por_sku
    sin = _SIN if sin is None else sin
    return gr.global_rescue(
        pallets=[], sin_colocar=dict(sin), por_sku=por_sku, capacidad_cama_por_sku={}, nivel_por_sku={k: 6 for k in por_sku},
        tope_pallet_por_sku={}, n_pallets=n, cd="SINTETICO_R4", presupuesto=PRESUPUESTO, **kw,
    )


def _firma(pallets):
    return sorted(sorted((t.sku, t.cantidad) for t in p.torres) for p in pallets)


def _con_imposible():
    por_sku = {**_POR_SKU, "X": [_cand("X", 200, 200, 20, 1)]}  # footprint mayor que el pallet: nunca se puede colocar
    return por_sku, {**_SIN, "X": 1}


# ------------------------------------------------------------------------------------------------ Global: terminación natural


def test_el_modo_natural_termina_en_completo_y_registra_trabajo_estados_y_watchdog():
    pallets, faltantes, st = _global(watchdog_cpu_segundos=3600.0)
    p = st["presupuesto"]
    assert st["motivo_stop"] == "completo" and faltantes == {}
    assert p["modo"] == "terminacion_natural" and p["motivo_stop"] == "completo"
    assert p["watchdog_disparado"] is False and p["watchdog_cpu_segundos"] == 3600.0
    assert p["expansiones_trabajo"] > 0 and st["estados_generados"] > 0  # EXPANSIONES y ESTADOS son métricas distintas
    assert p["expansiones_trabajo"] != st["estados_generados"]


def test_el_modo_natural_puede_terminar_en_estancado():
    por_sku, sin = _con_imposible()
    _, faltantes, st = _global(por_sku, sin, watchdog_cpu_segundos=3600.0)
    assert st["motivo_stop"] == "estancado" and st["presupuesto"]["motivo_stop"] == "estancado"
    assert faltantes.get("X") == 1 and st["presupuesto"]["watchdog_disparado"] is False
    assert [r["motivo_stop"] for r in st["reinicios"]] == ["estancado"] * 3  # el multi-start sigue igual: los 3 reinicios corren


def test_el_modo_natural_da_el_mismo_resultado_que_el_modo_cpu_de_siempre():
    for args in ((None, None), _con_imposible()):
        p_cpu, f_cpu, s_cpu = _global(*args)
        p_nat, f_nat, s_nat = _global(*args, watchdog_cpu_segundos=3600.0)
        assert _firma(p_nat) == _firma(p_cpu) and f_nat == f_cpu
        assert s_nat["estados_generados"] == s_cpu["estados_generados"] and s_nat["motivo_stop"] == s_cpu["motivo_stop"]
        assert s_nat["reinicios"] == s_cpu["reinicios"]


def test_el_trabajo_natural_es_repetible_y_no_depende_del_reloj_ni_del_deadline(monkeypatch):
    base = _global(watchdog_cpu_segundos=3600.0)
    assert [_global(watchdog_cpu_segundos=3600.0)[2]["presupuesto"]["expansiones_trabajo"] for _ in range(2)] == [base[2]["presupuesto"]["expansiones_trabajo"]] * 2
    # el `deadline` del caller (vencido) se IGNORA en este modo
    vencido = _global(watchdog_cpu_segundos=3600.0, deadline=time.process_time() - 1.0)
    assert vencido[2]["presupuesto"]["expansiones_trabajo"] == base[2]["presupuesto"]["expansiones_trabajo"] and vencido[1] == base[1]
    # sin el modo natural, en cambio, un deadline vencido corta de inmediato (comportamiento de siempre)
    assert _global(deadline=time.process_time() - 1.0)[2]["motivo_stop"] == "timeout"
    # relojes falsos que no avanzan / retroceden: el resultado no cambia
    for reloj in (lambda: 0.0, lambda: -5.0):
        monkeypatch.setattr(time, "process_time", reloj)
        otra = _global(watchdog_cpu_segundos=3600.0)
        assert otra[2]["presupuesto"]["expansiones_trabajo"] == base[2]["presupuesto"]["expansiones_trabajo"]
        assert _firma(otra[0]) == _firma(base[0]) and otra[2]["motivo_stop"] == base[2]["motivo_stop"]


def test_el_watchdog_no_gobierna_la_ejecucion_normal():
    for args in ((None, None), _con_imposible()):
        st = _global(*args, watchdog_cpu_segundos=1800.0)[2]
        assert st["presupuesto"]["watchdog_disparado"] is False and st["motivo_stop"] != "watchdog"


def test_un_watchdog_artificialmente_pequeno_dispara_y_queda_registrado():
    pallets, faltantes, st = _global(watchdog_cpu_segundos=-1.0)
    p = st["presupuesto"]
    assert p["watchdog_disparado"] is True and p["motivo_stop"] == "watchdog" and st["motivo_stop"] == "watchdog"
    assert p["expansiones_trabajo"] == 0 and faltantes == _SIN  # cortó antes de expandir: el gate lo detecta, no se hace pasar por natural


def test_el_watchdog_con_reloj_falso_que_avanza_corta_en_el_siguiente_borde_de_profundidad(monkeypatch):
    reloj = {"t": 0.0}
    monkeypatch.setattr(time, "process_time", lambda: reloj["t"])
    original = gr._expandir_estado
    n = []

    def _cuenta(*a, **k):
        n.append(1)
        reloj["t"] += 10.0  # cada expansión "gasta" 10 s de CPU falsos
        return original(*a, **k)

    monkeypatch.setattr(gr, "_expandir_estado", _cuenta)
    _, _, st = _global(watchdog_cpu_segundos=25.0)
    assert st["presupuesto"]["watchdog_disparado"] is True and st["motivo_stop"] == "watchdog"
    assert len(n) == st["presupuesto"]["expansiones_trabajo"]


def test_argumentos_incompatibles_se_rechazan():
    with pytest.raises(ValueError):
        _global(watchdog_cpu_segundos=3600.0, presupuesto_expansiones=10)


def test_los_defaults_no_cambian_el_comportamiento_de_siempre():
    sig = inspect.signature(gr.global_rescue).parameters
    assert sig["watchdog_cpu_segundos"].default is None and sig["presupuesto_expansiones"].default is None
    _, _, st = _global()
    assert "presupuesto" not in st  # sin la bandera no hay bloque nuevo en las stats


def test_con_presupuesto_de_expansiones_global_sigue_como_siempre():
    """Global final / OPEN (presupuesto_expansiones): sin cambios -corta por trabajo, no tiene watchdog, no tiene bloque `presupuesto`."""
    completo = _global(presupuesto_expansiones=10_000)
    cortado = _global(presupuesto_expansiones=2)
    assert cortado[2]["motivo_stop"] == "timeout" and completo[2]["motivo_stop"] == "completo"
    assert "presupuesto" not in cortado[2] and "presupuesto" not in completo[2]


def test_la_cota_estructural_es_solo_telemetria_y_no_corta():
    _, _, st = _global(watchdog_cpu_segundos=3600.0)
    p = st["presupuesto"]
    cajas = sum(_SIN.values())
    assert p["cota_estructural_observada"] == (128 + 64 + 32) * cajas == 224 * cajas
    assert p["expansiones_trabajo"] < p["cota_estructural_observada"]
    # no hay NINGUNA segunda frontera funcional: el único `limite_tiempo` del modo es SIN_TOPE
    assert RelojTrabajoConWatchdog.SIN_TOPE == 1e30
    fuente = inspect.getsource(gr.global_rescue)
    assert "limite_tiempo = RelojTrabajoConWatchdog.SIN_TOPE" in fuente and "cota" not in fuente.split("limite_tiempo")[1].split("else:")[0]


# ------------------------------------------------------------------------------------------------ cableado en _empacar_n_pallets


def _stub_cascada(monkeypatch, recibidos, global_stats=None):
    def _rescue_espia(pallets, sin_colocar, *a, **k):
        recibidos["rescue"] = dict(k)
        return pallets, sin_colocar, {"presupuesto": {"modo": "agotamiento_natural", "nodos_trabajo": 11, "watchdog_disparado": False,
                                                    "motivo_stop": "sin_progreso"}} if "watchdog_cpu_segundos" in k else {}

    def _repair_espia(pallets, sin_colocar, *a, **k):
        recibidos["repair"] = dict(k)
        return pallets, sin_colocar, {}

    def _exact_espia(pallet, por_sku, sin_colocar, *a, **k):
        recibidos.setdefault("exact", []).append(dict(k))
        return pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}

    def _global_espia(pallets, sin_colocar, *a, **k):
        recibidos["global"] = dict(k)
        return pallets, sin_colocar, dict(global_stats if global_stats is not None else {"motivo_stop": "completo", "estados_generados": 7})

    monkeypatch.setattr(rs, "rescue_solver", _rescue_espia)
    monkeypatch.setattr(rp, "repair_solver", _repair_espia)
    monkeypatch.setattr(er, "exact_repair_orquestado", _exact_espia)
    monkeypatch.setattr(gr, "global_rescue", _global_espia)


def _sin_deadline(kw):  # `deadline` y `contador` (ids de pallet) no son parte del gobierno de la etapa
    return {k: v for k, v in kw.items() if k not in ("deadline", "contador")}


def _empacar_n(n_pallets=1, **kw):
    por_sku = {
        "A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)],
        "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 400, 1.0)],
    }
    return pb._empacar_n_pallets(
        {"A": 400, "B": 400}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], n_pallets,
        paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw,
    )


_PRES_GLOBAL = {"modo": "terminacion_natural", "expansiones_trabajo": 4388, "watchdog_cpu_segundos": 1800.0, "watchdog_disparado": False,
                "motivo_stop": "completo", "cota_estructural_observada": 25536}


def test_el_gobernador_profundo_pasa_el_watchdog_a_global_y_deja_repair_y_exact_como_siempre(monkeypatch):
    rec = {}
    _stub_cascada(monkeypatch, rec, global_stats={"motivo_stop": "completo", "estados_generados": 32364, "presupuesto": dict(_PRES_GLOBAL)})
    pallets, _ = _empacar_n(gobernador_profundo=True)

    assert pb.FIXED_N_DEEP_GLOBAL_WATCHDOG_SECONDS == 1800.0
    assert _sin_deadline(rec["global"]) == {"watchdog_cpu_segundos": 1800.0}  # sin presupuesto de expansiones, `deadline` viaja pero se ignora
    assert _sin_deadline(rec["rescue"]) == {"watchdog_cpu_segundos": 1800.0}  # Rescue: como en R1
    # Repair / Exact: exactamente lo de siempre (deadlines de CPU, nada de trabajo)
    assert _sin_deadline(rec["repair"]) == {} and 80 < rec["repair"]["deadline"] - time.process_time() < 91
    assert all(set(k) == {"deadline"} and 80 < k["deadline"] - time.process_time() < 91 for k in rec["exact"])

    gob = pallets[-1].metadata["fixed_n_deep_governor"]
    assert gob["activo"] is True and gob["modo"] == "rescue_global_terminacion_natural"
    assert gob["watchdog_triggered"] is False and gob["watchdog_stages"] == []
    assert gob["etapas"]["rescue"] == {"trabajo": 11, "unidad": "visitas", "stop_reason": "sin_progreso", "watchdog_triggered": False}
    assert gob["etapas"]["global"] == {
        "trabajo": 4388, "unidad": "expansiones", "estados_generados": 32364, "stop_reason": "completo", "watchdog_triggered": False,
        "watchdog_cpu_segundos": 1800.0, "structural_bound_observed": 25536,
    }


def test_si_dispara_el_watchdog_de_global_queda_en_la_metadata_y_en_el_log(monkeypatch, caplog):
    rec = {}
    disparado = {**_PRES_GLOBAL, "watchdog_disparado": True, "motivo_stop": "watchdog", "expansiones_trabajo": 12}
    _stub_cascada(monkeypatch, rec, global_stats={"motivo_stop": "watchdog", "estados_generados": 90, "presupuesto": disparado})
    with caplog.at_level("WARNING", logger=pb.__name__):
        pallets, _ = _empacar_n(gobernador_profundo=True)
    gob = pallets[-1].metadata["fixed_n_deep_governor"]
    assert gob["watchdog_triggered"] is True and gob["watchdog_stages"] == ["global"]
    assert gob["etapas"]["global"]["watchdog_triggered"] is True and gob["etapas"]["global"]["stop_reason"] == "watchdog"
    assert gob["etapas"]["rescue"]["watchdog_triggered"] is False
    assert any("WATCHDOG" in r.message and "global" in r.message for r in caplog.records)


def test_sin_la_bandera_global_sigue_por_cpu_como_siempre(monkeypatch):
    rec = {}
    _stub_cascada(monkeypatch, rec)
    pallets, _ = _empacar_n()
    assert _sin_deadline(rec["global"]) == {} and rec["global"]["deadline"] - time.process_time() < 181
    assert "fixed_n_deep_governor" not in pallets[-1].metadata


def test_open_y_final_con_presupuestos_conservan_su_politica_de_global(monkeypatch):
    # sondeo OPEN (presupuestos de Rescue/Repair/Exact): Global por CPU como siempre, sin watchdog
    rec = {}
    _stub_cascada(monkeypatch, rec)
    pallets, _ = _empacar_n(gobernador_profundo=True, presupuesto_rescue_nodos=777, presupuesto_repair_nodos=5, presupuesto_exact_intentos=3)
    assert _sin_deadline(rec["global"]) == {} and "fixed_n_deep_governor" not in pallets[-1].metadata
    # materialización final (presupuesto_global_expansiones): Global por trabajo, sin watchdog
    rec = {}
    _stub_cascada(monkeypatch, rec)
    pallets, _ = _empacar_n(gobernador_profundo=True, presupuesto_global_expansiones=9)
    assert _sin_deadline(rec["global"]) == {"presupuesto_expansiones": 9} and "fixed_n_deep_governor" not in pallets[-1].metadata
    assert "watchdog_cpu_segundos" not in rec["rescue"]
