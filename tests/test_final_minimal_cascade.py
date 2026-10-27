"""[PATCH V6.12-D8B-7.2 -"Final minimal cascade"] La materialización FINAL
(`_empacar_optimizado`, corrida con LNS en la N ganadora) usa una cascada
mínima y acotada por TRABAJO:

    DFS/LNS -> Rescue 3250 nodos -> [Repair OFF] -> Exact 14 intentos
            -> Global 9500 expansiones -> witness fallback

PROBE (Rescue 15000 / Repair 24000 / Exact 500 / Global por tiempo) y
`Pallets_Objetivo` fijo (cascada completa por tiempo) NO cambian. Calibración
y contrato (PROBE: perder un éxito puede aumentar N; FINAL: N ya elegido y
witness factible => perder una mejora profunda es un fallback de calidad) en
el comentario de `busqueda_n_pallets.FINAL_RESCUE_MAX_NODES`."""
import inspect
import time

import pandas as pd
import pytest

import config
import src.busqueda_n_pallets as bnp
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from models import PalletV5
from src.medidor_trabajo import MedidorTrabajo
from src.torres import TorreCandidate
from src.validacion_v5 import validar_pallet_v5

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO

FINAL_KW = dict(
    presupuesto_rescue_nodos=3250, omitir_repair=True, presupuesto_exact_intentos=14,
    exact_max_deterministic_time=1.0, presupuesto_global_expansiones=9500,
)


def _cand(sku, largo, ancho, alto, cantidad_disponible=200):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, cantidad_disponible, 1.0)


def _escenario_inalcanzable():
    por_sku = {"A": [_cand("A", 40, 30, 20)], "B": [_cand("B", 20, 15, 12)]}
    return por_sku, {"A": 200, "B": 200}


def _empacar(**kw):
    por_sku, pendientes = _escenario_inalcanzable()
    return pb._empacar_n_pallets(
        dict(pendientes), por_sku, {}, {"A": 1, "B": 1}, {}, "TEST", [0], 1, paralelo_lns=False, max_nodos_dfs=15,
        lns_recon_max_nodos=5, lns_sin_mejora_max=2, **kw,
    )


class _Cascada:
    """Stubs de las 4 etapas que registran cuántas veces y con qué kwargs se las llama."""

    def __init__(self, monkeypatch, completa_en=None):
        self.llamadas: dict[str, list[dict]] = {"rescue": [], "repair": [], "exact": [], "global": []}
        completa = completa_en

        def _rescue(p, s, *a, **k):
            self.llamadas["rescue"].append(k)
            return (p, {}, {}) if completa == "rescue" else (p, s, {})

        def _repair(p, s, *a, **k):
            self.llamadas["repair"].append(k)
            return (p, {}, {}) if completa == "repair" else (p, s, {})

        def _exact(pallet, por_sku, s, *a, **k):
            self.llamadas["exact"].append(k)
            if completa == "exact":
                return pallet, {}, {"intentos": 1, "exitos": 1, "cajas_recuperadas": sum(s.values())}
            return pallet, dict(s), {"intentos": 1, "exitos": 0, "cajas_recuperadas": 0}

        def _global(p, s, *a, **k):
            self.llamadas["global"].append(k)
            return (p, {}, {}) if completa == "global" else (p, s, {})

        monkeypatch.setattr(rs, "rescue_solver", _rescue)
        monkeypatch.setattr(rp, "repair_solver", _repair)
        monkeypatch.setattr(er, "exact_repair_orquestado", _exact)
        monkeypatch.setattr(gr, "global_rescue", _global)

    def contadas(self):
        return {k: len(v) for k, v in self.llamadas.items()}


# ------------------------------------------------------------------ constantes


