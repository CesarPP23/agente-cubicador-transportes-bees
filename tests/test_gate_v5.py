"""[V5-P14] Gate formal: V5 no reemplaza a V4 por defecto hasta que un
BenchmarkResultado real apruebe TODOS los criterios a la vez -ninguno se
relaja para hacer pasar el benchmark."""
from src.benchmark import BenchmarkResultado, evaluar_gate_v5


def _resultado(**overrides):
    base = dict(
        dataset_hash="x", commit="x", config_hash="x",
        pallets=43, altura_media=195.0, altura_min=180.0, altura_max=214.0,
        parciales=0, demanda_unidades_error=0.0, geometria_inferida_count=0,
    )
    base.update(overrides)
    return BenchmarkResultado(**base)


def test_aprueba_cuando_todo_esta_dentro_de_los_criterios():
    gate = evaluar_gate_v5(_resultado())
    assert gate.aprobado is True
    assert gate.razones == []


def test_rechaza_por_pallets_fuera_de_rango():
    gate = evaluar_gate_v5(_resultado(pallets=61))
    assert gate.aprobado is False
    assert any("pallets=61" in r for r in gate.razones)


def test_rechaza_por_demanda_no_exacta():
    gate = evaluar_gate_v5(_resultado(demanda_unidades_error=3.0))
    assert gate.aprobado is False
    assert any("demanda_unidades_error" in r for r in gate.razones)


def test_rechaza_por_altura_sobre_tope_real():
    gate = evaluar_gate_v5(_resultado(altura_max=220.0))
    assert gate.aprobado is False
    assert any("altura_max" in r for r in gate.razones)


def test_rechaza_por_violaciones_geometricas():
    gate = evaluar_gate_v5(_resultado(), violaciones_geometria=["P1: overlap", "P2: overflow"])
    assert gate.aprobado is False
    assert gate.violaciones_geometria == 2


def test_acumula_todas_las_razones_de_rechazo_sin_detenerse_en_la_primera():
    gate = evaluar_gate_v5(_resultado(pallets=61, demanda_unidades_error=1.0, altura_max=220.0))
    assert len(gate.razones) == 3
