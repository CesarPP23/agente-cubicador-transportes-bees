"""[V6.13-R6C -"DFS inicial profundo"] El DFS inicial del camino profundo de N fijo (`_empacar_n_pallets(gobernador_profundo=True)` sin presupuestos de sondeo/final
de OPEN) está acotado por `max_nodos_dfs` (el reloj no decide el corte) y usa `_candidatos_lote_rapido`. Cualquier otro llamador del mismo front-end (sin
gobernador profundo, sondeos y materialización final de OPEN, modo incumbent `solo_frente`) conserva la referencia. La salida es idéntica."""
import pytest

import src.packing_bloques as pb
from src.torres import TorreCandidate
from tests.test_r6b_candidatos_lote import _stub_cascada


def _por_sku():
    return {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 400, 1.0)]}


def _empacar(n=2, **kw):
    return pb._empacar_n_pallets({"A": 400, "B": 400}, _por_sku(), {}, {"A": 1, "B": 1}, {}, "TEST", [0], n, paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw)


class _Etapas:
    """Cuenta qué variante de `_candidatos_lote` corrió ANTES de la cascada (= DFS inicial) y durante ella."""

    def __init__(self, monkeypatch):
        self.antes = {"ref": 0, "rapido": 0}
        self.durante = {"ref": 0, "rapido": 0}
        self.en_cascada = False
        ref, rapido = pb._candidatos_lote_referencia, pb._candidatos_lote_rapido

        def r(*a, **k):
            (self.durante if self.en_cascada else self.antes)["ref"] += 1
            return ref(*a, **k)

        def f(*a, **k):
            (self.durante if self.en_cascada else self.antes)["rapido"] += 1
            return rapido(*a, **k)

        monkeypatch.setattr(pb, "_candidatos_lote_referencia", r)
        monkeypatch.setattr(pb, "_candidatos_lote_rapido", f)
        visto = {}
        _stub_cascada(monkeypatch, visto)
        import src.rescue_solver as rs
        stub = rs.rescue_solver

        def rescue(*a, **k):
            self.en_cascada = True
            return stub(*a, **k)

        monkeypatch.setattr(rs, "rescue_solver", rescue)


@pytest.mark.parametrize("n", [1, 2, 3])
def test_el_dfs_inicial_del_camino_profundo_usa_la_rapida(monkeypatch, n):
    e = _Etapas(monkeypatch)
    _empacar(n=n, gobernador_profundo=True)
    assert e.antes["rapido"] > 0 and e.antes["ref"] == 0
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None  # contexto cerrado y caché descartada


def test_sin_gobernador_profundo_el_dfs_inicial_conserva_la_referencia(monkeypatch):
    e = _Etapas(monkeypatch)
    _empacar()
    assert e.antes["ref"] > 0 and e.antes["rapido"] == 0


@pytest.mark.parametrize("kw", [
    dict(presupuesto_rescue_nodos=777),                      # sondeo OPEN
    dict(presupuesto_repair_nodos=5),
    dict(presupuesto_exact_intentos=3),
    dict(presupuesto_global_expansiones=9),                  # materialización final de OPEN
    dict(presupuesto_rescue_nodos=777, presupuesto_repair_nodos=5, presupuesto_exact_intentos=3),
])
def test_con_cualquier_presupuesto_de_open_aunque_se_pida_el_gobernador_profundo_el_dfs_inicial_conserva_la_referencia(monkeypatch, kw):
    e = _Etapas(monkeypatch)
    _empacar(gobernador_profundo=True, **kw)
    assert e.antes["ref"] > 0 and e.antes["rapido"] == 0


def test_el_modo_incumbent_solo_frente_conserva_la_referencia(monkeypatch):
    e = _Etapas(monkeypatch)
    _empacar(solo_frente=True)
    assert e.antes["ref"] > 0 and e.antes["rapido"] == 0


@pytest.mark.parametrize("n", [1, 3])
def test_el_resultado_del_front_end_es_el_mismo_con_y_sin_el_dfs_rapido(monkeypatch, n):
    def corrida(**kw):
        info = {}
        pallets, sin = pb._empacar_n_pallets({"A": 400, "B": 400}, _por_sku(), {}, {"A": 1, "B": 1}, {}, "TEST", [0], n, paralelo_lns=False, con_lns=False,
                                             max_nodos_dfs=30, solo_frente=True, info_frente=info, **kw)
        return sorted(sin.items()), [(t.sku, t.x, t.y, t.z, t.cantidad) for p in pallets for t in p.torres], info.get("nodos"), info.get("motivo_parada")

    referencia = corrida()
    with pb._candidatos_rapido():
        rapida = corrida()
    assert referencia == rapida
    assert referencia[2] is not None  # el DFS reportó sus nodos
