"""[PATCH V6.12-RC2-D1 -"FIXED_N_NO_RESERVE_FALLBACK"] En el camino profundo de `Pallets_Objetivo` (sin `exact_n_incumbent`), si el front-end CON
reserva no completa Y el LNS quedó sin candidatos (`sin_skus`: todos los SKUs protegidos), se corre un segundo front-end con
`priorizar_grandes=False` (`solo_frente=True`, sin Rescue/Repair/Exact/Global):

  camino normal completa            -> el fallback NO se ejecuta
  exact_n_incumbent existe          -> el fallback NO se ejecuta (modo `solo_frente`)
  normal falla con sin_skus         -> el fallback SÍ se ejecuta
  fallback completa                 -> la cascada profunda NO corre
  fallback no completa              -> la cascada profunda sigue disponible
  el resultado no depende del reloj."""
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
    return TorreCandidate(sku, "CD", "L×A", 60.0, 50.0, 20.0, 20, 10_000, 1.0)   # 40 cajas por pallet


def _args(demanda=60):
    return ({"A": demanda}, {"A": [_cand()]}, {}, {"A": 1}, {})


def _df(cantidad):
    return pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": cantidad, "Largo_Efectivo": 60.0, "Ancho_Efectivo": 50.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "T",
    }])


def _colocadas(pallets):
    return sum(t.cantidad for p in pallets for t in p.torres)


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


def _espiar_reserva(monkeypatch, forzar_incompleto=False):
    """Registra cada llamada a `_empacar_n_pallets` (priorizar_grandes, solo_frente). Con `forzar_incompleto` el front-end CON reserva queda
    sin colocar nada nuevo (la reserva se vacía): simula el atasco de BK35 -el DFS no completa y todo SKU colocado queda protegido."""
    llamadas = []
    real = pb._empacar_n_pallets

    def _espia(*a, **k):
        llamadas.append({"priorizar_grandes": k.get("priorizar_grandes"), "solo_frente": bool(k.get("solo_frente")), "con_lns": k.get("con_lns", True)})
        return real(*a, **k)

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    return llamadas


def _front_end_con_reserva_atascado(monkeypatch):
    """Escenario sintético de BK35: CON reserva el front-end no completa y el LNS queda `sin_skus` (la reserva no coloca nada pero protege todos
    los SKUs, el greedy fijo de ese primer front-end no coloca nada y su DFS se recorta a 1 nodo); SIN reserva (segundo front-end) todo corre
    normal y completa."""
    estado = {"con_reserva": False, "llamadas_greedy": 0}
    real_dfs = pb._resolver_pallets_backtracking
    real_greedy = pb._empacar_n_pallets_greedy

    def _greedy(pendientes, por_sku, cap, niv, tope, cd, contador, n):
        estado["con_reserva"] = False                               # arranca cada front-end sin reserva
        estado["llamadas_greedy"] += 1
        if estado["llamadas_greedy"] > 1:
            return real_greedy(pendientes, por_sku, cap, niv, tope, cd, contador, n)
        pallets = []
        for _ in range(n):
            contador[0] += 1
            pallets.append(pb.PalletV5(id=f"PV5-{cd}-{contador[0]:03d}", cd=cd))
        return pallets, dict(pendientes)

    def _reserva(construcciones, colocados, pendientes, por_sku, *a, **k):
        estado["con_reserva"] = True                                # no coloca nada, pero protege TODOS los SKUs
        return frozenset(s for s, c in pendientes.items() if c > 0)

    def _dfs(*a, **k):
        return real_dfs(*a, **({**k, "max_nodos": 1} if estado["con_reserva"] else k))

    monkeypatch.setattr(pb, "_empacar_n_pallets_greedy", _greedy)
    monkeypatch.setattr(pb, "_reservar_skus_grandes", _reserva)
    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", _dfs)
    return estado


# ------------------------------------------------------------------------------------ unidad: _empacar_n_pallets


def test_defaults_inertes():
    p = inspect.signature(pb._empacar_n_pallets).parameters
    assert p["no_reserve_fallback"].default is False and p["info_no_reserve"].default is None


