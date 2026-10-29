"""[PATCH V6.12-RC2-B -"EXACT_N_GREEDY_INCUMBENT"] Política FIXED_N (`Pallets_Objetivo`):

  1. `_empacar` -si cubre el 100% con EXACTAMENTE N pallets y 0 errores, es el `exact_n_incumbent` (NO se retorna todavía).
  2. Con incumbent se corre SOLO el front-end determinista (`_empacar_n_pallets(solo_frente=True)`: greedy fijo + reserva + DFS + LNS,
     todos acotados por trabajo, sin Rescue/Repair/Exact/Global). Si el front-end completa (N exacto, 100%, 0 errores) gana el
     front-end; si no, gana el incumbent y la cascada profunda NO corre.
  3. Sin incumbent (n_greedy > N, n_greedy < N, no cubre, no valida): camino profundo de siempre."""
import inspect

import pandas as pd
import pytest

import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
import src.validacion_v5 as v5
from src.torres import TorreCandidate


def _cand(sku="A"):
    # caja 60x50x20: 4 por capa, 10 capas -> 40 por pallet (presupuesto de altura 205,08)
    return TorreCandidate(sku, "CD", "L×A", 60.0, 50.0, 20.0, 20, 10_000, 1.0)


def _incumbent(demanda, n_objetivo):
    por_sku = {"A": [_cand()]}
    return pb._exact_n_incumbent({"A": demanda}, por_sku, {}, {"A": 1}, {}, pb._altura_presupuesto(), "T", [0], n_objetivo)


# ----------------------------------------------------------------- _exact_n_incumbent (unidad)


def test_n_greedy_igual_a_n_produce_el_incumbent_sin_retornarlo_como_final():
    pallets, info = _incumbent(60, 2)
    assert pallets is not None and len(pallets) == 2
    assert sum(t.cantidad for p in pallets for t in p.torres) == 60
    assert info["incumbent"] is True and info["motivo"] == "n_greedy==N" and info["errores_geometricos"] == 0


@pytest.mark.parametrize("n_objetivo,motivo", [(1, "n_greedy>N"), (3, "n_greedy<N")])
def test_n_distinto_no_hay_incumbent_y_el_caso_queda_registrado(n_objetivo, motivo):
    pallets, info = _incumbent(60, n_objetivo)
    assert pallets is None and info["incumbent"] is False and info["motivo"] == motivo and info["n_greedy"] == 2


def test_si_la_validacion_geometrica_falla_no_hay_incumbent(monkeypatch):
    monkeypatch.setattr(v5, "validar_pallet_v5", lambda p: ["error_sintetico"])
    pallets, info = _incumbent(60, 2)
    assert pallets is None and info["motivo"] == "validacion_geometrica_fallida"


def test_demanda_que_el_greedy_no_cubre_no_es_incumbent(monkeypatch):
    original = pb._empacar
    monkeypatch.setattr(pb, "_empacar", lambda pend, *a, **k: original(pend, *a, **k)[:1])
    pallets, info = _incumbent(60, 2)
    assert pallets is None and info["motivo"] == "greedy_no_cubre_el_100%"


# ------------------------------------------------ solo_frente: modo interno explícito (no un timeout corto)


def _escenario_inalcanzable():
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)]}
    return por_sku, {"A": 5000, "B": 5000}


def _n_pallets(**kw):
    por_sku, pend = _escenario_inalcanzable()
    return pb._empacar_n_pallets(dict(pend), por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, max_nodos_dfs=40,
                                 lns_recon_max_nodos=10, lns_sin_mejora_max=2, **kw)


def _espiar_cascada(monkeypatch):
    llamadas = {"rescue": 0, "repair": 0, "exact": 0, "global": 0}

    def _mk(nombre, ret):
        def f(*a, **k):
            llamadas[nombre] += 1
            return ret(a)
        return f

    monkeypatch.setattr(rs, "rescue_solver", _mk("rescue", lambda a: (a[0], a[1], {})))
    monkeypatch.setattr(rp, "repair_solver", _mk("repair", lambda a: (a[0], a[1], {})))
    monkeypatch.setattr(er, "exact_repair_orquestado", _mk("exact", lambda a: (a[0], a[2], {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0})))
    monkeypatch.setattr(gr, "global_rescue", _mk("global", lambda a: (a[0], a[1], {})))
    return llamadas


def test_solo_frente_se_detiene_antes_de_rescue_repair_exact_global(monkeypatch):
    llamadas = _espiar_cascada(monkeypatch)
    pallets, sin = _n_pallets(solo_frente=True)
    assert sin and llamadas == {"rescue": 0, "repair": 0, "exact": 0, "global": 0}
    # control: sin solo_frente la cascada SÍ corre sobre el mismo escenario
    _n_pallets()
    assert llamadas["rescue"] == 1 and llamadas["global"] == 1


