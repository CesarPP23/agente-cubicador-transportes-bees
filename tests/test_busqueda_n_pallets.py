"""[V6.12-R2-B] Tests de `src.busqueda_n_pallets` -ceil_safe (nunca
sobreestima por ruido flotante), hard_lower_bound (peso/volumen/PH,
volumen con overhang corregido), BusquedaState (4 estados por N,
UNTESTED nunca se confunde con una prueba, optimality_status exacto), y
Policy A (descenso persistente: UNKNOWN no corta, respeta hard_lb y
max_solves, nunca re-sondea un N ya conocido)."""
import inspect

import pytest

import config
from models import PalletV5
from src.busqueda_n_pallets import (
    POLICY_A_MAX_SOLVES,
    BusquedaState,
    EstadoN,
    ProbeResult,
    ProbeStatus,
    ceil_exacto_enteros,
    ceil_safe,
    hard_lower_bound,
    politica_a_descenso,
)
from src.torres import TorreCandidate


def _cand(sku, largo=30.0, ancho=20.0, alto=20.0, peso_unitario=1.0):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, 10_000, peso_unitario)


# --- ceil_safe: nunca sobreestima por ruido de punto flotante -------------


def test_ceil_safe_valor_exacto_no_sobreestima():
    assert ceil_safe(3.0, 1.0) == 3
    assert ceil_safe(9.0, 3.0) == 3


def test_ceil_safe_ruido_positivo_no_sobreestima():
    """El caso real que motivó esta función: una suma flotante que
    matemáticamente es un entero exacto (3.0) puede llegar como
    3.0000000000003 por acumulación de error -no debe redondear a 4."""
    assert ceil_safe(3.0000000000003, 1.0) == 3


def test_ceil_safe_ruido_negativo_sigue_redondeando_hacia_arriba():
    assert ceil_safe(2.9999999999997, 1.0) == 3


def test_ceil_safe_valor_genuinamente_por_encima_redondea_normal():
    """Un cociente genuinamente MAYOR (no solo ruido) sigue subiendo -el
    margen conservador no oculta un caso real que necesita más pallets."""
    assert ceil_safe(3.5, 1.0) == 4


def test_ceil_safe_denominador_no_positivo_explota():
    with pytest.raises(ValueError):
        ceil_safe(10.0, 0.0)
    with pytest.raises(ValueError):
        ceil_safe(10.0, -1.0)


def test_ceil_exacto_enteros_basico():
    assert ceil_exacto_enteros(324, 108) == 3
    assert ceil_exacto_enteros(325, 108) == 4
    assert ceil_exacto_enteros(108, 108) == 1


def test_ceil_exacto_enteros_denominador_no_positivo_explota():
    with pytest.raises(ValueError):
        ceil_exacto_enteros(10, 0)


# --- hard_lower_bound -----------------------------------------------------


def test_hard_lower_bound_domina_peso():
    pendientes = {"A": 100}
    por_sku = {"A": [_cand("A", largo=10, ancho=10, alto=10, peso_unitario=100.0)]}
    # peso_total = 100*100 = 10000kg; PESO_TOPE_ELASTICO_KG=1430 -> ceil(6.99)=7
    bound = hard_lower_bound(pendientes, por_sku, {})
    assert bound == ceil_safe(100 * 100.0, config.PESO_TOPE_ELASTICO_KG)
    assert bound > 1


def test_hard_lower_bound_domina_ph():
    pendientes = {"A": 500}
    por_sku = {"A": [_cand("A", largo=1, ancho=1, alto=1, peso_unitario=0.001)]}
    # peso/volumen triviales (cajas chiquitas y livianas) -PH manda.
    bound = hard_lower_bound(pendientes, por_sku, {"A": 50})
    assert bound == ceil_exacto_enteros(500, 50) == 10


