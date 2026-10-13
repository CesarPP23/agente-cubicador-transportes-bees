"""[PATCH V6.12-D7B-P2 -"Probe Rescue work budget"] Rescue corta por un
presupuesto de NODOS (unidad y convención de conteo: `src/medidor_trabajo.py`)
SOLO en el contexto del sondeo (`busqueda_n_pallets.probe()`):
`PROBE_RESCUE_MAX_NODES` viaja explícito `probe()` -> `_empacar_n_pallets`
(`presupuesto_rescue_nodos`) -> `rescue_solver(presupuesto_nodos=...)`.
La materialización final y `Pallets_Objetivo` fijo no reciben el kwarg."""
import inspect
from unittest.mock import patch

import pytest

import config
import src.busqueda_n_pallets as bnp
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from models import PalletV5
from src.busqueda_n_pallets import ProbeStatus
from src.medidor_trabajo import MedidorTrabajo
from src.rescue_solver import rescue_solver
from src.torres import TorreCandidate, crear_torre


def _cand(sku="X", largo=30, ancho=30, alto=20, cantidad_disponible=10):
    return TorreCandidate(sku, "BK31", "LxA", largo, ancho, alto, 10, cantidad_disponible, 1.0)


def _escenario_grande_bloqueado_por_dos_chicos():
    """Mismo escenario ya validado de test_rescue_solver/cpu_time_clock: Rescue
    necesita una ruina dirigida (consume nodos de backtracking) para resolver."""
    presupuesto = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO
    wall1_cand = _cand(sku="WALL1", largo=82.0, ancho=104.0, alto=presupuesto)
    wall1 = crear_torre(wall1_cand, x=40, y=-2, cantidad=1)
    wall2_cand = _cand(sku="WALL2", largo=42.0, ancho=72.0, alto=presupuesto)
    wall2 = crear_torre(wall2_cand, x=-2, y=30, cantidad=1)
    chico_a = _cand(sku="A", largo=20, ancho=30, alto=15)
    chico_b = _cand(sku="B", largo=20, ancho=30, alto=15)
    torre_a = crear_torre(chico_a, x=0, y=0, cantidad=1)
    torre_b = crear_torre(chico_b, x=20, y=0, cantidad=1)
    pallet = PalletV5(id="P1", cd="BK31", torres=[wall1, wall2, torre_a, torre_b],
                       altura_final=config.ALTURA_PALLET_VACIO + presupuesto)
    grande = _cand(sku="GRANDE", largo=40, ancho=30, alto=15)
    por_sku = {"GRANDE": [grande], "A": [chico_a], "B": [chico_b], "WALL1": [wall1_cand], "WALL2": [wall2_cand]}
    nivel_por_sku = {"GRANDE": 6, "A": 6, "B": 6, "WALL1": 6, "WALL2": 6}
    return pallet, por_sku, nivel_por_sku, presupuesto


def _correr_rescue(**kw):
    pallet, por_sku, nivel_por_sku, presupuesto = _escenario_grande_bloqueado_por_dos_chicos()
    pallets_final, sin_colocar_final, stats = rescue_solver(
        [pallet], {"GRANDE": 1}, por_sku, capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku,
        tope_pallet_por_sku={}, n_pallets=1, presupuesto=presupuesto, **kw,
    )
    firma = sorted((t.sku, t.cantidad, round(t.x, 2), round(t.y, 2), round(t.z, 2)) for t in pallets_final[0].torres)
    return sin_colocar_final, stats, firma


# --------------------------------------------------------- constantes y firmas


def test_constantes_y_defaults():
    assert bnp.PROBE_RESCUE_MAX_NODES == 15000
    assert inspect.signature(rescue_solver).parameters["presupuesto_nodos"].default is None
    assert inspect.signature(pb._empacar_n_pallets).parameters["presupuesto_rescue_nodos"].default is None


def test_medidor_de_trabajo_acumula_y_se_lee_como_reloj():
    m = MedidorTrabajo()
    assert m() == 0.0
    m.registrar_nodos(5)
    m.registrar_nodos(7)
    assert m() == 12.0 and m.nodos == 12


