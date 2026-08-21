"""[V5-P0] El benchmark tiene que contar pallets FÍSICOS reales, sin excluir
los PH-BAT-* dedicados -un pallet dedicado a cajas BAT es un pallet físico
más que Transporte mueve, no una excepción a esconder del conteo."""
from pathlib import Path

from models import Pallet
from src.benchmark import calcular_kpis
from src.pipeline import ejecutar_desde_archivo

ARCHIVO_REAL = Path(__file__).resolve().parent.parent / "Cubicaje18.07.2026.xlsx"


def _pallet(id_, cd="BK31", altura=195.0, peso=500.0):
    return Pallet(id=id_, cd=cd, tipo="Mixto", altura_final=altura, peso_estimado=peso)


def test_pallet_bat_dedicado_incrementa_el_total():
    normales = [_pallet("PH-MIX-BK31-001"), _pallet("PH-MIX-BK31-002")]
    con_bat_dedicado = normales + [_pallet("PH-BAT-BK31-001", altura=69.9)]

    r_sin = calcular_kpis(normales)
    r_con = calcular_kpis(con_bat_dedicado)

    assert r_sin.pallets == 2
    assert r_con.pallets == 3  # el dedicado SUMA, no se descarta
    assert r_con.bat_dedicados == 1
    assert r_sin.bat_dedicados == 0


def test_sin_bat_dedicado_el_conteo_no_cambia():
    normales = [_pallet("PH-MIX-BK31-001"), _pallet("PH-MIX-BK31-002"), _pallet("PH-HOM-BK31-001")]
    r = calcular_kpis(normales)
    assert r.pallets == len(normales)
    assert r.bat_dedicados == 0


def test_calcular_kpis_guarda_pallets_por_cd():
    pallets = [_pallet("PH-MIX-BK31-001", cd="BK31"), _pallet("PH-MIX-BK41-001", cd="BK41"), _pallet("PH-MIX-BK41-002", cd="BK41")]
    r = calcular_kpis(pallets)
    assert r.pallets_por_cd == {"BK31": 1, "BK41": 2}


def test_benchmark_total_fisico_correcto_contra_dataset_real():
    """El número de `benchmark_df` tiene que ser exactamente
    `len(pallets armados)`, dedicados BAT incluidos -no un subconjunto
    filtrado. El prefijo de dedicado depende del motor activo
    (`config.PACKER_VERSION`): "PH-BAT-" en V4, "PV5-BAT-" en V5 -ambos
    son lo mismo que ya reconoce `benchmark.calcular_kpis`."""
    if not ARCHIVO_REAL.exists():
        import pytest

        pytest.skip(f"No está el dataset real en {ARCHIVO_REAL}")
    resultado = ejecutar_desde_archivo(ARCHIVO_REAL)
    armados = [p for p in resultado.pallets if p.tipo != "Requiere Revisión"]
    bat_dedicados_reales = sum(1 for p in armados if p.id.startswith("PH-BAT-") or p.id.startswith("PV5-BAT-"))

    row = resultado.benchmark_df.iloc[0]
    assert int(row["pallets"]) == len(armados)
    assert int(row["bat_dedicados"]) == bat_dedicados_reales