def test_hard_lower_bound_usa_footprint_con_overhang():
    """[V6.12-R2-B0, corrección real] El bound de volumen debe usar
    PALLET_LARGO_EFECTIVO/PALLET_ANCHO_EFECTIVO (con overhang, el mismo
    canvas que usa el solver real -ver _cuboide_inicial), no
    PALLET_LARGO/PALLET_ANCHO desnudos -usar el footprint SIN overhang
    subestima la capacidad real de un pallet y sobreestima el bound
    (justo lo prohibido: nunca sobreestimar)."""
    from src.packing_columnar import _altura_presupuesto

    # Una caja que ocupa TODO el footprint con overhang de un pallet,
    # exactamente 1 unidad de altura de producto -1 sola caja debe bastar
    # para justificar N=1 por volumen, tanto con el footprint correcto
    # como con el desnudo (footprint más grande en el numerador real no
    # cambia esto) -en cambio, comparamos directo los dos denominadores.
    vol_con_overhang = config.PALLET_LARGO_EFECTIVO * config.PALLET_ANCHO_EFECTIVO * _altura_presupuesto()
    vol_sin_overhang = config.PALLET_LARGO * config.PALLET_ANCHO * _altura_presupuesto()
    assert vol_con_overhang > vol_sin_overhang  # el bound corregido SIEMPRE es más laxo (denominador mayor)

    # Caso real: demanda cuyo volumen total cae justo ENTRE ambos
    # denominadores -con el footprint desnudo (bug viejo) el bound sube a
    # 2, con el corregido se queda en 1 (más flojo, nunca sobreestima).
    volumen_total_objetivo = vol_sin_overhang * 1.03  # > sin_overhang, < con_overhang (overhang da ~+7.5%)
    if volumen_total_objetivo >= vol_con_overhang:
        pytest.skip("el margen real entre ambos denominadores no alcanza para este caso sintético")
    largo, ancho, alto = 10.0, 10.0, 10.0
    cantidad = int(volumen_total_objetivo / (largo * ancho * alto))
    pendientes = {"A": cantidad}
    por_sku = {"A": [_cand("A", largo=largo, ancho=ancho, alto=alto, peso_unitario=0.001)]}
    bound = hard_lower_bound(pendientes, por_sku, {})
    assert bound == 1  # con el footprint CORREGIDO (con overhang) sigue alcanzando en 1 pallet


def test_hard_lower_bound_ignora_skus_sin_pendiente_o_sin_candidatas():
    pendientes = {"A": 0, "B": 5}
    por_sku = {"A": [_cand("A")], "B": [_cand("B", peso_unitario=0.001, largo=1, ancho=1, alto=1)]}
    bound = hard_lower_bound(pendientes, por_sku, {})
    assert bound == 1  # A no pesa/cuenta (cantidad 0), B es trivial


def test_hard_lower_bound_minimo_es_1():
    pendientes = {"A": 1}
    por_sku = {"A": [_cand("A", largo=1, ancho=1, alto=1, peso_unitario=0.001)]}
    assert hard_lower_bound(pendientes, por_sku, {}) == 1


# --- BusquedaState: UNTESTED nunca es una prueba --------------------------


def test_estado_default_es_untested():
    state = BusquedaState(hard_lower_bound=3)
    assert state.estado(5) is EstadoN.UNTESTED


def test_estado_bajo_el_hard_bound_es_infeasible_proven_sin_registrar_nada():
    state = BusquedaState(hard_lower_bound=3)
    assert state.estado(1) is EstadoN.INFEASIBLE_PROVEN
    assert state.estado(2) is EstadoN.INFEASIBLE_PROVEN
    assert state.solves_realizados == 0  # gratis, no gastó ningún solve


def test_registrar_feasible_directo_no_gasta_solve():
    state = BusquedaState(hard_lower_bound=1)
    state.registrar_feasible_directo(4, pallets=["x"])
    assert state.best_feasible == 4
    assert state.best_feasible_pallets == ["x"]
    assert state.solves_realizados == 0
    assert state.estado(4) is EstadoN.FEASIBLE


def test_registrar_feasible_actualiza_best_feasible_solo_si_es_menor():
    state = BusquedaState(hard_lower_bound=1)
    state.registrar_feasible_directo(5, pallets=["cinco"])
    state.registrar(ProbeResult(4, ProbeStatus.FEASIBLE, ["cuatro"], 10, 10, 0.1))
    assert state.best_feasible == 4
    assert state.best_feasible_pallets == ["cuatro"]
    # un FEASIBLE en un N mayor al ya conocido no debe "empeorar" el incumbente
    state.registrar(ProbeResult(6, ProbeStatus.FEASIBLE, ["seis"], 10, 10, 0.1))
    assert state.best_feasible == 4


