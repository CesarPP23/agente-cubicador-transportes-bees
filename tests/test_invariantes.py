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
    """La orientación elegida debe maximizar columnas x filas, no solo columnas.

    [V3 / sección 7] Solo rotación XY (la caja siempre de pie) -"cajas
    acostadas" salió del flujo productivo, ver config.py."""
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


def test_ningun_pallet_supera_el_tope_duro(resultado):
    """Restricción física dura: 210 cm incluyendo el pallet vacío -es el techo
    absoluto (config.ALTURA_TOPE_DURO), no config.ALTURA_TOTAL_MAX (205): un
    pallet que todavía no llegó al mínimo tolerado (185) puede estirarse hasta
    210 para cerrar (ver apilado_3d._limite_altura)."""
    excedidos = [
        (p.id, round(p.altura_final, 2))
        for p in resultado.pallets
        if p.altura_final > config.ALTURA_TOPE_DURO + 1e-6
    ]
    assert not excedidos, f"Pallets fuera del tope duro: {excedidos}"


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


def test_remate_exclusivo(resultado):
    """Cigarros y Comestibles nunca comparten la MISMA cama.

    [V3 / bat._buscar_host_forzado] A nivel PALLET, Comestibles y Cigarros SÍ
    pueden convivir ahora -en capas (camas) distintas- cuando es la única
    forma de que una caja BAT entre en un pallet ya armado: la prioridad de
    negocio explícita es que una caja BAT nunca sea un pallet físico aparte,
    por encima de mantener remates puros por pallet (ver docstring de
    `bat.asignar_hosts_bat`, niveles 1-4). Lo que sigue siendo un invariante
    duro es que NINGUNA cama individual mezcle ambas categorías -eso sí sería
    físicamente imposible (una sola capa no puede ser dos cosas a la vez).
    `Cama.categoria_remate` ya revienta con ValueError si alguna vez pasa,
    así que alcanza con recorrer las camas sin que exploten."""
    for pallet in resultado.pallets:
        for cama in pallet.camas:
            cama.categoria_remate  # no debe levantar ValueError


def test_peso_se_reporta_pero_no_bloquea(resultado):
    """[V4b / fotos de los 42 pallets reales] Confirmado con Omar: la única
    restricción DURA de armado es la altura (config.PESO_ES_RESTRICCION_DURA
    = False por defecto) -el peso se sigue calculando y reportando
    (ESTADO_ALERTA_PESO en validacion_peso.py) pero ya no bloquea una
    combinación que geométricamente conviene, así que un pallet multi-cama
    SÍ puede superar el tope elástico histórico. Lo único que se verifica acá
    es que el peso siga siendo un número real y positivo -no que esté
    acotado."""
    assert not config.PESO_ES_RESTRICCION_DURA
    for pallet in resultado.pallets:
        assert pallet.peso_estimado >= 0


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
