"""[PATCH V6.12-RC2-A -"Weight informational only"] El peso (`Peso bruto por unidad`) puede calcularse y reportarse, pero NO puede
participar en el bound, la factibilidad, el pruning, el orden de candidatos, el score ni la selección de solución: su semántica
contractual no está validada.

Regresión del falso `INFEASIBLE_PROVEN` descubierto en RC2-D1: un pallet real de BK35 (4 SKU, 188 cajas, ocupación volumétrica mínima
0,79) fue declarado infactible por `hard_lower_bound` solo porque su peso calculado (1604 kg, con cajas de peso 0 contadas como 0)
superaba `PESO_TOPE_ELASTICO_KG` (1430). Acá se reproduce con datos sintéticos (no hay datos reales en el repo)."""
import inspect
import re

import pytest

import config
import src.busqueda_n_pallets as bnp
import src.exact_repair as er
import src.global_rescue as gr
import src.packing_bloques as pb
import src.repair_solver as rp
import src.rescue_solver as rs
from src.busqueda_n_pallets import BusquedaState, EstadoN, hard_lower_bound
from src.packing_columnar import _altura_presupuesto
from src.torres import TorreCandidate


def _cand(sku, largo, ancho, alto, peso_unitario):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 20, 10_000, peso_unitario)


def _escenario_bk35_pallet_real(peso_total_kg):
    """Composición cuya ocupación volumétrica mínima es ~0,79 de UN pallet (bound de volumen = 1) y cuyo peso total es
    `peso_total_kg`. 4 SKU, 188 cajas, como el pallet real."""
    vol_util = config.PALLET_LARGO_EFECTIVO * config.PALLET_ANCHO_EFECTIVO * _altura_presupuesto()
    cantidades = {"A": 60, "B": 50, "C": 40, "D": 38}   # 188 cajas
    lados = {"A": (30.0, 25.0), "B": (40.0, 20.0), "C": (25.0, 25.0), "D": (35.0, 30.0)}
    # alto común calibrado para que el volumen total sea 0,79 del volumen útil
    area_total = sum(lados[s][0] * lados[s][1] * q for s, q in cantidades.items())
    alto = 0.79 * vol_util / area_total
    peso_unit = peso_total_kg / sum(cantidades.values())
    por_sku = {s: [_cand(s, lados[s][0], lados[s][1], alto, peso_unit)] for s in cantidades}
    return cantidades, por_sku


def test_regresion_bk35_pallet_pesado_no_es_infactible_por_peso():
    pendientes, por_sku = _escenario_bk35_pallet_real(peso_total_kg=1604.0)
    assert 1604.0 > config.PESO_TOPE_ELASTICO_KG                      # el peso SÍ supera el tope que antes subía el bound
    assert hard_lower_bound(pendientes, por_sku, {}) == 1             # ahora: el bound lo deciden volumen y Cajas por PH
    estado = BusquedaState(hard_lower_bound=hard_lower_bound(pendientes, por_sku, {}))
    assert estado.estado(1) is not EstadoN.INFEASIBLE_PROVEN          # N=1 ya no se "prueba" infactible
    assert estado.estado(1) is EstadoN.UNTESTED


@pytest.mark.parametrize("peso_unitario", [0.0, 0.001, 1.0, 100.0, 1e6])
def test_el_bound_no_depende_del_peso(peso_unitario):
    pendientes, por_sku = _escenario_bk35_pallet_real(peso_total_kg=188 * peso_unitario)
    assert hard_lower_bound(pendientes, por_sku, {}) == 1


def test_volumen_y_cajas_por_ph_siguen_decidiendo_el_bound():
    """La eliminación del peso no debilita los otros dos bounds."""
    vol_util = config.PALLET_LARGO_EFECTIVO * config.PALLET_ANCHO_EFECTIVO * _altura_presupuesto()
    caja = 10.0
    cantidad = int(2.5 * vol_util / (caja ** 3))
    assert hard_lower_bound({"A": cantidad}, {"A": [_cand("A", caja, caja, caja, 0.0)]}, {}) == 3   # volumen
    assert hard_lower_bound({"A": 500}, {"A": [_cand("A", 1, 1, 1, 0.0)]}, {"A": 50}) == 10          # Cajas por PH


def test_hard_lower_bound_no_referencia_el_peso():
    fuente = inspect.getsource(hard_lower_bound)
    codigo = "\n".join(l for l in fuente.splitlines() if not l.strip().startswith(("#",)))
    cuerpo = codigo.split('"""')[-1]            # sin docstring
    assert "peso" not in cuerpo.lower()


@pytest.mark.parametrize("modulo", [bnp, pb, gr, rs, rp, er])
def test_ningun_modulo_del_solver_usa_constantes_de_peso(modulo):
    """Auditoría RC2-A: el solver no puede leer `config.PESO_*` (alerta/tope/duro) para decidir nada."""
    fuente = inspect.getsource(modulo)
    assert not re.search(r"config\.PESO_", fuente), modulo.__name__
