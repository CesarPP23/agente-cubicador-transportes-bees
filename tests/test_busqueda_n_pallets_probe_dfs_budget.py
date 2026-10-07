"""[PATCH V6.12-D7B-P1 -"Probe DFS work budget"] El DFS inicial del SONDEO
(`busqueda_n_pallets.probe()`) acota por `PROBE_DFS_MAX_NODES` (8000);
TODO lo demás conserva su tope: materialización final de `_empacar_optimizado`,
`Pallets_Objetivo` fijo, DFS del LNS, Rescue/Repair. La unidad es conteo de
nodos -nunca el reloj.

[CONVENCIÓN DE CONTEO -fijada en V6.12-D7B-P2, idéntica para todos los
budgets de trabajo de ahí en adelante] `_resolver_pallets_backtracking`
incrementa `estado["nodos"]` AL ENTRAR a cada nodo (la raíz es el nodo 1) y
corta con `if estado["nodos"] > max_nodos: return` (guard estricto). Por lo
tanto, un tope de N significa:
  * EXPANSIONES (nodos que calculan candidatos, = llamadas a
    `_candidatos_lote`) <= N  -exactamente N si el espacio no se agota antes;
  * VISITAS (la métrica real `estado["nodos"]`, la que registran los
    contadores y las trazas) = N + 1 al cortar: la visita que excede el tope
    se cuenta, evalúa si mejora el incumbente, y retorna sin expandir.
Los tests sintéticos de abajo miden las dos cosas con el contador real."""
import inspect
from unittest.mock import patch

import pytest

import src.busqueda_n_pallets as bnp
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from src.busqueda_n_pallets import ProbeStatus
from src.torres import TorreCandidate


def _cand(sku, largo, ancho, alto, cantidad_disponible=20, max_verticales=20):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _escenario_inalcanzable():
    por_sku = {
        "A": [_cand("A", 40, 30, 20, cantidad_disponible=200)],
        "B": [_cand("B", 20, 15, 12, cantidad_disponible=200)],
    }
    return por_sku, {"A": 200, "B": 200}


def _escenario_completable():
    por_sku = {
        "A": [_cand("A", 40, 30, 20, cantidad_disponible=9)],
        "B": [_cand("B", 30, 40, 20, cantidad_disponible=9)],
        "C": [_cand("C", 40, 25, 15, cantidad_disponible=9)],
        "D": [_cand("D", 25, 40, 15, cantidad_disponible=9)],
    }
    return por_sku, {"A": 9, "B": 9, "C": 9, "D": 9}


def _stubear_cascada(monkeypatch):
    """La cascada Rescue/Repair/Exact/Global NO es lo que se prueba acá (y
    corre contra presupuestos de reloj reales)."""
    monkeypatch.setattr(rs, "rescue_solver", lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {}))
    monkeypatch.setattr(rp, "repair_solver", lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {}))
    monkeypatch.setattr(
        er, "exact_repair_orquestado",
        lambda pallet, por_sku, sin_colocar, *a, **k: (pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}),
    )
    monkeypatch.setattr(gr, "global_rescue", lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {}))


def _contar_nodos_dfs(monkeypatch):
    """Cuenta llamadas a `_candidatos_lote` (proxy exacto de nodos DFS visitados
    -ver tests de D5) SOLO del DFS inicial: la cascada está stubeada y no hay LNS."""
    n = [0]
    original = pb._candidatos_lote

    def _contado(*a, **k):
        n[0] += 1
        return original(*a, **k)

    monkeypatch.setattr(pb, "_candidatos_lote", _contado)
    return n