def test_camino_normal_completa_el_fallback_no_se_ejecuta(monkeypatch):
    llamadas = _espiar_reserva(monkeypatch)
    info = {}
    pallets, sin = pb._empacar_n_pallets(*_args(60), "T", [0], 2, paralelo_lns=False, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve=info)
    assert not sin and _colocadas(pallets) == 60
    assert info == {"attempted": False, "resultado": "NOT_ATTEMPTED"}
    assert [c["priorizar_grandes"] for c in llamadas] == [True]               # una sola llamada: nunca un segundo front-end


def test_modo_solo_frente_nunca_ejecuta_el_fallback(monkeypatch):
    llamadas = _espiar_reserva(monkeypatch)
    _front_end_con_reserva_atascado(monkeypatch)
    info = {}
    pb._empacar_n_pallets(*_args(60), "T", [0], 2, paralelo_lns=False, priorizar_grandes=True, solo_frente=True, no_reserve_fallback=True, info_no_reserve=info)
    assert info["attempted"] is False and [c["priorizar_grandes"] for c in llamadas] == [True]


def test_sin_el_flag_el_fallback_no_se_ejecuta(monkeypatch):
    llamadas = _espiar_reserva(monkeypatch)
    _front_end_con_reserva_atascado(monkeypatch)
    _espiar_cascada(monkeypatch)
    pb._empacar_n_pallets(*_args(60), "T", [0], 2, paralelo_lns=False, priorizar_grandes=True)
    assert [c["priorizar_grandes"] for c in llamadas] == [True]


def test_front_end_con_reserva_falla_y_lns_sin_skus_el_fallback_completa_y_la_cascada_no_corre(monkeypatch):
    llamadas = _espiar_reserva(monkeypatch)
    _front_end_con_reserva_atascado(monkeypatch)
    cascada = _espiar_cascada(monkeypatch)
    info = {}
    contador = [0]
    pallets, sin = pb._empacar_n_pallets(*_args(60), "T", contador, 2, paralelo_lns=False, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve=info)
    assert not sin and _colocadas(pallets) == 60 and len(pallets) == 2 and all(v5.validar_pallet_v5(p) == [] for p in pallets)
    assert info["attempted"] is True and info["resultado"] == "COMPLETED" and info["colocadas"] == 60 and info["dfs_nodes"] >= 1
    assert isinstance(info["lns_iteraciones"], int)                             # observabilidad: iteraciones LNS del segundo front-end
    assert [(c["priorizar_grandes"], c["solo_frente"]) for c in llamadas] == [(True, False), (False, True)]   # normal, luego fallback sin reserva
    assert cascada == {"rescue": 0, "repair": 0, "exact": 0, "global": 0}      # la cascada profunda NO corrió
    assert contador[0] == 4 and {p.id for p in pallets} <= {f"PV5-T-00{i}" for i in range(1, 5)}   # ids como un camino normal (greedy 2 + dfs 2)


def test_fallback_no_completa_la_cascada_profunda_sigue_disponible(monkeypatch):
    # demanda inalcanzable: ni con reserva ni sin reserva completa -> cascada profunda como siempre
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)]}
    llamadas = _espiar_reserva(monkeypatch)
    cascada = _espiar_cascada(monkeypatch)
    real_reserva = pb._reservar_skus_grandes
    monkeypatch.setattr(pb, "_reservar_skus_grandes", lambda *a, **k: real_reserva(*a, **k) | frozenset(["A", "B"]))   # todo protegido (sin_skus)
    info = {}
    pallets, sin = pb._empacar_n_pallets({"A": 5000, "B": 5000}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, max_nodos_dfs=40,
                                         lns_recon_max_nodos=10, lns_sin_mejora_max=2, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve=info)
    assert sin and info["attempted"] is True and info["resultado"] == "INCOMPLETE"
    assert cascada["rescue"] == 1 and cascada["global"] == 1                    # la cascada profunda SÍ corrió
    assert [(c["priorizar_grandes"], c["solo_frente"]) for c in llamadas] == [(True, False), (False, True)]


