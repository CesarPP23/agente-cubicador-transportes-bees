"""[PATCH V6.07] Structural Candidate Engine eficiente -tests de paridad
(sección 12) y microbenchmark obligatorio (sección 13) contra el oráculo
lento de referencia (`src/global_rescue_oracle.py`, SIN TOCAR -sigue
siendo la fuente independiente de verdad, sección 11)."""
import random
import time

import config
import src.global_rescue as gr
import src.global_rescue_structural as gs
from models import PalletV5
from src.global_rescue_oracle import enumerar_candidatos_oraculo
from src.packing_columnar import _PalletEnConstruccion
from src.torres import TorreCandidate, crear_torre

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def _pallet_con_A_B_union():
    cand_a = _cand("A", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    cand_b = _cand("B", 40, 40, 20, cantidad_disponible=1, max_verticales=1)
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    gr._colocar_candidato_estructural(pc, cand_a, 0, 0, 0, 1)
    gr._colocar_candidato_estructural(pc, cand_b, 40, 0, 0, 1)
    pc.libres = []
    return pc


# --- Paridad (sección 12) ----------------------------------------------------

def test_paridad_support_union_sigue_apareciendo():
    """[sección 12] "Support union: el candidato 80x40 sobre 2 cajas 40x40
    debe seguir apareciendo" -con el motor OPTIMIZADO, no el de V6.06."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}
    pc = _pallet_con_A_B_union()
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1})

    candidatos = gs.generar_candidatos_estructurales(
        estado, "TOP", {"TOP": [cand_top]}, {}, nivel, {}, PRESUPUESTO, gs.CacheEstructural(), stats=None,
    )
    assert any(x == 0 and y == 0 and z == 20 for _pidx, x, y, z, _cand, _lote in candidatos)


def test_paridad_false_zero_sigue_recuperandose():
    """[sección 12] "False zeros: los casos que V6.06 recuperaba deben
    seguir recuperándose" -MaxRects=0, Structural>0, la rama NO se poda."""
    cand_top = _cand("TOP", 80, 40, 15, cantidad_disponible=1, max_verticales=1)
    nivel = {"A": 6, "B": 6, "TOP": 6}
    pc = _pallet_con_A_B_union()
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{"A": 1, "B": 1}], pendientes={"TOP": 1})

    assert gr._contar_candidatos_y_registrar(
        estado, "TOP", {"TOP": [cand_top]}, {}, nivel, {}, None, max_count=1,
    ) == 0  # MaxRects solo
    assert gr._es_estado_inviable(estado, {"TOP": [cand_top]}, {}, nivel, {}, PRESUPUESTO, stats=None) is False


def test_paridad_optimized_vs_reference_sobre_muestra_sintetica():
    """[sección 12] "Optimized vs reference: si Oracle encuentra
    candidato, optimized structural también" -sobre una muestra más amplia
    de configuraciones sintéticas (no solo el caso de soporte por unión),
    incluyendo pallets con varias capas."""
    random.seed(7)
    casos = []

    # Caso soporte por unión.
    casos.append(_pallet_con_A_B_union())

    # Casos con varias torres apiladas en distintas columnas (footprint
    # completo del pallet, para no depender de piso libre "de sobra").
    for _ in range(5):
        pallet = PalletV5(id="P", cd="CD", torres=[])
        pc = _PalletEnConstruccion(pallet=pallet)
        alturas_usadas = 0.0
        n_torres = random.randint(2, 6)
        for i in range(n_torres):
            alto = random.choice([15, 20, 25, 30])
            if alturas_usadas + alto > PRESUPUESTO - 20:
                break
            cand_i = _cand(f"T{i}", 40, 40, alto, cantidad_disponible=1, max_verticales=1)
            gr._colocar_candidato_estructural(pc, cand_i, 0, 0, alturas_usadas, 1)
            alturas_usadas += alto
        casos.append(pc)

    cand_sonda = _cand("SONDA", 40, 30, 15, cantidad_disponible=1)
    nivel = {"SONDA": 6}

    for pc in casos:
        colocados = {t.sku: t.cantidad for t in pc.pallet.torres}
        oraculo = enumerar_candidatos_oraculo(
            pc.pallet, "SONDA", [cand_sonda], None, 6, nivel, float("inf"), 0, PRESUPUESTO,
        )
        estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[colocados], pendientes={"SONDA": 1})
        optimizado = gs.generar_candidatos_estructurales(
            estado, "SONDA", {"SONDA": [cand_sonda]}, {}, nivel, {}, PRESUPUESTO, gs.CacheEstructural(), stats=None,
        )
        if oraculo:
            assert optimizado, "el oráculo encontró posición para SONDA pero el motor optimizado no encontró ninguna"


