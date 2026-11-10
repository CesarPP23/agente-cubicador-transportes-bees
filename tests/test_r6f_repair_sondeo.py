"""[V6.13-R6F -"Repair del sondeo de OPEN"] El Repair del SONDEO de OPEN (`presupuesto_repair_nodos is not None`, único llamador: `busqueda_n_pallets.probe`) corre dentro de
`_candidatos_rapido()`: su DFS real usa `_candidatos_lote_rapido` (misma salida). El Repair de N fijo (`deadline` de CPU, sin ese argumento), la materialización final (que
omite el Repair), el DFS inicial, el Rescue, Exact y Global del sondeo conservan la referencia."""
import ast
from contextlib import nullcontext
from pathlib import Path

import pytest

import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from src.torres import TorreCandidate

from tests.test_r6d_lns_final_open import _llamadas_con_la_keyword

REAL_REPAIR = rp.repair_solver


def _por_sku():
    return {"A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 400, 1.0)], "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 400, 1.0)]}


def _empacar(n=2, **kw):
    """Demanda que no cabe en `n` pallets con el DFS inicial acotado: el Repair (real) corre y su DFS interno se invoca."""
    return pb._empacar_n_pallets({"A": 4000, "B": 4000}, _por_sku(), {}, {"A": 1, "B": 1}, {}, "TEST", [0], n, paralelo_lns=False, con_lns=False, max_nodos_dfs=6, **kw)


class _Etapas:
    """Rescue/Exact/Global son pasantes; el Repair es el REAL. Cuenta por fase (dfs_inicial / repair / otras) qué variante de `_candidatos_lote` corrió."""

    def __init__(self, monkeypatch):
        self.n = {f: {"ref": 0, "rapido": 0, "dfs": 0} for f in ("inicial", "repair", "otras")}
        self.fase = "inicial"
        self.repair_llamadas = 0
        self.prof_en_repair = None
        ref, rapido, dfs = pb._candidatos_lote_referencia, pb._candidatos_lote_rapido, pb._resolver_pallets_backtracking

        def r(*a, **k):
            self.n[self.fase]["ref"] += 1
            return ref(*a, **k)

        def f(*a, **k):
            self.n[self.fase]["rapido"] += 1
            return rapido(*a, **k)

        def d(*a, **k):
            self.n[self.fase]["dfs"] += 1
            return dfs(*a, **k)

        monkeypatch.setattr(pb, "_candidatos_lote_referencia", r)
        monkeypatch.setattr(pb, "_candidatos_lote_rapido", f)
        monkeypatch.setattr(pb, "_resolver_pallets_backtracking", d)

        def fase(nombre, pasante):
            def g(*a, **k):
                anterior, self.fase = self.fase, nombre
                try:
                    return pasante(*a, **k)
                finally:
                    self.fase = anterior
            return g

        def rescue(pallets, sin_colocar, *a, **k):
            return pallets, sin_colocar, {}

        def repair(*a, **k):
            self.repair_llamadas += 1
            self.prof_en_repair = pb._CAND_PROFUNDIDAD.get()
            return REAL_REPAIR(*a, **k)

        def exact(pallet, por_sku, sin_colocar, *a, **k):
            return pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}

        def glob(pallets, sin_colocar, *a, **k):
            return pallets, sin_colocar, {"presupuesto": {}}

        monkeypatch.setattr(rs, "rescue_solver", fase("otras", rescue))
        monkeypatch.setattr(rp, "repair_solver", fase("repair", repair))
        monkeypatch.setattr(er, "exact_repair_orquestado", fase("otras", exact))
        monkeypatch.setattr(gr, "global_rescue", fase("otras", glob))
        monkeypatch.setattr(rp, "RESCUE_TIME_MAX_SECONDS", 1.5)
        monkeypatch.setattr(rp, "REPAIR_TIME_MAX_SECONDS", 1.5)


# ------------------------------------------------------------------------------------------------------------- qué variante corre en el DFS real del Repair


def test_el_dfs_real_del_repair_de_sondeo_usa_la_rapida_y_nada_mas(monkeypatch):
    e = _Etapas(monkeypatch)
    _empacar(presupuesto_rescue_nodos=50, presupuesto_repair_nodos=400, presupuesto_exact_intentos=1)
    assert e.repair_llamadas == 1 and e.prof_en_repair == 1
    assert e.n["repair"]["dfs"] >= 1                                            # el Repair de verdad lanzó DFS
    assert e.n["repair"]["rapido"] > 0 and e.n["repair"]["ref"] == 0           # y todos sus candidatos salieron de la rápida
    assert e.n["inicial"]["ref"] > 0 and e.n["inicial"]["rapido"] == 0         # DFS inicial: referencia
    assert e.n["otras"]["rapido"] == 0                                          # Rescue/Exact/Global: sin llamadas rápidas
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None  # contexto y caché cerrados


