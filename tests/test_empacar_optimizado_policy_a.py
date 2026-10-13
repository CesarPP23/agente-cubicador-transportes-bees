"""[V6.12-R2-B] Tests de integración de `_empacar_optimizado` con Policy A
real (`src.busqueda_n_pallets`) -complementan los unitarios de
`test_busqueda_n_pallets.py` (que usan un `probe` fake) con corridas
REALES del solver a través de `armar_pallets_bloques`. Cubren: (1) el
caso más común en datos reales (gap=0, `PROVEN_MINIMUM` gratis, ver
golden-6 -5/6 CDs), (2) el descenso real gastando solves genuinos cuando
sí hay un gap, (3) la invariante `hard_lower_bound <= n_greedy` explota si
se viola, (4) el camino de `Pallets_Objetivo` fijo queda intacto (no
pasa por `busqueda_n_pallets` en absoluto)."""
import ast
import inspect

import pandas as pd
import pytest

import src.busqueda_n_pallets as bnp
import src.packing_bloques as pb
from models import PalletV5
from src.packing_bloques import armar_pallets_bloques
from src.torres import TorreCandidate


def _fila(sku, largo, ancho, alto, cantidad, cd="BK31", peso=1.0):
    return {
        "SKU": sku, "CD": cd, "Cajas_Remanente": cantidad,
        "Largo_Efectivo": largo, "Ancho_Efectivo": ancho, "Alto_Efectivo": alto,
        "Peso_Caja": peso, "Fuente_Geometria": "UMA_VALIDADA",
    }


def test_gap_cero_da_proven_minimum_sin_gastar_solves():
    """[caso más común en datos reales, ver golden-6: 5/6 CDs] Cuando el
    hard bound ya coincide con lo que el greedy logra, la búsqueda no
    gasta ningún solve -PROVEN_MINIMUM gratis."""
    df = pd.DataFrame([_fila("A", 30, 20, 20, 300)])
    pallets = armar_pallets_bloques(df, "BK31")
    total = sum(t.cantidad for p in pallets for t in p.torres)
    assert total == 300
    meta = pallets[-1].metadata["optimality_status"]
    assert meta["status"] == "PROVEN_MINIMUM"
    assert meta["best_feasible_n"] == meta["hard_lower_bound"] == meta["n_greedy"]
    assert meta["solves_realizados"] == 0


def test_policy_a_desciende_con_solves_reales_y_nunca_pierde_demanda(monkeypatch):
    """Fuerza un `n_greedy` artificialmente inflado (parcheando `_empacar`
    para devolver pallets vacíos de más) sobre una demanda REAL chica -
    Policy A debe, con corridas REALES de `_empacar_n_pallets`, encontrar
    una N menor que el `n_greedy` inflado, gastando solves genuinos."""
    original_empacar = pb._empacar

    def _empacar_inflado(*args, **kwargs):
        pallets = original_empacar(*args, **kwargs)
        contador = args[7]
        extra = []
        for _ in range(3):
            contador[0] += 1
            extra.append(PalletV5(id=f"PV5-EXTRA-{contador[0]:03d}", cd="BK31"))
        return pallets + extra

    monkeypatch.setattr(pb, "_empacar", _empacar_inflado)
    df = pd.DataFrame([_fila("A", 30, 20, 20, 40)])
    pallets = armar_pallets_bloques(df, "BK31")

    total = sum(t.cantidad for p in pallets for t in p.torres)
    assert total == 40  # nunca se pierde demanda, a pesar del n_greedy inflado
    meta = pallets[-1].metadata["optimality_status"]
    assert meta["n_greedy"] >= 4  # 1 real (o más) + 3 fake
    assert meta["best_feasible_n"] < meta["n_greedy"]  # Policy A SÍ encontró algo mejor
    assert meta["solves_realizados"] > 0  # gastó sondeos reales, no fue gratis
    assert meta["status"] in ("PROVEN_MINIMUM", "BEST_FEASIBLE_UNPROVEN")
    # el trace tiene una entrada real por cada solve gastado, con cpu_s registrado
    entradas_probe = [e for e in meta["trace"] if e["fuente"] == "probe"]
    assert len(entradas_probe) == meta["solves_realizados"]
    assert all(e["cpu_s"] >= 0.0 for e in entradas_probe)