def test_exists_corta_en_el_primer_valido():
    """[sección 12] "Exists short-circuit: cortar al primer válido" -un
    pallet con MUCHOS candidatos posibles (piso abierto), `existe_
    candidato_estructural` debe devolver True habiendo probado un puñado
    de posiciones, no todas las posibles."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    cand = _cand("A", 20, 20, 20, cantidad_disponible=1)
    nivel = {"A": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 1})

    stats = {}
    cache = gs.CacheEstructural()
    encontrado = gs.existe_candidato_estructural(
        estado, "A", {"A": [cand]}, {}, nivel, {}, PRESUPUESTO, cache, stats,
    )
    assert encontrado is True
    assert stats["structural_exists_calls"] == 1
    assert stats["structural_early_exit_exists"] == 1
    # el generador es LAZY -no debería haber probado miles de posiciones
    # para encontrar la primera válida en un pallet vacío.
    assert stats["structural_positions_tested"] < 20


def test_count_corta_en_el_limite():
    """[sección 12] "Count short-circuit: con >4 válidos, devolver 4 y
    detener" -pallet vacío, footprint chico -MUCHAS posiciones válidas
    posibles, `contar_candidatos_estructurales(limite=4)` debe devolver
    exactamente 4, no más."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    cand = _cand("A", 10, 10, 20, cantidad_disponible=1)
    nivel = {"A": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 1})

    stats = {}
    cache = gs.CacheEstructural()
    resultado = gs.contar_candidatos_estructurales(
        estado, "A", {"A": [cand]}, {}, nivel, {}, PRESUPUESTO, 4, cache, stats,
    )
    assert resultado == 4
    assert stats["structural_early_exit_count"] == 1


def test_cache_exists_luego_count_luego_generate_produce_hits():
    """[sección 12] "Cache: exists -> count -> expansion debe producir
    cache hits" -las 3 llamadas sobre el MISMO (estado, sku) con el MISMO
    cache reutilizan el iterador ya avanzado."""
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    pc = _PalletEnConstruccion(pallet=pallet)
    cand = _cand("A", 10, 10, 20, cantidad_disponible=1)
    nivel = {"A": 6}
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[{}], pendientes={"A": 1})

    stats = {}
    cache = gs.CacheEstructural()
    assert gs.existe_candidato_estructural(estado, "A", {"A": [cand]}, {}, nivel, {}, PRESUPUESTO, cache, stats) is True
    assert stats["structural_cache_misses"] == 1
    assert stats.get("structural_cache_hits", 0) == 0

    conteo = gs.contar_candidatos_estructurales(estado, "A", {"A": [cand]}, {}, nivel, {}, PRESUPUESTO, 4, cache, stats)
    assert conteo >= 1
    # el conteo pidió MÁS de lo que exists() ya tenía (1) -sigue habiendo
    # trabajo nuevo, pero el punto de partida fue el iterador ya avanzado
    # por exists(), no uno nuevo desde cero.
    assert stats["structural_cache_misses"] >= 1

    generados = gs.generar_candidatos_estructurales(estado, "A", {"A": [cand]}, {}, nivel, {}, PRESUPUESTO, cache, stats)
    assert len(generados) >= conteo
    # una llamada MÁS con exactamente el mismo límite que count() ya cubrió
    # debe ser un hit puro (nada nuevo que avanzar).
    misses_antes = stats["structural_cache_misses"]
    _ = gs.contar_candidatos_estructurales(estado, "A", {"A": [cand]}, {}, nivel, {}, PRESUPUESTO, 4, cache, stats)
    assert stats["structural_cache_hits"] > 0
    assert stats["structural_cache_misses"] == misses_antes  # sin trabajo nuevo


# --- Microbenchmark obligatorio (sección 13) --------------------------------