# ----------------------------------------------------- propagación del contexto


def test_probe_pasa_el_presupuesto_de_rescue_y_el_de_dfs(monkeypatch):
    capturado = {}

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        capturado.update(kw)
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    bnp.probe(1, {"A": 5}, {"A": [_cand("A")]}, {}, {"A": 1}, {}, "TEST", [0], False)

    assert capturado["presupuesto_rescue_nodos"] == bnp.PROBE_RESCUE_MAX_NODES == 15000
    assert capturado["max_nodos_dfs"] == bnp.PROBE_DFS_MAX_NODES == 8000


def test_final_y_pallets_objetivo_no_reciben_el_presupuesto_de_rescue(monkeypatch):
    llamadas = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append(dict(kw))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)

    # materialización final de la ruta abierta (el sondeo SÍ lo recibe)
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: [PalletV5(id=f"PV5-X-{i}", cd="X") for i in range(2)])
    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_optimizado({"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0], paralelo_lns=False)
    sondeos = [kw for kw in llamadas if kw.get("con_lns") is False]
    finales = [kw for kw in llamadas if kw.get("con_lns", True) is True]
    assert sondeos and all(kw["presupuesto_rescue_nodos"] == 15000 for kw in sondeos)
    # [D8B-7.2] la FINAL tiene su PROPIO tope de Rescue (3250), nunca el del sondeo (15000)
    assert finales and all(kw["presupuesto_rescue_nodos"] == bnp.FINAL_RESCUE_MAX_NODES == 3250 for kw in finales)

    # Pallets_Objetivo fijo
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
    assert llamadas and all("presupuesto_rescue_nodos" not in kw for kw in llamadas)


def _stubear_resto_de_la_cascada(monkeypatch, repair=None):
    monkeypatch.setattr(rp, "repair_solver", repair or (lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {})))
    monkeypatch.setattr(
        er, "exact_repair_orquestado",
        lambda pallet, por_sku, sin_colocar, *a, **k: (pallet, sin_colocar, {"intentos": 0, "exitos": 0, "cajas_recuperadas": 0}),
    )
    monkeypatch.setattr(gr, "global_rescue", lambda pallets, sin_colocar, *a, **k: (pallets, sin_colocar, {}))


def _empacar_n_inalcanzable(**kw):
    por_sku = {
        "A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)],
        "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)],
    }
    return pb._empacar_n_pallets(
        {"A": 200, "B": 200}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1,
        paralelo_lns=False, con_lns=False, max_nodos_dfs=30, **kw,
    )


def test_empacar_n_pallets_envia_presupuesto_nodos_a_rescue_solo_si_se_pide(monkeypatch):
    recibidos = []

    def _rescue_espia(pallets, sin_colocar, *a, **k):
        recibidos.append(dict(k))
        return pallets, sin_colocar, {}

    monkeypatch.setattr(rs, "rescue_solver", _rescue_espia)
    _stubear_resto_de_la_cascada(monkeypatch)

    _empacar_n_inalcanzable()
    _empacar_n_inalcanzable(presupuesto_rescue_nodos=777)

    assert "presupuesto_nodos" not in recibidos[0]
    assert recibidos[1]["presupuesto_nodos"] == 777


def test_feasible_preservado_por_la_cascada_posterior(monkeypatch):
    """Plomería de la cadena: Rescue (con presupuesto) entrega un residual
    PARCIAL, y la etapa siguiente parte de ese residual y lo completa =>
    el sondeo es FEASIBLE aunque Rescue no llegó al 100%. (La evidencia
    real sobre BK41 n=3 / BK65 n=4 está en los gates de batch.)"""
    entradas_repair = []

    def _rescue_parcial(pallets, sin_colocar, *a, **k):
        assert k["presupuesto_nodos"] == bnp.PROBE_RESCUE_MAX_NODES
        return pallets, {"A": 3}, {}  # mejora parcial: de 400 a 3 faltantes

    def _repair_completa(pallets, sin_colocar, *a, **k):
        entradas_repair.append(dict(sin_colocar))
        return pallets, {}, {}

    monkeypatch.setattr(rs, "rescue_solver", _rescue_parcial)
    _stubear_resto_de_la_cascada(monkeypatch, repair=_repair_completa)
    # score: forzar que el parcial sea aceptado como mejor que el incumbente
    monkeypatch.setattr(rs, "_score_solucion", lambda total, *a, **k: (total,))

    por_sku = {
        "A": [TorreCandidate("A", "CD", "L×A", 40, 30, 20, 20, 200, 1.0)],
        "B": [TorreCandidate("B", "CD", "L×A", 20, 15, 12, 20, 200, 1.0)],
    }
    monkeypatch.setattr(bnp, "PROBE_DFS_MAX_NODES", 30)
    r = bnp.probe(1, {"A": 200, "B": 200}, por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], False)

    assert entradas_repair == [{"A": 3}]  # Repair parte del residual parcial de Rescue
    assert r.status is ProbeStatus.FEASIBLE


