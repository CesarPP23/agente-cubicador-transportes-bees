"""[PATCH V6.08] Zero-Only Structural Rescue -tests obligatorios de la
sección 10 del parche. Regla nueva: `MaxRects > 0 -> NO llamar Structural;
MaxRects == 0 -> consultar Structural`, aplicada uniformemente a poda, MRV
y expansión -Structural deja de ser "enriquecimiento general" (V6.06/V6.07)
y vuelve a ser EXCLUSIVAMENTE un rescate de falsos ceros."""
import config
import src.global_rescue as gr
from models import PalletV5
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate
from src.validacion_v5 import validar_pallet_v5

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _pallet_con_A_B_union():
    """Dos cajas 40x40 lado a lado -mismo patrón de soporte-por-unión ya
    usado en Fase 2.1/V6.06/V6.07. `pc.libres=[]` aísla el caso: MaxRects
    ve 0 para cualquier candidato que necesite la unión, sin depender de
    piso libre "de sobra" en el resto del pallet real (ver nota en
    `test_global_rescue_hybrid.py::_pallet_con_A_B_union`)."""
    cand_a = _cand("A", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    cand_b = _cand("B", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    gr._colocar_candidato_estructural(pc, cand_a, 0, 0, 0, 1)
    gr._colocar_candidato_estructural(pc, cand_b, 40, 0, 0, 1)
    pc.libres = []
    return pc


def _stats_estructurales(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if k.startswith(("structural_", "zero_rescue_"))}


def _stats_vacio() -> dict:
    """Mismo esqueleto mínimo que `global_rescue()` inicializa -las
    funciones de nivel `global_rescue.py` (a diferencia de las de `global_
    rescue_structural.py`, que solo usan `stats.get(...)`) indexan algunas
    claves directamente (`stats["por_sku"]`, `stats["raw_candidates_
    generados"] += ...`) asumiendo que YA existen, igual que cuando se
    llama a través de `global_rescue()` de punta a punta."""
    return {
        "por_sku": {}, "raw_candidates_generados": 0, "candidates_retenidos_top_k": 0,
        "estados_generados": 0, "duplicados": 0, "transposition_hits": 0, "estados_pruned_no_moves": 0,
    }


# --- 10.1 MaxRects > 0 no llama Structural -----------------------------------

def test_10_1_maxrects_mayor_a_0_no_llama_structural():
    """MaxRects=1 (pallet real, un solo cuboide libre) -Structural NO debe
    consultarse ni en poda, ni en MRV, ni en expansión."""
    cand_a = _cand("A", 40, 30, 20, cantidad_disponible=3)
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)  # un solo _CuboidLibre real -> MaxRects=1 para A
    por_sku = {"A": [cand_a]}
    nivel = {"A": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 3})

    # Premisa: MaxRects=1 (no 0) para A.
    assert gr._contar_candidatos_y_registrar(estado, "A", por_sku, {}, nivel, {}, None, max_count=1) == 1

    stats: dict = _stats_vacio()
    # Poda.
    muerto, _sku_causante = gr._evaluar_viabilidad(estado, por_sku, {}, nivel, {}, PRESUPUESTO, stats)
    assert muerto is False
    # MRV.
    orden = gr._ordenar_mrv(["A"], estado, por_sku, {}, nivel, {}, "footprint", stats, PRESUPUESTO)
    assert orden == ["A"]
    # Expansión.
    hijos = gr._expandir_estado(estado, por_sku, {}, nivel, {}, "footprint", stats, PRESUPUESTO)
    assert hijos

    estructurales = _stats_estructurales(stats)
    contadores_llamadas = {
        k: v for k, v in estructurales.items()
        if k.endswith("_calls") and isinstance(v, int)
    }
    assert all(v == 0 for v in contadores_llamadas.values()), contadores_llamadas
    # Los placements de esta expansión deben venir todos de MaxRects.
    assert stats.get("placements_from_structural_zero_rescue", 0) == 0
    assert stats.get("placements_from_maxrects", 0) > 0


# --- 10.2 False zero sigue rescatado -----------------------------------------