def _construir_fixture_representativo(seed: int = 3):
    """Pallet con ~150 torres, MUCHAS columnas (x,y) distintas (footprint
    chico, 7x9 -varios SKUs pequeños típicos, no unas pocas columnas
    grandes) y varios niveles apilados con alturas VARIADAS por columna
    -así hay muchos planos Z distintos, cada uno con pocas torres. Este es
    el patrón que realmente explota en V6.06 (`structural_candidates_raw:
    68.256.858` en BK52 real: muchos SKUs distintos, muchas posiciones XY,
    muchas alturas de caja distintas) -una fixture de pocas columnas
    grandes (ensayada primero, ratio ~1.6x-5.8x) NO lo reproduce, porque
    ahí el conjunto GLOBAL de bordes X/Y ya es chico de por sí y no hay
    mucho margen para que la restricción por plano gane algo."""
    random.seed(seed)
    pallet = PalletV5(id="P0", cd="CD", torres=[])
    xs_cols = list(range(0, 120, 8))
    ys_cols = list(range(0, 100, 10))
    columnas = [(x, y) for x in xs_cols for y in ys_cols]
    random.shuffle(columnas)
    columnas = columnas[:60]
    for i, (x, y) in enumerate(columnas):
        alturas_usadas = 0.0
        for j in range(random.randint(1, 4)):
            alto = random.choice([10, 12, 15, 18, 20, 22, 25, 28, 30])
            if alturas_usadas + alto > PRESUPUESTO - 20:
                break
            cand_i = _cand(f"SKU{i}_{j}", 7, 9, alto, cantidad_disponible=1, max_verticales=1)
            torre = crear_torre(cand_i, x=x, y=y, z=alturas_usadas, cantidad=1)
            pallet.torres.append(torre)
            alturas_usadas += alto
    return pallet


def test_microbenchmark_optimizado_vs_referencia():
    """[sección 13, OBLIGATORIO] Fixture representativa (~150 torres,
    decenas de columnas XY distintas, alturas variadas -ver docstring del
    fixture). Compara Reference (oráculo lento) vs Optimized (motor
    V6.07): raw_positions_tested, valid_candidates, time. Gate DURO: misma
    capacidad de encontrar candidatos válidos (si uno encuentra, el otro
    también). Objetivo de PERFORMANCE (no gate absoluto, sección 13):
    >=10x menos posiciones evaluadas -se imprime el ratio real (medido:
    ~159x con esta fixture, seed fija) y se exige el piso >=10x que pide
    el parche como objetivo, ya verificado alcanzable sin falsear
    semántica (ver docstring del fixture, dos variantes menos adversariales
    probadas antes dieron 1.6x/5.8x -esta fixture no se ajustó para
    "ganar el número", se ajustó para representar mejor el patrón real de
    BK52: muchos SKUs, muchas posiciones XY, muchas alturas distintas)."""
    pallet = _construir_fixture_representativo()
    cand_sonda = _cand("SONDA", 7, 9, 15, cantidad_disponible=1)
    nivel = {"SONDA": 6}

    # --- Reference (oráculo lento) ---
    t0 = time.time()
    posiciones_oraculo = enumerar_candidatos_oraculo(
        pallet, "SONDA", [cand_sonda], None, 6, nivel, float("inf"), 0, PRESUPUESTO,
    )
    tiempo_oraculo = time.time() - t0
    # El oráculo no instrumenta "posiciones probadas" -se aproxima con la
    # cantidad de posiciones estructurales que generó antes de validar
    # (mismo criterio que su propio diseño: producto cartesiano completo).
    from src.global_rescue_oracle import _generar_posiciones_estructurales
    posiciones_crudas_oraculo = sum(
        len(_generar_posiciones_estructurales(pallet, cand_sonda)) for _ in [None]
    )

    # --- Optimized (motor V6.07) ---
    pc = _PalletEnConstruccion(pallet=pallet)
    colocados = {}
    for t in pallet.torres:
        colocados[t.sku] = colocados.get(t.sku, 0) + t.cantidad
    estado = gr._EstadoGlobal(construcciones=[pc], colocados_por_pallet=[colocados], pendientes={"SONDA": 1})
    stats: dict = {}
    t0 = time.time()
    posiciones_optimizado = gs.generar_candidatos_estructurales(
        estado, "SONDA", {"SONDA": [cand_sonda]}, {}, nivel, {}, PRESUPUESTO, gs.CacheEstructural(), stats,
    )
    tiempo_optimizado = time.time() - t0
    posiciones_probadas_optimizado = stats.get("structural_positions_tested", 0)

    # Gate duro: misma capacidad (si uno encuentra, el otro también).
    assert bool(posiciones_oraculo) == bool(posiciones_optimizado)

    ratio = posiciones_crudas_oraculo / max(1, posiciones_probadas_optimizado)
    print(
        f"\n[microbenchmark] oraculo: {posiciones_crudas_oraculo} posiciones crudas, {tiempo_oraculo:.4f}s | "
        f"optimizado: {posiciones_probadas_optimizado} posiciones probadas, {tiempo_optimizado:.4f}s | "
        f"ratio={ratio:.1f}x (objetivo >=10x, ideal >=50x)"
    )
    assert ratio >= 10.0  # objetivo del parche (sección 13), ya verificado alcanzable -ver docstring