def test_lns_con_candidatos_no_dispara_el_fallback(monkeypatch):
    # front-end con reserva incompleto pero la reserva NO protege todo (hay candidatos para el LNS) -> no es el caso `sin_skus`
    por_sku = {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)]}
    llamadas = _espiar_reserva(monkeypatch)
    _espiar_cascada(monkeypatch)
    monkeypatch.setattr(pb, "_reservar_skus_grandes", lambda *a, **k: frozenset())
    info = {}
    pb._empacar_n_pallets({"A": 5000, "B": 5000}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, max_nodos_dfs=40,
                          lns_recon_max_nodos=10, lns_sin_mejora_max=2, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve=info)
    assert info["attempted"] is False and [c["priorizar_grandes"] for c in llamadas] == [True]


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_el_resultado_del_fallback_no_depende_del_reloj(monkeypatch, reloj):
    def _firma(res):
        pallets, sin = res
        return (sorted(sin.items()), sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for p in pallets for t in p.torres))

    estado = _front_end_con_reserva_atascado(monkeypatch)
    _espiar_cascada(monkeypatch)
    kw = dict(paralelo_lns=False, priorizar_grandes=True, no_reserve_fallback=True)
    info1 = {}
    esperado = _firma(pb._empacar_n_pallets(*_args(60), "T", [0], 2, info_no_reserve=info1, **kw))
    monkeypatch.setattr(pb.time, "process_time", reloj)
    monkeypatch.setattr(pb.time, "monotonic", reloj)
    monkeypatch.setattr(pb.time, "time", reloj)
    info2 = {}
    estado["llamadas_greedy"] = 0                                               # reinicia el escenario (primer front-end atascado otra vez)
    assert _firma(pb._empacar_n_pallets(*_args(60), "T", [0], 2, info_no_reserve=info2, **kw)) == esperado
    assert info1 == info2 and info1["resultado"] == "COMPLETED"


# --------------------------------------------------------------------- integración: armar_pallets_bloques + metadata


def test_integracion_incumbent_existe_el_fallback_no_corre_y_no_hay_metadata_del_fallback(monkeypatch):
    llamadas = _espiar_reserva(monkeypatch)
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)   # n_greedy == N: incumbent
    md = pallets[-1].metadata
    assert [(c["priorizar_grandes"], c["solo_frente"]) for c in llamadas] == [(True, True)]
    assert "fixed_n_no_reserve_fallback_attempted" not in md and md["fixed_n_solution_source"] in ("FRONTEND_COMPLETE", "EXACT_N_GREEDY_INCUMBENT")


def test_integracion_camino_normal_completa_registra_no_intentado(monkeypatch):
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=3, paralelo_lns=False)    # n_greedy < N: camino profundo; completa sin fallback
    md = pallets[-1].metadata
    assert md["fixed_n_no_reserve_fallback_attempted"] is False and md["fixed_n_no_reserve_fallback_result"] == "NOT_ATTEMPTED"
    assert md["fixed_n_no_reserve_dfs_nodes"] is None and "fixed_n_solution_source" not in md


def test_integracion_fallback_completa_registra_metadata_y_fuente(monkeypatch):
    _front_end_con_reserva_atascado(monkeypatch)
    cascada = _espiar_cascada(monkeypatch)
    monkeypatch.setattr(pb, "_exact_n_incumbent", lambda *a, **k: (None, {"incumbent": False, "motivo": "test"}))   # fuerza el camino profundo
    pallets = pb.armar_pallets_bloques(_df(60), "T", pallets_objetivo=2, paralelo_lns=False)
    md = pallets[-1].metadata
    assert _colocadas(pallets) == 60 and len(pallets) == 2 and cascada == {"rescue": 0, "repair": 0, "exact": 0, "global": 0}
    assert md["fixed_n_no_reserve_fallback_attempted"] is True and md["fixed_n_no_reserve_fallback_result"] == "COMPLETED"
    assert md["fixed_n_no_reserve_dfs_nodes"] >= 1 and isinstance(md["fixed_n_no_reserve_lns_iterations"], int)
    assert md["fixed_n_solution_source"] == "FIXED_N_NO_RESERVE_FALLBACK"