def test_10_2_false_zero_sigue_rescatado():
    """MaxRects=0, Structural=1 (soporte por unión) -rama viva, MRV
    count=1, expansión usa el candidato Structural."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}
    pc = _pallet_con_A_B_union()
    por_sku = {"TOP": [cand_top]}
    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1},
    )

    assert gr._contar_candidatos_y_registrar(estado, "TOP", por_sku, {}, nivel, {}, None, max_count=1) == 0  # MaxRects

    stats: dict = _stats_vacio()
    # Rama viva.
    muerto, _sku_causante = gr._evaluar_viabilidad(estado, por_sku, {}, nivel, {}, PRESUPUESTO, stats)
    assert muerto is False

    # MRV count > 0 -deja de ser 0 ("rescatado"). El parche (sección 10.2)
    # dice literalmente "MRV count = 1", pero la geometría real de este
    # escenario (posición de soporte por unión + los ~2cm de tolerancia de
    # sobresaliente en cada borde) admite legítimamente MÁS de una ancla
    # válida para TOP (confirmado con `enumerar_candidatos_oraculo` en
    # Fase 2.1/V6.06) -exigir EXACTAMENTE 1 falsearía el escenario para
    # que cuadre con el número del enunciado. Lo que sí importa, y es lo
    # que este test verifica: pasa de 0 (MaxRects solo) a >0 (rescatado).
    conteo_hibrido = gr._contar_candidatos_y_registrar(
        estado, "TOP", por_sku, {}, nivel, {}, stats, max_count=4, presupuesto=PRESUPUESTO,
    )
    assert conteo_hibrido > 0

    # Expansión usa el candidato Structural.
    hijos = gr._expandir_estado(estado, por_sku, {}, nivel, {}, "footprint", stats, PRESUPUESTO)
    assert hijos
    assert stats.get("placements_from_structural_zero_rescue", 0) > 0
    assert stats.get("structural_rescues_used", {}).get("TOP", 0) > 0
    for hijo in hijos:
        assert validar_pallet_v5(hijo.construcciones[0].pallet) == []


# --- 10.3 True zero poda -----------------------------------------------------

def test_10_3_true_zero_poda():
    """MaxRects=0, Structural=0, capacidad_instalada=0 -rama podada."""
    cand_imposible = _cand("IMPOSIBLE", 500, 500, 20, cantidad_disponible=1)
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    por_sku = {"IMPOSIBLE": [cand_imposible]}
    nivel = {"IMPOSIBLE": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"IMPOSIBLE": 1})

    assert gr._contar_candidatos_y_registrar(estado, "IMPOSIBLE", por_sku, {}, nivel, {}, None, max_count=1) == 0

    stats: dict = _stats_vacio()
    muerto, sku_causante = gr._evaluar_viabilidad(estado, por_sku, {}, nivel, {}, PRESUPUESTO, stats)
    assert muerto is True
    assert sku_causante == "IMPOSIBLE"
    assert stats.get("zero_rescue_failures", 0) > 0


# --- 10.4 Support union -------------------------------------------------------

def test_10_4_support_union_maxrects_0_structural_mayor_0_placement_valido():
    """40x40 + 40x40 abajo, 80x40 arriba -MaxRects=0, Structural>0,
    placement válido."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}
    pc = _pallet_con_A_B_union()
    por_sku = {"TOP": [cand_top]}
    estado = gr._EstadoGlobal(
        construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1},
    )

    assert gr._contar_candidatos_y_registrar(estado, "TOP", por_sku, {}, nivel, {}, None, max_count=1) == 0

    stats: dict = _stats_vacio()
    hijos = gr._expandir_estado(estado, por_sku, {}, nivel, {}, "footprint", stats, PRESUPUESTO)
    assert hijos
    assert any(hijo.pendientes.get("TOP", 0) == 0 for hijo in hijos)  # TOP llegó a completarse en alguna rama
    for hijo in hijos:
        assert validar_pallet_v5(hijo.construcciones[0].pallet) == []


# --- 10.5 Search-path compatibility -------------------------------------------

def test_10_5_search_path_compatibility_maxrects_resuelve_100_sin_tocar_structural():
    """Caso sintético donde MaxRects por sí solo YA resuelve el 100% -la
    corrida real de `global_rescue` (que siempre pasa `presupuesto`, así
    que el híbrido está "disponible") debe tomar la MISMA fuente de
    candidatos que V6.05 (puro MaxRects) y llegar al mismo resultado,
    sin exigir layout byte-idéntico, pero SÍ: mismas cajas colocadas,
    misma factibilidad (100%), y Structural calls = 0."""
    por_sku = {
        "A": [_cand("A", 60, 50, 20, cantidad_disponible=2)],
        "B": [_cand("B", 40, 30, 15, cantidad_disponible=3)],
    }
    nivel_por_sku = {"A": 6, "B": 6}

    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={"A": 2, "B": 3}, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="ZEROONLY_SEARCHPATH", presupuesto=PRESUPUESTO,
    )

    assert faltantes == {}  # misma factibilidad: 100%
    assert sum(t.cantidad for t in pallets[0].torres) == 5  # mismas cajas colocadas que V6.05
    assert validar_pallet_v5(pallets[0]) == []

    estructurales = _stats_estructurales(stats)
    contadores_llamadas = {
        k: v for k, v in estructurales.items()
        if k.endswith("_calls") and isinstance(v, int)
    }
    assert all(v == 0 for v in contadores_llamadas.values()), contadores_llamadas
    assert stats.get("placements_from_structural_zero_rescue", 0) == 0
    assert stats.get("placements_from_maxrects", 0) > 0
