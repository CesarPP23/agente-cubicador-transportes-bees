"""Tests de invariantes: propiedades que deben cumplirse SIEMPRE, sin
depender del algoritmo de armado interno. Sobreviven a refactors y son los
que de verdad protegen el plan de picking.

Cómo correrlos:
    pytest tests/test_invariantes.py -v
"""

from pathlib import Path

import pandas as pd
import pytest

import config
from src.pipeline import ejecutar_pipeline

RAIZ = Path(__file__).resolve().parents[1]
DATASET = RAIZ / "Cubicaje18.07.2026.xlsx"


@pytest.fixture(scope="module")
def resultado():
    if not DATASET.exists():
        pytest.skip(f"No está el dataset real en {DATASET}")
    envios = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    maestro = pd.read_excel(DATASET, sheet_name="Maestro_SKUs")
    uma = pd.read_excel(DATASET, sheet_name="UMA")
    return ejecutar_pipeline(envios, maestro, uma)


@pytest.fixture(scope="module")
def demanda_oficial():
    if not DATASET.exists():
        pytest.skip(f"No está el dataset real en {DATASET}")
    envios = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    envios["SKU"] = envios["SKU"].astype(str).str.strip()  # normalización de src/validacion.py:_normalizar_sku
    envios = envios[envios["Cajas Teóricas"] > 0]
    agrupado = envios.groupby(["CD", "SKU"])["Cajas Teóricas"].sum()
    import math
    return {clave: math.ceil(valor) for clave, valor in agrupado.items()}


def test_ningun_pallet_supera_el_tope_duro(resultado):
    """Restricción física dura: config.ALTURA_TOPE_DURO es el techo absoluto."""
    excedidos = [
        (p.id, round(p.altura_final, 2))
        for p in resultado.pallets
        if p.altura_final > config.ALTURA_TOPE_DURO + 1e-6
    ]
    assert not excedidos, f"Pallets fuera del tope duro: {excedidos}"


def test_nunca_se_despacha_por_encima_de_la_demanda(resultado, demanda_oficial):
    """El motor nunca debe inventar cajas. `Cajas_Extra_Consolidacion` está
    en 0 por diseño, así que el plan debe ser <= demanda redondeada."""
    despachado: dict[tuple, int] = {}
    for pallet in resultado.pallets:
        for linea in pallet.lineas:
            clave = (pallet.cd, linea.sku)
            total = linea.cajas_demanda_oficial + linea.cajas_extra_consolidacion
            despachado[clave] = despachado.get(clave, 0) + total

    excesos = {
        clave: (cantidad, demanda_oficial.get(clave, 0))
        for clave, cantidad in despachado.items()
        if cantidad > demanda_oficial.get(clave, 0)
    }
    assert not excesos, f"Se despachó de más en: {excesos}"


def test_peso_se_reporta_pero_no_bloquea(resultado):
    """La única restricción DURA de armado es la altura
    (config.PESO_ES_RESTRICCION_DURA = False por defecto) -el peso se sigue
    calculando y reportando (ESTADO_ALERTA_PESO en validacion_peso.py) pero
    no bloquea el armado. Acá solo se verifica que sea un número real y
    positivo -no que esté acotado."""
    assert not config.PESO_ES_RESTRICCION_DURA
    for pallet in resultado.pallets:
        assert pallet.peso_estimado >= 0


def test_determinismo(demanda_oficial):
    """Dos corridas con el mismo input deben dar exactamente el mismo Excel.
    Sin esto no se puede diffear la corrida de hoy contra la de ayer."""
    if not DATASET.exists():
        pytest.skip(f"No está el dataset real en {DATASET}")
    envios = pd.read_excel(DATASET, sheet_name="Envios_Julio")
    maestro = pd.read_excel(DATASET, sheet_name="Maestro_SKUs")
    uma = pd.read_excel(DATASET, sheet_name="UMA")

    primera = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())
    segunda = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())

    pd.testing.assert_frame_equal(primera.plan_picking_df, segunda.plan_picking_df)
    pd.testing.assert_frame_equal(primera.resumen_cd_df, segunda.resumen_cd_df)


def test_ids_de_pallet_unicos(resultado):
    ids = [p.id for p in resultado.pallets]
    duplicados = {i for i in ids if ids.count(i) > 1}
    assert not duplicados, f"IDs de pallet duplicados: {duplicados}"


# --------------------------------------------------------------------------
# Métrica de referencia (no es un assert: imprime para comparar antes/después)
# --------------------------------------------------------------------------

def test_reporte_de_ocupacion(resultado, capsys):
    """No falla nunca: imprime los KPIs para comparar antes/después.
    Correr con `pytest -s` para verlos."""
    total = len(resultado.pallets)
    if total == 0:
        pytest.skip("Sin pallets")
    parciales = sum(1 for p in resultado.pallets if p.altura_final < config.ALTURA_TOTAL_MIN_TOLERADO)
    altura_prom = sum(p.altura_final for p in resultado.pallets) / total
    peso_prom = sum(p.peso_estimado for p in resultado.pallets) / total

    with capsys.disabled():
        print("\n--- Ocupación ---")
        print(f"Pallets totales:        {total}")
        print(f"Pallets parciales:      {parciales} ({parciales / total:.0%})")
        print(f"Altura promedio:        {altura_prom:.1f} cm de {config.ALTURA_TOTAL_MAX}")
        print(f"Aprovechamiento altura: {altura_prom / config.ALTURA_TOTAL_MAX:.0%}")
        print(f"Peso promedio:          {peso_prom:.1f} kg de {config.PESO_TOPE_ELASTICO_KG}")
    assert total > 0