def _contar_visitas_dfs(monkeypatch):
    """Instrumenta (solo en el test) `_resolver_pallets_backtracking` para
    registrar `estado["nodos"]` -la MISMA métrica real que reportan las trazas
    y los contadores- al terminar cada corrida. No cambia el comportamiento."""
    visitas: list[int] = []
    fuente = inspect.getsource(pb._resolver_pallets_backtracking)
    marca = '    return estado["mejor_total"]\n'
    assert fuente.count(marca) == 1
    fuente = fuente.replace(marca, '    _registro_visitas_test.append(estado["nodos"])\n' + marca)
    original = pb._resolver_pallets_backtracking
    pb.__dict__["_registro_visitas_test"] = visitas
    exec(compile(fuente, "<visitas_test>", "exec"), pb.__dict__)
    instrumentada = pb.__dict__["_resolver_pallets_backtracking"]
    pb.__dict__["_resolver_pallets_backtracking"] = original  # monkeypatch registra `original` como valor a restaurar
    monkeypatch.setattr(pb, "_resolver_pallets_backtracking", instrumentada)
    monkeypatch.delitem(pb.__dict__, "_registro_visitas_test", raising=False)
    pb.__dict__["_registro_visitas_test"] = visitas
    return visitas


def _correr_probe(por_sku, pendientes, n_pallets=1):
    return bnp.probe(
        n_pallets, dict(pendientes), por_sku, {}, {s: 1 for s in por_sku}, {}, "TEST", [0], False,
    )


# ------------------------------------------------------------------ constantes


def test_probe_usa_8000_y_el_default_de_la_funcion_sigue_en_30000():
    assert bnp.PROBE_DFS_MAX_NODES == 8000
    assert pb.COMBINACION_PALLETS_MAX_NODOS == 30_000
    default = inspect.signature(pb._empacar_n_pallets).parameters["max_nodos_dfs"].default
    assert default == 30_000 == pb.COMBINACION_PALLETS_MAX_NODOS


def test_probe_pasa_PROBE_DFS_MAX_NODES_a_empacar_n_pallets(monkeypatch):
    capturado = {}

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        capturado.update(kw)
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    por_sku, pendientes = _escenario_inalcanzable()
    resultado = _correr_probe(por_sku, pendientes)

    assert capturado["max_nodos_dfs"] == bnp.PROBE_DFS_MAX_NODES == 8000
    assert capturado["con_lns"] is False
    assert resultado.status is ProbeStatus.UNKNOWN


def test_materializacion_final_y_pallets_objetivo_no_pasan_el_override(monkeypatch):
    """`Pallets_Objetivo` fijo (`armar_pallets_bloques`) llama a
    `_empacar_n_pallets` SIN `max_nodos_dfs` -sigue con el default de 30000. Los
    sondeos (con_lns=False, via probe()) lo sobrescriben con 8000 y desde
    V6.12-D8A.1 la materialización final usa SU PROPIO tope (FINAL_DFS_MAX_NODES,
    ver tests/test_final_materialization_work_budget.py), nunca el del sondeo."""
    llamadas = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append((n, dict(kw)))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)

    # 1) materialización final de la ruta abierta
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: _pallets_dummy(2))
    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_optimizado({"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0], paralelo_lns=False)
    sondeos = [(n, kw) for n, kw in llamadas if kw.get("con_lns") is False]
    finales = [(n, kw) for n, kw in llamadas if kw.get("con_lns", True) is True]
    assert sondeos and all(kw["max_nodos_dfs"] == 8000 for _, kw in sondeos)
    assert finales and all(kw["max_nodos_dfs"] == bnp.FINAL_DFS_MAX_NODES != bnp.PROBE_DFS_MAX_NODES for _, kw in finales)

    # 2) Pallets_Objetivo fijo, directo desde armar_pallets_bloques
    llamadas.clear()
    import pandas as pd

    from src.packing_bloques import armar_pallets_bloques

    df = pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": 3, "Largo_Efectivo": 30.0, "Ancho_Efectivo": 20.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "BK31",
    }])
    try:
        armar_pallets_bloques(df, "BK31", pallets_objetivo=1, paralelo_lns=False)
    except Exception:  # el espía devuelve un resultado vacío -lo único que importa son los kwargs recibidos
        pass
    assert llamadas, "Pallets_Objetivo debía llamar a _empacar_n_pallets"
    assert all("max_nodos_dfs" not in kw for _, kw in llamadas)


def _pallets_dummy(n):
    from models import PalletV5
    return [PalletV5(id=f"PV5-X-{i}", cd="X") for i in range(n)]


