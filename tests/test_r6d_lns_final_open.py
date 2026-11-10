"""[V6.13-R6D -"DFS del LNS de la materialización final de OPEN"] El LNS de la materialización final (el único llamador de `_empacar_n_pallets` que pasa
`presupuesto_global_expansiones`, en su rama secuencial) corre su DFS con `_candidatos_lote_rapido` (misma salida). Todo lo demás conserva la referencia: el DFS
inicial de esa misma llamada, la cascada (Rescue/Repair/Exact/Global), los sondeos de OPEN, el LNS fuera de la materialización final y el LNS del camino profundo
de N fijo (cuyo DFS inicial usa la rápida desde R6-C, pero no su LNS)."""
import pytest

from models import PalletV5

import src.packing_bloques as pb
from src.torres import TorreCandidate
from tests.test_r6b_candidatos_lote import _stub_cascada


def _por_sku():
    return {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 400, 1.0)]}


def _empacar(n=2, **kw):
    kw.setdefault("lns_max_iteraciones", 3)
    return pb._empacar_n_pallets({"A": 400, "B": 400}, _por_sku(), {}, {"A": 1, "B": 1}, {}, "TEST", [0], n, paralelo_lns=False, con_lns=True,
                                 max_nodos_dfs=6, lns_recon_max_nodos=15, lns_sin_mejora_max=2, **kw)


class _Fases:
    """Cuenta qué variante de `_candidatos_lote` corrió en cada fase de `_empacar_n_pallets`: DFS inicial, LNS y cascada."""

    def __init__(self, monkeypatch):
        self.n = {f: {"ref": 0, "rapido": 0} for f in ("inicial", "lns", "cascada")}
        self.fase = "inicial"
        ref, rapido = pb._candidatos_lote_referencia, pb._candidatos_lote_rapido

        def r(*a, **k):
            self.n[self.fase]["ref"] += 1
            return ref(*a, **k)

        def f(*a, **k):
            self.n[self.fase]["rapido"] += 1
            return rapido(*a, **k)

        monkeypatch.setattr(pb, "_candidatos_lote_referencia", r)
        monkeypatch.setattr(pb, "_candidatos_lote_rapido", f)
        lns = pb._lns_mejorar_pallets

        def lns_(*a, **k):
            anterior, self.fase = self.fase, "lns"
            try:
                return lns(*a, **k)
            finally:
                self.fase = anterior

        monkeypatch.setattr(pb, "_lns_mejorar_pallets", lns_)
        self.visto = {}
        _stub_cascada(monkeypatch, self.visto)
        import src.rescue_solver as rs
        stub = rs.rescue_solver

        def rescue(*a, **k):
            self.fase = "cascada"
            return stub(*a, **k)

        monkeypatch.setattr(rs, "rescue_solver", rescue)


def test_la_materializacion_final_corre_su_lns_con_la_rapida_y_el_resto_con_la_referencia(monkeypatch):
    f = _Fases(monkeypatch)
    _empacar(presupuesto_global_expansiones=9)
    assert f.n["lns"]["rapido"] > 0 and f.n["lns"]["ref"] == 0           # el DFS del LNS: rápida
    assert f.n["inicial"]["ref"] > 0 and f.n["inicial"]["rapido"] == 0   # el DFS inicial de la misma llamada: referencia
    assert f.n["cascada"]["rapido"] == 0                                 # Rescue/Repair/Exact/Global: referencia
    assert f.visto.get("rescue") == 0                                    # y su etapa no ve el contexto
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None


@pytest.mark.parametrize("kw", [
    dict(),                                                                                  # sin presupuestos
    dict(presupuesto_rescue_nodos=777),                                                      # sondeo de OPEN
    dict(presupuesto_rescue_nodos=777, presupuesto_repair_nodos=5, presupuesto_exact_intentos=3),
    dict(presupuesto_exact_intentos=3),
    dict(gobernador_profundo=True),                                                          # camino profundo de N fijo: su DFS inicial es rápida (R6-C), su LNS no
])
def test_el_lns_fuera_de_la_materializacion_final_conserva_la_referencia(monkeypatch, kw):
    f = _Fases(monkeypatch)
    _empacar(**kw)
    assert f.n["lns"]["ref"] > 0 and f.n["lns"]["rapido"] == 0
    assert f.n["cascada"]["rapido"] == 0
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None


def test_el_dfs_inicial_de_la_materializacion_final_conserva_la_referencia_aunque_su_lns_use_la_rapida(monkeypatch):
    """R6-D no extiende la rápida al DFS inicial de OPEN (decisión aparte)."""
    f = _Fases(monkeypatch)
    _empacar(presupuesto_global_expansiones=9, gobernador_profundo=True)  # `gobernador_profundo` con presupuesto de OPEN: no es el camino profundo
    assert f.n["inicial"]["ref"] > 0 and f.n["inicial"]["rapido"] == 0


