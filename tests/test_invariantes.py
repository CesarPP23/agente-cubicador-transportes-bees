"""[PARCHE P10] Tests de invariantes.

`test_pipeline_real_data.py` es un golden test: detecta que algo CAMBIÓ, pero no
distingue una mejora de una regresión, y se rompe apenas se toca la heurística
(que es exactamente lo que hacen los parches P1/P2/P4/P5).

Estos tests son distintos: verifican propiedades que deben cumplirse SIEMPRE,
con cualquier algoritmo de packing. Sobreviven a refactors y son los que de
verdad protegen el plan de picking.

Cómo correrlos:
    pytest tests/test_invariantes.py -v

NOTA DE IMPORTS: este archivo asume que `config`, `models` y `src.*` se importan
igual que en el resto de la suite existente. Si los tests actuales usan
`from packing_2d import ...` en vez de `from src.packing_2d import ...`, ajustar
las dos líneas marcadas abajo.
"""

from pathlib import Path

import pandas as pd
import pytest

import config
from src.packing_2d import _elegir_orientacion  # <-- ajustar import si hace falta
from src.pipeline import ejecutar_pipeline      # <-- ajustar import si hace falta

RAIZ = Path(__file__).resolve().parents[1]
DATASET = RAIZ / "Cubicaje18.07.2026.xlsx"

NIVEL_REMATE = 7  # las camas de remate tienen nivel_categoria = None