def test_registrar_unknown_no_mueve_best_feasible():
    state = BusquedaState(hard_lower_bound=1)
    state.registrar_feasible_directo(5, pallets=["cinco"])
    state.registrar(ProbeResult(4, ProbeStatus.UNKNOWN, None, 8, 10, 0.1))
    assert state.best_feasible == 5
    assert state.estado(4) is EstadoN.UNKNOWN


def test_optimality_status_proven_minimum_cuando_best_feasible_es_el_hard_bound():
    state = BusquedaState(hard_lower_bound=3)
    state.registrar_feasible_directo(3, pallets=["tres"])
    assert state.optimality_status() == "PROVEN_MINIMUM"


def test_optimality_status_unproven_si_queda_un_unknown_en_el_medio():
    state = BusquedaState(hard_lower_bound=3)
    state.registrar_feasible_directo(6, pallets=["seis"])
    state.registrar(ProbeResult(5, ProbeStatus.FEASIBLE, ["cinco"], 10, 10, 0.1))
    state.registrar(ProbeResult(4, ProbeStatus.UNKNOWN, None, 8, 10, 0.1))
    # 4 quedó UNKNOWN -aunque 3 (hard_lb) nunca se probó, 4 ya bloquea PROVEN_MINIMUM
    assert state.optimality_status() == "BEST_FEASIBLE_UNPROVEN"


def test_optimality_status_unproven_si_queda_un_untested_en_el_medio():
    """[V6.12-R2-B0, bug real corregido] Un N que JAMÁS se probó (no
    FEASIBLE, no UNKNOWN -simplemente no se llegó a él, p.ej. porque se
    agotó max_solves) NO puede contar como si estuviera probado. Antes de
    esta corrección, un chequeo que solo miraba `tested_unknown` habría
    declarado PROVEN_MINIMUM acá incorrectamente."""
    state = BusquedaState(hard_lower_bound=3)
    state.registrar_feasible_directo(6, pallets=["seis"])
    state.registrar(ProbeResult(5, ProbeStatus.FEASIBLE, ["cinco"], 10, 10, 0.1))
    # nunca se registró nada para N=4 ni N=3 (p.ej. se acabó max_solves) -
    # ambos son UNTESTED, no INFEASIBLE_PROVEN.
    assert state.estado(4) is EstadoN.UNTESTED
    assert state.optimality_status() == "BEST_FEASIBLE_UNPROVEN"


def test_optimality_status_sin_solucion_si_nunca_se_registro_nada():
    state = BusquedaState(hard_lower_bound=1)
    assert state.optimality_status() == "SIN_SOLUCION"


def test_optimality_status_proven_minimum_con_rango_vacio_por_gap_cero():
    """gap == 0 (best_feasible == hard_lower_bound desde el arranque, sin
    ningún sondeo adicional) -PROVEN_MINIMUM trivial, `all()` de un rango
    vacío es True por definición matemática, no por accidente."""
    state = BusquedaState(hard_lower_bound=7)
    state.registrar_feasible_directo(7, pallets=["siete"])
    assert state.optimality_status() == "PROVEN_MINIMUM"
    assert list(range(state.hard_lower_bound, state.best_feasible)) == []


# --- Policy A: descenso persistente ---------------------------------------


def _fake_probe_factory(resultados_por_n: dict[int, ProbeStatus]):
    """Reemplaza `busqueda_n_pallets.probe` para no correr el solver real
    -cada N devuelve exactamente el status que el test le asigna."""
    llamadas = []

    def _fake(n, *args, **kwargs):
        llamadas.append(n)
        status = resultados_por_n[n]
        pallets = [f"pallets-{n}"] if status is ProbeStatus.FEASIBLE else None
        return ProbeResult(n, status, pallets, 10, 10, 0.01)

    return _fake, llamadas


def test_policy_a_persistente_no_corta_en_el_primer_unknown(monkeypatch):
    """[pedido explícito -sección D] UNKNOWN se registra, NO corta el
    descenso -debe seguir probando best_feasible-2, -3, ... hasta hard_lb."""
    fake_probe, llamadas = _fake_probe_factory({
        8: ProbeStatus.UNKNOWN, 7: ProbeStatus.UNKNOWN, 6: ProbeStatus.FEASIBLE,
    })
    monkeypatch.setattr("src.busqueda_n_pallets.probe", fake_probe)

    state = BusquedaState(hard_lower_bound=6)
    state.registrar_feasible_directo(9, pallets=["nueve"])
    politica_a_descenso(state, {}, {}, {}, {}, {}, "CD", [0], True)

    assert llamadas == [8, 7, 6]  # nunca se detuvo en 8 ni en 7
    assert state.best_feasible == 6
    assert state.optimality_status() == "PROVEN_MINIMUM"