# ------------------------------------------------ RC2-D1.1: el fallback es secuencial (semilla 0) en cualquier modo exterior


@pytest.mark.parametrize("paralelo_exterior", [False, True])
def test_el_fallback_corre_siempre_secuencial_sin_importar_paralelo_lns_exterior(monkeypatch, paralelo_exterior):
    llamadas = []
    real = pb._empacar_n_pallets

    def _espia(*a, **k):
        llamadas.append({"priorizar_grandes": k.get("priorizar_grandes"), "paralelo_lns": k.get("paralelo_lns")})
        return real(*a, **k)

    _front_end_con_reserva_atascado(monkeypatch)
    _espiar_cascada(monkeypatch)
    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    info = {}
    pallets, sin = pb._empacar_n_pallets(*_args(60), "T", [0], 2, paralelo_lns=paralelo_exterior, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve=info)
    assert not sin and info["resultado"] == "COMPLETED"
    assert llamadas == [{"priorizar_grandes": True, "paralelo_lns": paralelo_exterior}, {"priorizar_grandes": False, "paralelo_lns": False}]
    assert isinstance(info["lns_iteraciones"], int)                             # siempre observable: ya no es None en modo paralelo


def test_el_resultado_del_fallback_es_igual_con_paralelo_lns_true_y_false(monkeypatch):
    def _firma(res):
        pallets, sin = res
        return (sorted(sin.items()), sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for p in pallets for t in p.torres))

    estado = _front_end_con_reserva_atascado(monkeypatch)
    _espiar_cascada(monkeypatch)
    firmas = []
    for paralelo in (False, True):
        estado["llamadas_greedy"] = 0
        firmas.append(_firma(pb._empacar_n_pallets(*_args(60), "T", [0], 2, paralelo_lns=paralelo, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve={})))
    assert firmas[0] == firmas[1]


def test_el_fallback_pasa_el_tope_de_iteraciones_lns_y_el_front_end_normal_no():
    assert pb.FIXED_N_NO_RESERVE_LNS_MAX_ITERATIONS == 100 < pb.COMBINACION_PALLETS_LNS_ITERACIONES
    assert inspect.signature(pb._empacar_n_pallets).parameters["lns_max_iteraciones"].default is None
    assert inspect.signature(pb._lns_mejorar_pallets).parameters["max_iteraciones"].default is None


def test_el_fallback_llama_al_front_end_con_el_tope_y_el_resto_de_llamadas_sin_tope(monkeypatch):
    llamadas = []
    real = pb._empacar_n_pallets

    def _espia(*a, **k):
        llamadas.append((k.get("priorizar_grandes"), k.get("lns_max_iteraciones")))
        return real(*a, **k)

    _front_end_con_reserva_atascado(monkeypatch)
    _espiar_cascada(monkeypatch)
    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    pb._empacar_n_pallets(*_args(60), "T", [0], 2, priorizar_grandes=True, no_reserve_fallback=True, info_no_reserve={})
    assert llamadas == [(True, None), (False, pb.FIXED_N_NO_RESERVE_LNS_MAX_ITERATIONS)]


@pytest.mark.parametrize("tope, esperado", [(0, 0), (1, 1), (7, 7), (None, pb.COMBINACION_PALLETS_LNS_ITERACIONES)])
def test_el_tope_de_iteraciones_del_lns_corta_el_trabajo(monkeypatch, tope, esperado):
    monkeypatch.setattr(pb, "_romper_skus_con_cascada", lambda *a, **k: None)
    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", lambda *a, **k: 0)
    monkeypatch.setattr(pb, "_snapshot_estado_pallets", lambda *a, **k: None)
    monkeypatch.setattr(pb, "_restaurar_estado_pallets", lambda *a, **k: None)
    info = {}
    total = pb._lns_mejorar_pallets(
        [], [{"A": 5, "B": 5}], {"A": 3}, {}, {}, {}, {}, 0.0, 2, "s", sin_mejora_max=10_000, info_salida=info, max_iteraciones=tope,
    )
    assert total == 10 and info["iteraciones"] == esperado