def test_constantes_final_minimas_y_probe_sin_cambios():
    assert bnp.FINAL_RESCUE_MAX_NODES == 3250
    assert bnp.FINAL_REPAIR_ENABLED is False
    assert bnp.FINAL_EXACT_MAX_ATTEMPTS == 14 and bnp.FINAL_EXACT_MAX_DET_TIME == 1.0
    assert bnp.FINAL_GLOBAL_MAX_EXPANSIONS == 9500
    # D8A.1 intacto
    assert (bnp.FINAL_DFS_MAX_NODES, bnp.FINAL_LNS_RECON_MAX_NODES, bnp.FINAL_LNS_SIN_MEJORA) == (6500, 2650, 40)
    # PROBE intacto
    assert bnp.PROBE_DFS_MAX_NODES == 8000 and bnp.PROBE_RESCUE_MAX_NODES == 15000
    assert bnp.PROBE_REPAIR_MAX_NODES == 24000
    assert bnp.PROBE_EXACT_MAX_ATTEMPTS == 500 and bnp.PROBE_EXACT_MAX_DET_TIME == 1.0


def test_el_margen_de_global_cubre_los_breakpoints_medidos():
    """BK52 llega al 100% en la expansión 4388 (última profundidad en 4260) y
    BK53 en la 6434 (última profundidad en 6306): el cap mínimo es 6306."""
    assert bnp.FINAL_GLOBAL_MAX_EXPANSIONS >= 6306 * 1.4
    assert bnp.FINAL_GLOBAL_MAX_EXPANSIONS >= 6434


def test_defaults_de_las_funciones_no_activan_el_modo_final():
    firma = inspect.signature(pb._empacar_n_pallets).parameters
    assert firma["omitir_repair"].default is False
    assert firma["presupuesto_global_expansiones"].default is None
    assert inspect.signature(gr.global_rescue).parameters["presupuesto_expansiones"].default is None


# ----------------------------------------------------- propagación del contexto


def _espiar_empacar_n(monkeypatch):
    llamadas = []

    def _espia(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        llamadas.append(dict(kw))
        return [], {"A": 1}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _espia)
    return llamadas