def test_policy_a_todos_unknown_termina_en_hard_bound_sin_proven_minimum(monkeypatch):
    fake_probe, llamadas = _fake_probe_factory({
        8: ProbeStatus.UNKNOWN, 7: ProbeStatus.UNKNOWN, 6: ProbeStatus.UNKNOWN,
    })
    monkeypatch.setattr("src.busqueda_n_pallets.probe", fake_probe)

    state = BusquedaState(hard_lower_bound=6)
    state.registrar_feasible_directo(9, pallets=["nueve"])
    politica_a_descenso(state, {}, {}, {}, {}, {}, "CD", [0], True)

    assert llamadas == [8, 7, 6]
    assert state.best_feasible == 9  # nunca mejoró
    assert state.optimality_status() == "BEST_FEASIBLE_UNPROVEN"


def test_policy_a_respeta_max_solves(monkeypatch):
    fake_probe, llamadas = _fake_probe_factory({
        9: ProbeStatus.UNKNOWN, 8: ProbeStatus.UNKNOWN, 7: ProbeStatus.UNKNOWN,
        6: ProbeStatus.UNKNOWN, 5: ProbeStatus.UNKNOWN, 4: ProbeStatus.FEASIBLE,
    })
    monkeypatch.setattr("src.busqueda_n_pallets.probe", fake_probe)

    state = BusquedaState(hard_lower_bound=1)
    state.registrar_feasible_directo(10, pallets=["diez"])
    politica_a_descenso(state, {}, {}, {}, {}, {}, "CD", [0], True, max_solves=5)

    assert llamadas == [9, 8, 7, 6, 5]  # se detiene en max_solves, nunca llega a 4
    assert state.solves_realizados == 5
    assert state.best_feasible == 10  # no mejoró -4 (FEASIBLE) nunca se probó
    assert state.optimality_status() == "BEST_FEASIBLE_UNPROVEN"


def test_policy_a_nunca_prueba_por_debajo_del_hard_bound(monkeypatch):
    fake_probe, llamadas = _fake_probe_factory({4: ProbeStatus.UNKNOWN})
    monkeypatch.setattr("src.busqueda_n_pallets.probe", fake_probe)

    state = BusquedaState(hard_lower_bound=4)
    state.registrar_feasible_directo(5, pallets=["cinco"])
    politica_a_descenso(state, {}, {}, {}, {}, {}, "CD", [0], True)

    assert llamadas == [4]  # se detiene ahí, 3 nunca se prueba (ya es INFEASIBLE_PROVEN gratis)
    assert state.estado(3) is EstadoN.INFEASIBLE_PROVEN


def test_policy_a_nunca_re_sondea_un_n_ya_conocido(monkeypatch):
    """Si un N ya tiene estado registrado (por ejemplo, otra rama ya lo
    probó antes de llamar a la política), no debe volver a gastar un
    solve en él."""
    fake_probe, llamadas = _fake_probe_factory({7: ProbeStatus.FEASIBLE, 6: ProbeStatus.UNKNOWN})
    monkeypatch.setattr("src.busqueda_n_pallets.probe", fake_probe)

    state = BusquedaState(hard_lower_bound=6)
    state.registrar_feasible_directo(9, pallets=["nueve"])
    state.registrar(ProbeResult(8, ProbeStatus.UNKNOWN, None, 8, 10, 0.01))  # ya probado de antemano
    politica_a_descenso(state, {}, {}, {}, {}, {}, "CD", [0], True)

    assert llamadas == [7, 6]  # jamás volvió a probar 8 -y sigue bajando hasta el hard_lb (persistente)
    assert state.best_feasible == 7


def test_policy_a_requiere_incumbente_feasible_ya_registrado():
    state = BusquedaState(hard_lower_bound=1)
    with pytest.raises(AssertionError):
        politica_a_descenso(state, {}, {}, {}, {}, {}, "CD", [0], True)


def test_policy_a_max_solves_default_es_5():
    sig = inspect.signature(politica_a_descenso)
    assert sig.parameters["max_solves"].default == POLICY_A_MAX_SOLVES == 5