# ----------------------------------------------------- el corte es por trabajo


def test_el_corte_ocurre_exactamente_por_el_presupuesto_de_nodos(monkeypatch):
    """Con `PROBE_DFS_MAX_NODES` chico, el DFS del sondeo visita EXACTAMENTE
    ese número de nodos (el escenario es inalcanzable: jamás termina antes)."""
    _stubear_cascada(monkeypatch)
    nodos = _contar_nodos_dfs(monkeypatch)
    por_sku, pendientes = _escenario_inalcanzable()

    resultados = {}
    for tope in (5, 25, 60):
        nodos[0] = 0
        monkeypatch.setattr(bnp, "PROBE_DFS_MAX_NODES", tope)
        r = _correr_probe(por_sku, pendientes)
        resultados[tope] = (nodos[0], r.cajas_colocadas)
        assert r.status is ProbeStatus.UNKNOWN

    assert [resultados[t][0] for t in (5, 25, 60)] == [5, 25, 60]
    # más trabajo permitido => nunca menos cajas
    assert resultados[5][1] <= resultados[25][1] <= resultados[60][1]


def test_convencion_expansiones_igual_al_tope_y_visitas_igual_al_tope_mas_uno(monkeypatch):
    """Explica por qué la métrica real de un DFS cortado por `PROBE_DFS_MAX_NODES
    = 8000` es 8001 y no 8000: la visita que excede el tope se contabiliza
    (guard `>` estricto, contador incrementado al entrar) pero no expande."""
    _stubear_cascada(monkeypatch)
    expansiones = _contar_nodos_dfs(monkeypatch)
    visitas = _contar_visitas_dfs(monkeypatch)
    por_sku, pendientes = _escenario_inalcanzable()

    for tope in (7, 30):
        expansiones[0] = 0
        visitas.clear()
        monkeypatch.setattr(bnp, "PROBE_DFS_MAX_NODES", tope)
        _correr_probe(por_sku, pendientes)
        assert expansiones[0] == tope
        assert visitas == [tope + 1]  # una sola corrida de DFS en el probe; métrica real = tope + 1


def test_un_probe_que_necesita_menos_de_8000_nodos_sigue_siendo_feasible(monkeypatch):
    _stubear_cascada(monkeypatch)
    nodos = _contar_nodos_dfs(monkeypatch)
    por_sku, pendientes = _escenario_completable()

    r = _correr_probe(por_sku, pendientes, n_pallets=2)

    assert r.status is ProbeStatus.FEASIBLE
    assert r.cajas_colocadas == r.demanda_total == 36
    assert 0 < nodos[0] < bnp.PROBE_DFS_MAX_NODES  # terminó por solución, no por el tope


# ---------------------------------------------- el reloj no decide el trabajo


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_cambiar_process_time_no_cambia_el_trabajo_ni_el_resultado_del_probe(monkeypatch, reloj):
    _stubear_cascada(monkeypatch)
    nodos = _contar_nodos_dfs(monkeypatch)
    monkeypatch.setattr(bnp, "PROBE_DFS_MAX_NODES", 40)
    por_sku, pendientes = _escenario_inalcanzable()

    with patch("time.process_time", side_effect=lambda: reloj()):
        r = _correr_probe(por_sku, pendientes)

    assert nodos[0] == 40
    assert (r.status, r.cajas_colocadas) == (ProbeStatus.UNKNOWN, r.cajas_colocadas)
    referencia = (40, r.cajas_colocadas)
    # dos relojes opuestos (congelado / saltando) => mismo trabajo y mismas cajas
    assert (nodos[0], r.cajas_colocadas) == referencia


def test_resultado_del_probe_identico_entre_repeticiones(monkeypatch):
    _stubear_cascada(monkeypatch)
    monkeypatch.setattr(bnp, "PROBE_DFS_MAX_NODES", 50)
    por_sku, pendientes = _escenario_inalcanzable()
    resultados = [_correr_probe(por_sku, pendientes).cajas_colocadas for _ in range(3)]
    assert len(set(resultados)) == 1