def test_empacar_optimizado_final_recibe_la_cascada_minima_y_el_probe_la_completa(monkeypatch):
    llamadas = _espiar_empacar_n(monkeypatch)
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: [PalletV5(id=f"PV5-X-{i}", cd="X") for i in range(2)])
    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    pb._empacar_optimizado({"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0], paralelo_lns=False)

    sondeos = [kw for kw in llamadas if kw.get("con_lns") is False]
    finales = [kw for kw in llamadas if kw.get("con_lns", True) is True]
    assert sondeos and finales
    for kw in sondeos:
        assert kw["presupuesto_rescue_nodos"] == 15000 and kw["presupuesto_repair_nodos"] == 24000
        assert kw["presupuesto_exact_intentos"] == 500 and kw["exact_max_deterministic_time"] == 1.0
        assert "omitir_repair" not in kw and "presupuesto_global_expansiones" not in kw  # PROBE sigue llamando Repair
    for kw in finales:
        for k, v in FINAL_KW.items():
            assert kw[k] == v, k
        assert "presupuesto_repair_nodos" not in kw


def test_pallets_objetivo_no_hereda_nada_de_la_cascada_final(monkeypatch):
    llamadas = _espiar_empacar_n(monkeypatch)
    # [RC2-B] El incumbent exact-N (`_exact_n_incumbent`) hace que este caso sintetico no llegue al camino profundo con los kwargs que se espían; aca se valida lo que el
    # solver de N fijo RECIBE cuando sí se lo invoca -se desactiva el incumbent (cubierto en tests/test_fixed_n_exact_n_incumbent.py).
    monkeypatch.setattr(pb, "_exact_n_incumbent", lambda *a, **k: (None, {"incumbent": False, "motivo": "test"}))
    df = pd.DataFrame([{
        "SKU": "A", "Cajas_Remanente": 3, "Largo_Efectivo": 30.0, "Ancho_Efectivo": 20.0, "Alto_Efectivo": 20.0,
        "Cajas_Cama_Efectivo": 20, "Categoria_Normalizada": "Comestibles", "Nivel_Categoria": 6,
        "Peso_Caja": 1.0, "Cajas_por_PH": 20, "Fuente_Geometria": "TEST", "CD": "BK31",
    }])
    try:
        pb.armar_pallets_bloques(df, "BK31", pallets_objetivo=1, paralelo_lns=False)
    except Exception:  # el espía devuelve vacío -solo importan los kwargs
        pass
    assert llamadas
    for kw in llamadas:
        assert not any(k in kw for k in FINAL_KW), kw


# ------------------------------------------------------------ flujo de la cascada


def test_final_no_llama_repair_si_llama_exact_y_global_con_sus_topes(monkeypatch):
    c = _Cascada(monkeypatch)
    pallets, sin = _empacar(**FINAL_KW)
    assert sin  # ninguna etapa completa -> queda demanda (el witness lo resuelve el llamador)
    assert c.contadas()["repair"] == 0
    assert c.contadas()["rescue"] == 1 and c.contadas()["global"] == 1 and c.contadas()["exact"] >= 1
    assert c.llamadas["rescue"][0]["presupuesto_nodos"] == 3250
    for k in c.llamadas["exact"]:
        assert k["max_deterministic_time"] == 1.0 and 1 <= k["max_intentos"] <= 14 and "deadline" not in k
    assert c.llamadas["global"][0]["presupuesto_expansiones"] == 9500


def test_probe_y_pallets_objetivo_siguen_llamando_repair(monkeypatch):
    c = _Cascada(monkeypatch)
    _empacar()  # defaults: Pallets_Objetivo (cascada completa por tiempo)
    assert c.contadas()["repair"] == 1 and c.contadas()["global"] == 1
    assert "presupuesto_expansiones" not in c.llamadas["global"][0]  # Global por CPU-time
    assert "presupuesto_nodos" not in c.llamadas["repair"][0]
    c2 = _Cascada(monkeypatch)
    _empacar(presupuesto_rescue_nodos=15000, presupuesto_repair_nodos=24000, presupuesto_exact_intentos=500,
             exact_max_deterministic_time=1.0)  # sondeo
    assert c2.contadas()["repair"] == 1
    assert c2.llamadas["repair"][0]["presupuesto_nodos"] == 24000
    assert "presupuesto_expansiones" not in c2.llamadas["global"][0]


@pytest.mark.parametrize("completa_en,esperado", [
    ("rescue", {"rescue": 1, "repair": 0, "exact": 0, "global": 0}),
    ("exact", {"rescue": 1, "repair": 0, "exact": 1, "global": 0}),
    ("global", {"rescue": 1, "repair": 0, "global": 1}),
    (None, {"rescue": 1, "repair": 0, "global": 1}),
])
def test_cada_etapa_que_completa_corta_la_cascada_en_final(monkeypatch, completa_en, esperado):
    c = _Cascada(monkeypatch, completa_en=completa_en)
    pallets, sin = _empacar(**FINAL_KW)
    contadas = c.contadas()
    for etapa, n in esperado.items():
        assert contadas[etapa] == n, (etapa, contadas)
    assert (sin == {}) is (completa_en is not None)


def test_si_ninguna_etapa_completa_el_final_cae_al_witness(monkeypatch):
    """`_empacar_optimizado`: final con faltantes -> devuelve el witness del sondeo."""
    witness = [PalletV5(id="PV5-WITNESS-1", cd="BK31")]

    def _fake(pendientes, por_sku, cap, niv, tope, cd, contador, n, **kw):
        if kw.get("con_lns") is False:
            return (witness, {}) if n == 2 else ([], {"A": 1})
        return [], {"A": 999}

    monkeypatch.setattr(pb, "_empacar_n_pallets", _fake)
    monkeypatch.setattr(pb, "_empacar", lambda *a, **k: [PalletV5(id=f"PV5-G-{i}", cd="BK31") for i in range(3)])
    monkeypatch.setattr(bnp, "hard_lower_bound", lambda *a, **k: 1)
    por_sku = {"A": [TorreCandidate("A", "BK31", "L", 30.0, 20.0, 20.0, 20, 10_000, 1.0)]}
    res = pb._empacar_optimizado({"A": 10}, por_sku, {}, {}, {}, presupuesto=200.0, cd="BK31", contador=[0],
                                 paralelo_lns=False)
    assert res is witness
    assert res[0].metadata["optimality_status"]["fuente"] == "witness_probe_no_reproducido_por_LNS_final"


# --------------------------------------------- Global por TRABAJO (expansiones)

_POR_SKU_G = {
    "A": [_cand("A", 60, 50, 20, 3)], "B": [_cand("B", 40, 30, 15, 5)],
    "C": [_cand("C", 25, 25, 10, 8)], "D": [_cand("D", 80, 90, 25, 2)],
}
_SIN_G = {"A": 3, "B": 5, "C": 8, "D": 2}


def _global(monkeypatch, **kw):
    expansiones = []
    original = gr._expandir_estado

    def _cuenta(*a, **k):
        expansiones.append(1)
        return original(*a, **k)

    monkeypatch.setattr(gr, "_expandir_estado", _cuenta)
    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar=dict(_SIN_G), por_sku=_POR_SKU_G,
        capacidad_cama_por_sku={}, nivel_por_sku={k: 6 for k in _POR_SKU_G}, tope_pallet_por_sku={},
        n_pallets=2, cd="SINTETICO_D8B72", presupuesto=PRESUPUESTO, **kw,
    )
    return len(expansiones), pallets, faltantes, stats


def test_global_sin_presupuesto_de_trabajo_se_comporta_como_siempre(monkeypatch):
    n1, _, _, s1 = _global(monkeypatch)
    n2, _, _, s2 = _global(monkeypatch)
    assert n1 == n2 > 2
    assert s1["motivo_stop"] == s2["motivo_stop"]


def test_global_con_presupuesto_corta_por_expansiones_en_frontera_de_profundidad(monkeypatch):
    completo, _, _, s_completo = _global(monkeypatch)
    cortado, pallets, _, s_corto = _global(monkeypatch, presupuesto_expansiones=2)
    assert s_corto["motivo_stop"] == "timeout"
    assert 2 <= cortado < completo          # soft cap: la profundidad en curso termina
    assert cortado <= 2 + 2                 # una profundidad con frontera de 1 estado (beam crece despacio)
    assert all(validar_pallet_v5(p) == [] for p in pallets)
    # un presupuesto holgado reproduce exactamente la corrida sin presupuesto
    holgado, _, _, s_holgado = _global(monkeypatch, presupuesto_expansiones=10_000)
    assert holgado == completo and s_holgado["motivo_stop"] == s_completo["motivo_stop"]


def test_global_con_presupuesto_es_determinista_y_ajeno_al_reloj(monkeypatch):
    base = _global(monkeypatch, presupuesto_expansiones=3)
    for reloj in (lambda: 0.0, lambda: 1e12):
        monkeypatch.setattr(gr.time, "process_time", reloj)
        n, pallets, faltantes, stats = _global(monkeypatch, presupuesto_expansiones=3)
        assert (n, faltantes, stats["motivo_stop"]) == (base[0], base[2], base[3]["motivo_stop"])
        assert stats["estados_generados"] == base[3]["estados_generados"]


def test_global_con_presupuesto_ignora_el_deadline_de_cpu(monkeypatch):
    completo, *_ = _global(monkeypatch, presupuesto_expansiones=10_000)
    con_deadline_vencido, _, _, stats = _global(
        monkeypatch, presupuesto_expansiones=10_000, deadline=time.process_time() - 1.0,
    )
    assert con_deadline_vencido == completo
    # sin presupuesto de trabajo, en cambio, el deadline vencido sí corta de inmediato
    sin_presupuesto, _, _, stats = _global(monkeypatch, deadline=time.process_time() - 1.0)
    assert sin_presupuesto == 0 and stats["motivo_stop"] == "timeout"


def test_medidor_cuenta_una_expansion_por_estado_expandido():
    m = MedidorTrabajo()
    m.registrar_nodos(1)
    m.registrar_nodos(1)
    assert m() == 2.0