def _firma(res):
    pallets, sin = res
    return (sorted(sin.items()), sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for p in pallets for t in p.torres))


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_el_frente_es_determinista_y_ajeno_al_reloj(monkeypatch, reloj):
    _espiar_cascada(monkeypatch)
    esperado = _firma(_n_pallets(solo_frente=True))
    monkeypatch.setattr(pb.time, "process_time", reloj)
    monkeypatch.setattr(pb.time, "monotonic", reloj)
    assert _firma(_n_pallets(solo_frente=True)) == esperado


def test_solo_frente_default_es_false():
    assert inspect.signature(pb._empacar_n_pallets).parameters["solo_frente"].default is False


# ---------------------------------------------- política en armar_pallets_bloques (integración con espías)


def _df(cantidad):
    return pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": cantidad, "Largo_Efectivo": 60.0, "Ancho_Efectivo": 50.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "T",
    }])


def _espia_solver(monkeypatch, frente):
    """Espía de `_empacar_n_pallets`: registra cada llamada (solo_frente o profunda). `frente` decide qué devuelve el front-end."""
    llamadas = []
    original = pb._empacar

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append({"n": n, "solo_frente": bool(kw.get("solo_frente"))})
        if kw.get("solo_frente"):
            return frente(pendientes, por_sku, cap, niv, tope, cd, n, original)
        return [], {"A": 1}                    # la cascada profunda "falla" -no debe invocarse cuando hay incumbent

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    return llamadas


def _frente_completa(pendientes, por_sku, cap, niv, tope, cd, n, empacar):
    pallets = empacar(dict(pendientes), por_sku, cap, niv, tope, pb._altura_presupuesto(), cd, [0])
    for p in pallets:
        p.metadata["origen_test"] = "FRENTE"
    return pallets, {}


def test_frente_completa_el_incumbent_greedy_no_lo_reemplaza(monkeypatch):
    llamadas = _espia_solver(monkeypatch, _frente_completa)
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    assert llamadas == [{"n": 2, "solo_frente": True}]                       # solo el front-end; sin camino profundo
    assert all(p.metadata.get("origen_test") == "FRENTE" for p in pallets) and len(pallets) == 2
    assert pallets[-1].metadata["fixed_n_exact_n_incumbent"]["resultado"] == "FRENTE_COMPLETO"


def test_frente_falla_y_hay_incumbent_el_incumbent_gana_y_la_cascada_profunda_no_corre(monkeypatch):
    llamadas = _espia_solver(monkeypatch, lambda *a: ([], {"A": 20}))         # el front-end no completa
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    assert llamadas == [{"n": 2, "solo_frente": True}]                       # NUNCA una llamada profunda (sin solo_frente)
    assert len(pallets) == 2 and sum(t.cantidad for p in pallets for t in p.torres) == 60
    assert all(v5.validar_pallet_v5(p) == [] for p in pallets)
    md = pallets[-1].metadata["fixed_n_exact_n_incumbent"]
    assert md["resultado"] == "INCUMBENT_USADO" and md["n_greedy"] == 2 and md["frente_colocadas"] == 0


def test_frente_con_pallets_invalidos_no_cuenta_como_completo(monkeypatch):
    def _frente_invalida(pendientes, por_sku, cap, niv, tope, cd, n, empacar):
        pallets, sin = _frente_completa(pendientes, por_sku, cap, niv, tope, cd, n, empacar)
        return pallets, sin

    llamadas = _espia_solver(monkeypatch, _frente_invalida)
    original = v5.validar_pallet_v5
    monkeypatch.setattr(v5, "validar_pallet_v5", lambda p: ["x"] if p.metadata.get("origen_test") == "FRENTE" else original(p))
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    assert llamadas == [{"n": 2, "solo_frente": True}]
    assert not any(p.metadata.get("origen_test") for p in pallets)             # ganó el incumbent (el front-end no valida)
    assert pallets[-1].metadata["fixed_n_exact_n_incumbent"]["resultado"] == "INCUMBENT_USADO"


@pytest.mark.parametrize("n_objetivo,motivo", [(1, "n_greedy>N"), (3, "n_greedy<N")])
def test_n_greedy_distinto_de_n_va_al_camino_profundo(monkeypatch, n_objetivo, motivo):
    llamadas = _espia_solver(monkeypatch, _frente_completa)
    pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=n_objetivo, paralelo_lns=False)
    assert llamadas == [{"n": n_objetivo, "solo_frente": False}]              # camino profundo, sin front-end previo


def test_el_camino_profundo_recibe_los_mismos_kwargs_de_siempre(monkeypatch):
    kws = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        kws.append(dict(kw))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=3, paralelo_lns=False)
    # idéntico al comportamiento anterior, más el fallback sin reserva de RC2-D1 (sin max_nodos_dfs, sin solo_frente)
    assert kws == [{"paralelo_lns": False, "priorizar_grandes": True, "no_reserve_fallback": True, "info_no_reserve": {}}]


def test_el_camino_abierto_no_cambia(monkeypatch):
    monkeypatch.setattr(pb, "_exact_n_incumbent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe correr")))
    pallets = pb.armar_pallets_bloques(_df(60), "T", paralelo_lns=False)
    assert sum(t.cantidad for p in pallets for t in p.torres) == 60