def test_el_resultado_de_la_materializacion_final_es_el_mismo_con_y_sin_la_rapida(monkeypatch):
    from contextlib import nullcontext

    def corrida():
        info = {}
        pallets, sin = _empacar(presupuesto_global_expansiones=9, info_frente=info)
        return (sorted(sin.items()), [(t.sku, t.x, t.y, t.z, t.cantidad) for p in pallets for t in p.torres], info.get("nodos"), info.get("iteraciones"),
                info.get("motivo_parada"))

    _stub_cascada(monkeypatch, {})
    con_rapida = corrida()
    monkeypatch.setattr(pb, "_candidatos_rapido", lambda: nullcontext())  # sin ningún contexto rápido
    sin_rapida = corrida()
    assert con_rapida == sin_rapida
    assert con_rapida[3] is not None and con_rapida[3] > 0                # el LNS de verdad iteró


def test_el_contexto_se_cierra_si_el_lns_lanza_una_excepcion(monkeypatch):
    _stub_cascada(monkeypatch, {})

    def falla(*a, **k):
        assert pb._CAND_PROFUNDIDAD.get() == 1   # abierto durante el LNS
        raise RuntimeError("lns")

    monkeypatch.setattr(pb, "_lns_mejorar_pallets", falla)
    with pytest.raises(RuntimeError):
        _empacar(presupuesto_global_expansiones=9)
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# Vínculo `presupuesto_global_expansiones is not None` <-> materialización final de OPEN (el criterio que decide el alcance de R6-D)
# ---------------------------------------------------------------------------------------------------------------------------------------------------


def _llamadas_con_la_keyword(nombre_kw):
    """Todos los sitios de llamada, en `src/`, que pasan `nombre_kw=` a cualquier función: (archivo, función contenedora, función llamada)."""
    import ast
    from pathlib import Path

    raiz = Path(pb.__file__).resolve().parent
    hallados = []
    for archivo in sorted(raiz.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for fn in ast.walk(arbol):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for nodo in ast.walk(fn):
                if isinstance(nodo, ast.Call) and any(k.arg == nombre_kw for k in nodo.keywords):
                    destino = nodo.func.id if isinstance(nodo.func, ast.Name) else getattr(nodo.func, "attr", "?")
                    hallados.append((archivo.name, fn.name, destino))
    return sorted(set(hallados))


def test_un_unico_llamador_de_src_pasa_presupuesto_global_expansiones_y_es_la_materializacion_final():
    assert _llamadas_con_la_keyword("presupuesto_global_expansiones") == [("packing_bloques.py", "_empacar_optimizado", "_empacar_n_pallets")]


def test_en_el_flujo_open_solo_la_llamada_final_lleva_presupuesto_global_expansiones_y_solo_ella_abre_la_rapida_en_su_lns(monkeypatch):
    """Recorre `_empacar_optimizado` con el `_empacar_n_pallets` REAL envuelto: cada llamada registra sus kwargs y si su LNS corrió con la rápida."""
    import src.busqueda_n_pallets as bnp

    registro = []
    real = pb._empacar_n_pallets
    lns_real = pb._lns_mejorar_pallets
    actual = [None]

    def lns_(*a, **k):
        actual[0]["lns_rapido"] = actual[0].get("lns_rapido", False) or pb._CAND_PROFUNDIDAD.get() > 0
        return lns_real(*a, **k)

    def envuelto(*a, **k):
        previo = actual[0]
        actual[0] = {"global": k.get("presupuesto_global_expansiones"), "con_lns": k.get("con_lns", True), "lns_rapido": False}
        registro.append(actual[0])
        try:
            return real(*a, **k)
        finally:
            actual[0] = previo

    monkeypatch.setattr(pb, "_lns_mejorar_pallets", lns_)
    monkeypatch.setattr(pb, "_empacar_n_pallets", envuelto)
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    # el greedy (2 pallets) queda por encima de la cota (1): hay descenso (sondeo) y materialización final
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: [PalletV5(id=f"PV5-T-{i}", cd="T") for i in range(2)])
    por_sku = {"A": [TorreCandidate("A", "T", "L×A", 40, 30, 20, 20, 400, 1.0)], "B": [TorreCandidate("B", "T", "L×A", 20, 15, 12, 20, 400, 1.0)]}
    pb._empacar_optimizado({"A": 6, "B": 9}, por_sku, {}, {"A": 1, "B": 1}, {}, presupuesto=200.0, cd="T", contador=[0], paralelo_lns=False)

    assert registro, "el flujo OPEN no llamó a _empacar_n_pallets"
    con_global = [r for r in registro if r["global"] is not None]
    assert len(con_global) == 1 and con_global[0]["con_lns"] is True              # una sola llamada, la final con LNS completo
    assert all(not r["lns_rapido"] for r in registro if r["global"] is None)       # ninguna otra llamada de OPEN abre la rápida en su LNS