# --------------------------------------------------------------------------
# P1 — orientación: casos calculados a mano, sin depender de data real
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "largo, ancho, cajas_esperadas",
    [
        # El caso que rompía: 4x1=4 (criterio viejo, "más columnas") vs 2x4=8
        (25, 51, 8),
        # Simétrico: la mejor opción es la que tiene MENOS columnas
        (51, 25, 8),
        # Caso donde ambas orientaciones empatan
        (30, 30, 12),   # 4 col x 3 filas
        # Caja que solo entra en una orientación
        (110, 40, 2),   # 1 col x 2 filas
    ],
)
def test_orientacion_maximiza_cajas_totales(largo, ancho, cajas_esperadas):
    """La orientación elegida debe maximizar columnas x filas, no solo columnas."""
    resultado = _elegir_orientacion(largo, ancho)
    assert resultado is not None
    w, d, _columnas = resultado
    cajas = int(config.PALLET_LARGO // w) * int(config.PALLET_ANCHO // d)
    assert cajas == cajas_esperadas


def test_orientacion_nunca_peor_que_la_alternativa():
    """Para cualquier caja, la orientación elegida es >= la otra orientación."""
    for largo in range(10, 121, 7):
        for ancho in range(10, 101, 7):
            resultado = _elegir_orientacion(largo, ancho)
            if resultado is None:
                continue
            w, d, _ = resultado
            elegida = int(config.PALLET_LARGO // w) * int(config.PALLET_ANCHO // d)
            alternativas = []
            for ww, dd in ((largo, ancho), (ancho, largo)):
                if ww > config.PALLET_LARGO or dd > config.PALLET_ANCHO:
                    continue
                alternativas.append(int(config.PALLET_LARGO // ww) * int(config.PALLET_ANCHO // dd))
            assert elegida == max(alternativas), f"caja {largo}x{ancho}: eligió {elegida}, mejor {max(alternativas)}"


def test_orientacion_devuelve_none_si_no_cabe():
    assert _elegir_orientacion(452, 452) is None


# --------------------------------------------------------------------------
# Invariantes sobre el pipeline completo
# --------------------------------------------------------------------------

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


def test_ningun_pallet_supera_la_altura_maxima(resultado):
    """Restricción física dura: 195 cm incluyendo el pallet vacío."""
    excedidos = [
        (p.id, round(p.altura_final, 2))
        for p in resultado.pallets
        if p.altura_final > config.ALTURA_TOTAL_MAX + 1e-6
    ]
    assert not excedidos, f"Pallets fuera de altura máxima: {excedidos}"


def test_nunca_se_despacha_por_encima_de_la_demanda(resultado, demanda_oficial):
    """[P2/P4] El motor nunca debe inventar cajas. `Cajas_Extra_Consolidacion`
    está en 0 por diseño, así que el plan debe ser <= demanda redondeada."""
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


def test_orden_vertical_de_categorias(resultado):
    """Las camas de un pallet deben ir de nivel menor (base) a mayor (arriba).
    Es la regla de estabilidad de la sección 9.1 del doc de diseño."""
    fallas = []
    for pallet in resultado.pallets:
        niveles = [c.nivel_categoria if c.nivel_categoria is not None else NIVEL_REMATE for c in pallet.camas]
        if niveles != sorted(niveles):
            fallas.append((pallet.id, niveles))
    assert not fallas, f"Pallets con orden vertical inválido: {fallas}"


def test_remate_exclusivo(resultado):
    """Cigarros y Comestibles nunca comparten pallet (sección 9.3)."""
    fallas = []
    for pallet in resultado.pallets:
        remates = {c.categorias[0] for c in pallet.camas if c.categorias[0] in config.CATEGORIAS_REMATE}
        if len(remates) > 1:
            fallas.append((pallet.id, remates))
    assert not fallas, f"Pallets con remate mixto: {fallas}"


def test_nada_pesado_encima_de_nabs(resultado):
    """Regla NABs (sección 9.2): solo Comestibles o Cigarros pueden ir encima."""
    fallas = []
    for pallet in resultado.pallets:
        vio_nabs = False
        for cama in pallet.camas:
            categoria = cama.categorias[0]
            if vio_nabs and categoria not in config.CATEGORIAS_REMATE and categoria != "NABs":
                fallas.append((pallet.id, categoria))
            if categoria == "NABs":
                vio_nabs = True
    assert not fallas, f"Categorías de nivel 1-5 apoyadas sobre NABs: {fallas}"


def test_peso_respetado_como_restriccion(resultado):
    """[P4] Con el peso como restricción del Paso 4, un pallet solo puede superar
    el tope si una sola cama ya lo supera por sí misma (caso irreducible)."""
    sospechosos = [
        (p.id, round(p.peso_estimado, 1))
        for p in resultado.pallets
        if p.peso_estimado > config.PESO_MAX_PALLET_KG + 1e-6 and len(p.camas) > 1
    ]
    assert not sospechosos, (
        f"Pallets multi-cama por encima del tope de peso: {sospechosos}. "
        "Si el peso es restricción del Paso 4 esto no debería poder ocurrir."
    )


def test_regla_de_soporte(resultado):
    """[P5] Ninguna cama con poca superficie cubierta sostiene otra encima."""
    if config.FILL_RATIO_MIN_SOPORTE <= 0:
        pytest.skip("Regla de soporte desactivada (FILL_RATIO_MIN_SOPORTE = 0)")
    fallas = []
    for pallet in resultado.pallets:
        for inferior in pallet.camas[:-1]:  # todas menos la de más arriba
            if inferior.fill_ratio < config.FILL_RATIO_MIN_SOPORTE - 1e-9:
                fallas.append((pallet.id, round(inferior.fill_ratio, 3)))
    assert not fallas, f"Camas poco cubiertas sosteniendo carga: {fallas}"


def test_determinismo(demanda_oficial):
    """[P3] Dos corridas con el mismo input deben dar exactamente el mismo Excel.
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
    """No falla nunca: imprime los KPIs que hoy el output no reporta.
    Correr con `pytest -s` para verlos y comparar contra la versión sin parches."""
    total = len(resultado.pallets)
    if total == 0:
        pytest.skip("Sin pallets")
    parciales = sum(1 for p in resultado.pallets if p.altura_final < config.ALTURA_TOTAL_MIN)
    altura_prom = sum(p.altura_final for p in resultado.pallets) / total
    peso_prom = sum(p.peso_estimado for p in resultado.pallets) / total

    with capsys.disabled():
        print("\n--- Ocupación ---")
        print(f"Pallets totales:        {total}")
        print(f"Pallets parciales:      {parciales} ({parciales / total:.0%})")
        print(f"Altura promedio:        {altura_prom:.1f} cm de {config.ALTURA_TOTAL_MAX}")
        print(f"Aprovechamiento altura: {altura_prom / config.ALTURA_TOTAL_MAX:.0%}")
        print(f"Peso promedio:          {peso_prom:.1f} kg de {config.PESO_MAX_PALLET_KG}")
    assert total > 0