# ------------------------------------------------------- Rescue real: el corte


def test_rescue_sin_presupuesto_nodos_sigue_en_modo_tiempo():
    sin_colocar, stats, _ = _correr_rescue()
    assert sin_colocar == {}
    assert stats["presupuesto"] == {"modo": "tiempo"}


def test_rescue_con_presupuesto_amplio_da_el_mismo_resultado_que_en_modo_tiempo():
    sc_t, st_t, firma_t = _correr_rescue()
    sc_n, st_n, firma_n = _correr_rescue(presupuesto_nodos=10**9)
    assert (sc_n, firma_n) == (sc_t, firma_t)
    assert st_n["presupuesto"]["modo"] == "nodos"
    assert st_n["presupuesto"]["nodos_trabajo"] > 0  # los backtracking registraron su trabajo


def test_cutoff_con_presupuesto_cero_rescue_no_arranca_nada():
    """`while reloj() < limite_tiempo` con límite = 0 + 0: ni siquiera entra."""
    sin_colocar, stats, _ = _correr_rescue(presupuesto_nodos=0)
    assert stats["presupuesto"]["nodos_trabajo"] == 0
    assert stats["iteraciones"] == 0
    assert sin_colocar == {"GRANDE": 1}  # no tocó nada


def test_cutoff_es_estricto_y_la_unidad_en_curso_termina():
    """Convención (src/medidor_trabajo.py): el chequeo es `reloj() > límite`,
    ENTRE unidades; la unidad en curso termina. Con presupuesto = el trabajo
    total de la corrida completa NUNCA se corta (consumo == tope no es `>`);
    con presupuesto 1 se corta apenas la primera unidad consume algo."""
    _, st_full, firma_full = _correr_rescue(presupuesto_nodos=10**9)
    total = st_full["presupuesto"]["nodos_trabajo"]

    sc_exacto, st_exacto, firma_exacta = _correr_rescue(presupuesto_nodos=total)
    assert st_exacto["presupuesto"]["nodos_trabajo"] == total
    assert firma_exacta == firma_full

    _, st_uno, _ = _correr_rescue(presupuesto_nodos=1)
    assert 1 <= st_uno["presupuesto"]["nodos_trabajo"] <= total
    assert st_uno["iteraciones"] <= st_full["iteraciones"]


# ------------------------------------------------ el reloj no decide el trabajo


@pytest.mark.parametrize("reloj", [lambda: 0.0, lambda: 1e12])
def test_reloj_rapido_o_lento_no_cambia_nodos_ni_resultado(reloj):
    ref = _correr_rescue(presupuesto_nodos=2000)
    with patch("time.process_time", side_effect=lambda: reloj()):
        sc, st, firma = _correr_rescue(presupuesto_nodos=2000)
    assert (sc, firma) == (ref[0], ref[2])
    assert st["presupuesto"] == ref[1]["presupuesto"]
    assert st["iteraciones"] == ref[1]["iteraciones"]


def test_mismo_input_mismos_nodos_y_residual():
    corridas = [_correr_rescue(presupuesto_nodos=2000) for _ in range(3)]
    assert len({(c[1]["presupuesto"]["nodos_trabajo"], tuple(sorted(c[0].items())), tuple(c[2])) for c in corridas}) == 1