def test_el_dfs_real_del_repair_de_n_fijo_conserva_la_referencia(monkeypatch):
    e = _Etapas(monkeypatch)
    _empacar()                                                                  # sin presupuestos: Repair por deadline de CPU
    assert e.repair_llamadas == 1 and e.prof_en_repair == 0
    assert e.n["repair"]["dfs"] >= 1 and e.n["repair"]["ref"] > 0 and e.n["repair"]["rapido"] == 0
    assert pb._CAND_PROFUNDIDAD.get() == 0


def test_el_dfs_real_del_repair_de_n_fijo_profundo_conserva_la_referencia(monkeypatch):
    e = _Etapas(monkeypatch)
    _empacar(gobernador_profundo=True)                                          # camino profundo de N fijo: su Repair es por CPU
    assert e.repair_llamadas == 1 and e.prof_en_repair == 0
    assert e.n["repair"]["rapido"] == 0


@pytest.mark.parametrize("kw", [
    dict(presupuesto_rescue_nodos=50),
    dict(presupuesto_exact_intentos=1),
    dict(presupuesto_global_expansiones=9),                                     # materialización final (el Repair se omite en producción con `omitir_repair=True`)
    dict(presupuesto_rescue_nodos=50, presupuesto_exact_intentos=1, presupuesto_global_expansiones=9),
])
def test_ningun_otro_presupuesto_de_open_abre_la_rapida_en_el_repair(monkeypatch, kw):
    e = _Etapas(monkeypatch)
    _empacar(**kw)
    assert e.prof_en_repair == 0 and e.n["repair"]["rapido"] == 0


def test_la_materializacion_final_omite_el_repair_y_no_abre_la_rapida(monkeypatch):
    e = _Etapas(monkeypatch)
    _empacar(presupuesto_global_expansiones=9, omitir_repair=True, presupuesto_rescue_nodos=50, presupuesto_exact_intentos=1)
    assert e.repair_llamadas == 0 and e.n["repair"]["rapido"] == 0 and e.n["repair"]["ref"] == 0


def test_el_resultado_del_repair_de_sondeo_es_el_mismo_con_y_sin_la_rapida(monkeypatch):
    _Etapas(monkeypatch)

    def corrida():
        pallets, sin = _empacar(presupuesto_rescue_nodos=50, presupuesto_repair_nodos=400, presupuesto_exact_intentos=1)
        return sorted(sin.items()), [(t.sku, t.x, t.y, t.z, t.cantidad) for p in pallets for t in p.torres], [p.metadata.get("repair_stats", {}).get("presupuesto") for p in pallets]

    con = corrida()
    monkeypatch.setattr(pb, "_candidatos_rapido", lambda: nullcontext())
    sin = corrida()
    assert con == sin
    assert con[2][-1] and con[2][-1].get("nodos_trabajo", 0) > 0              # el Repair gastó nodos de verdad


def test_el_contexto_se_cierra_si_el_repair_lanza_una_excepcion(monkeypatch):
    _Etapas(monkeypatch)

    def falla(*a, **k):
        assert pb._CAND_PROFUNDIDAD.get() == 1
        raise RuntimeError("repair")

    monkeypatch.setattr(rp, "repair_solver", falla)
    with pytest.raises(RuntimeError):
        _empacar(presupuesto_rescue_nodos=50, presupuesto_repair_nodos=400, presupuesto_exact_intentos=1)
    assert pb._CAND_PROFUNDIDAD.get() == 0 and pb._CAND_ESTADO.get() is None


# ---------------------------------------------------------------------------------------------------- único llamador con presupuesto_repair_nodos (AST)


def test_un_unico_llamador_de_src_pasa_presupuesto_repair_nodos_y_es_el_sondeo():
    assert _llamadas_con_la_keyword("presupuesto_repair_nodos") == [("busqueda_n_pallets.py", "probe", "_empacar_n_pallets")]


def test_el_unico_llamador_de_repair_solver_con_presupuesto_nodos_es_empacar_n_pallets():
    assert _llamadas_con_la_keyword("presupuesto_nodos") == []  # se pasa por **kwargs_repair, nunca como keyword literal
    raiz = Path(pb.__file__).resolve().parent
    sitios = []
    for archivo in sorted(raiz.glob("*.py")):
        for fn in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if isinstance(fn, ast.FunctionDef):
                for nodo in ast.walk(fn):
                    if isinstance(nodo, ast.Call) and getattr(nodo.func, "id", getattr(nodo.func, "attr", None)) == "repair_solver":
                        sitios.append((archivo.name, fn.name))
    assert sorted(set(sitios)) == [("packing_bloques.py", "_empacar_n_pallets")]