def test_witness_fallback_usado_cuando_materializacion_final_falla(monkeypatch):
    """[V6.12-R2-B1, pedido explícito -sección B] Si el probe (`con_lns=
    False`) demuestra que un N es FEASIBLE, pero la corrida FINAL
    (`con_lns=True`, materialización) NO reproduce ese resultado, debe
    usarse el witness real del probe -NUNCA se retrocede a
    `pallets_greedy` habiendo demostrado constructivamente una N menor."""
    pallets_greedy_dummy = [
        PalletV5(id="PV5-GREEDY-1", cd="BK31"),
        PalletV5(id="PV5-GREEDY-2", cd="BK31"),
        PalletV5(id="PV5-GREEDY-3", cd="BK31"),
    ]
    pallets_witness = [PalletV5(id="PV5-WITNESS-1", cd="BK31")]

    def _fake_empacar(*args, **kwargs):
        return pallets_greedy_dummy

    def _fake_empacar_n_pallets(
        pendientes, por_sku, capacidad_cama_por_sku, nivel_por_sku, tope_pallet_por_sku,
        cd, contador, n_pallets, paralelo_lns=True, con_lns=True, priorizar_grandes=False, max_nodos_dfs=30_000,
        presupuesto_rescue_nodos=None, presupuesto_repair_nodos=None, presupuesto_exact_intentos=None,
        exact_max_deterministic_time=None, lns_recon_max_nodos=None, lns_sin_mejora_max=None,
        omitir_repair=False, presupuesto_global_expansiones=None,
    ):
        if n_pallets == 2 and con_lns is False:
            return pallets_witness, {}          # el sondeo SÍ demuestra FEASIBLE en N=2
        if n_pallets == 2 and con_lns is True:
            return [], {"A": 999}                # pero la materialización final (LNS completo) "falla"
        return [], {"A": 1}                       # cualquier otro N (p.ej. N=1): UNKNOWN generico

    monkeypatch.setattr(pb, "_empacar", _fake_empacar)
    monkeypatch.setattr(pb, "_empacar_n_pallets", _fake_empacar_n_pallets)
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)

    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    resultado = pb._empacar_optimizado(
        {"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0], paralelo_lns=False,
    )

    assert resultado is pallets_witness  # NUNCA pallets_greedy_dummy, a pesar de que la final "falló"
    meta = resultado[0].metadata["optimality_status"]
    assert meta["best_feasible_n"] == 2
    assert meta["fuente"] == "witness_probe_no_reproducido_por_LNS_final"


def test_hard_bound_mayor_a_n_greedy_explota(monkeypatch):
    """[invariante -sección B de la autorización] Un hard bound que
    contradice una solución greedy ya válida es un error real del bound,
    nunca algo que se pueda silenciar."""
    import src.busqueda_n_pallets as bnp

    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 999_999)
    df = pd.DataFrame([_fila("A", 30, 20, 20, 300)])  # n_greedy=2 en este caso (ver test de arriba)
    with pytest.raises(AssertionError, match="hard_lower_bound"):
        armar_pallets_bloques(df, "BK31")


def test_pallets_objetivo_fijo_no_pasa_por_busqueda_n_pallets():
    """[sección F -no modificar el camino de Pallets_Objetivo fijo] El
    camino con `pallets_objetivo` explícito usa `_empacar_n_pallets`
    directo (línea ~2411 de packing_bloques.py) -nunca llega a
    `_empacar_optimizado` ni a `busqueda_n_pallets`."""
    fuente_armar = inspect.getsource(armar_pallets_bloques)
    # el branch `if pallets_objetivo is not None` no debe mencionar nada
    # de busqueda_n_pallets -sigue yendo directo a `_empacar_n_pallets`.
    arbol = ast.parse(fuente_armar)
    nombres_importados_o_llamados = {
        nodo.id for nodo in ast.walk(arbol) if isinstance(nodo, ast.Name)
    } | {
        nodo.attr for nodo in ast.walk(arbol) if isinstance(nodo, ast.Attribute)
    }
    assert "busqueda_n_pallets" not in nombres_importados_o_llamados
    assert "politica_a_descenso" not in nombres_importados_o_llamados
    assert "hard_lower_bound" not in nombres_importados_o_llamados


def test_camino_pallets_objetivo_fijo_sigue_dando_el_mismo_resultado():
    """Regresión funcional directa -mismo caso que ya cubre
    `test_bk31_golden.py::test_bk31_rescue_solver_98_de_98`, repetido acá
    para que quede junto a los tests de R2-B: `pallets_objetivo` fijo no
    cambió en absoluto."""
    from fixtures.bk31_manual import DEMANDA_TOTAL_CAJAS, demanda_solver_df

    df = demanda_solver_df()
    pallets = armar_pallets_bloques(df, "BK31", pallets_objetivo=1)
    colocadas = sum(t.cantidad for p in pallets for t in p.torres)
    assert colocadas == DEMANDA_TOTAL_CAJAS == 98
    assert len(pallets) == 1
    # nunca debe tener metadata de optimality_status -ese camino no pasa por ahí
    assert "optimality_status" not in pallets[0].metadata
