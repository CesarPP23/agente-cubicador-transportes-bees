"""PATCH V6.04 -Repair Solver v2 (coverage-aware scoring, ejection chains,
exact local repair). Tests de las secciones 17-19 que NO dependen de
correr el CD real completo (eso vive en test_multicd_rescue_regression.py,
junto a los gates de BK52/BK53)."""
import config
from models import PalletV5
from src.rescue_solver import _score_solucion, skus_completos
from src.repair_solver import _ArchivoPareto, RESCUE_PARETO_K, _buscar_ejection_chain
from src.torres import TorreCandidate, crear_torre
from src.validacion_v5 import validar_pallet_v5


def _cand(sku, largo, ancho, alto, cantidad_disponible=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, 10, cantidad_disponible, 1.0)


# --- sección 2/3: score coverage-aware ------------------------------------

def test_score_penaliza_romper_sku_protegido_sin_ganancia():
    """Dos soluciones con el MISMO total colocado -una mantiene un SKU
    que ya estaba completo en baseline, la otra lo rompe para colocar
    otro en su lugar- deben preferir la que NO rompe nada ya resuelto."""
    por_sku = {"A": [_cand("A", 20, 20, 20)], "B": [_cand("B", 20, 20, 20)]}
    protegidos = frozenset({"A"})
    pallets = [PalletV5(id="P1", cd="CD", torres=[], altura_final=100.0)]

    # Solución 1: A completo (0 pendiente), B con 1 faltante.
    score_mantiene_a = _score_solucion(9, {"A": 0, "B": 1}, por_sku, pallets, protegidos)
    # Solución 2: mismo total, pero A quedó con 1 faltante (se "rompió" A
    # -que estaba protegido- para colocar B en su lugar).
    score_rompe_a = _score_solucion(9, {"A": 1, "B": 0}, por_sku, pallets, protegidos)

    assert score_mantiene_a > score_rompe_a


def test_score_primero_compara_cantidad_total():
    """El total colocado sigue siendo la prioridad -no se puede preferir
    una solución con MENOS cajas solo por mejor cobertura."""
    por_sku = {"A": [_cand("A", 20, 20, 20)]}
    pallets = [PalletV5(id="P1", cd="CD", torres=[], altura_final=100.0)]
    score_mas_cajas_peor_cobertura = _score_solucion(10, {"A": 5}, por_sku, pallets, frozenset())
    score_menos_cajas_mejor_cobertura = _score_solucion(9, {"A": 0}, por_sku, pallets, frozenset())
    assert score_mas_cajas_peor_cobertura > score_menos_cajas_mejor_cobertura


def test_skus_completos_captura_baseline():
    por_sku = {"A": [_cand("A", 10, 10, 10)], "B": [_cand("B", 10, 10, 10)]}
    pendientes = {"A": 0, "B": 3}
    assert skus_completos(pendientes, por_sku) == frozenset({"A"})


# --- sección 4: Pareto incumbent -------------------------------------------

def test_archivo_pareto_descarta_dominados_y_conserva_no_dominados():
    archivo = _ArchivoPareto(k=RESCUE_PARETO_K)
    # (total, skus_completos, -skus_con_faltantes, ...) -A domina a B.
    score_a = (10, 3, -1, 0, 0.0, 0.0)
    score_b = (8, 2, -2, 0, 0.0, 0.0)  # dominado por A en las 3 primeras dims
    score_c = (9, 4, 0, 0, 0.0, 0.0)  # NO dominado por A: menos cajas, pero MÁS cobertura -tradeoff real

    archivo.considerar(score_a, "snap_a")
    archivo.considerar(score_b, "snap_b")
    archivo.considerar(score_c, "snap_c")

    scores_en_archivo = {s for s, _ in archivo.items}
    assert score_a in scores_en_archivo
    assert score_b not in scores_en_archivo  # dominado -descartado
    assert score_c in scores_en_archivo  # no dominado -conservado
    assert archivo.mejor()[0] == score_a


def test_archivo_pareto_respeta_tamano_maximo():
    archivo = _ArchivoPareto(k=2)
    for i in range(5):
        # cada uno con MÁS SKUs completos que el anterior -mutuamente no
        # dominados en total (decreciente) vs cobertura (creciente).
        archivo.considerar((10 - i, i, 0, 0, 0.0, 0.0), f"snap_{i}")
    assert len(archivo.items) <= 2


# --- sección 8/9: ejection chain --------------------------------------------

def test_ejection_chain_mueve_caja_entre_pallets():
    """SKU crítico no cabe en NINGÚN pallet directamente -pero ejectando
    un SKU chico ya colocado (en cualquiera de los 2 pallets) y dejando
    que el backtracking general lo reubique, el crítico sí entra. Caso
    sintético controlado (no depende de datos reales)."""
    # Pallet A: completamente ocupado por RELLENO (120x100).
    relleno_cand = _cand("RELLENO", config.PALLET_LARGO, config.PALLET_ANCHO, 50.0)
    relleno = crear_torre(relleno_cand, x=0, y=0, cantidad=1)
    pallet_a = PalletV5(id="PA", cd="CD", torres=[relleno], altura_final=config.ALTURA_PALLET_VACIO + 50.0)

    # Pallet B: un SKU chico (MOVIBLE) + espacio libre suficiente para el crítico.
    movible_cand = _cand("MOVIBLE", 20, 20, 20.0, cantidad_disponible=1)
    movible = crear_torre(movible_cand, x=0, y=0, cantidad=1)
    pallet_b = PalletV5(id="PB", cd="CD", torres=[movible], altura_final=config.ALTURA_PALLET_VACIO + 20.0)

    critico_cand = _cand("CRITICO", config.PALLET_LARGO, config.PALLET_ANCHO, 20.0, cantidad_disponible=1)
    por_sku = {"RELLENO": [relleno_cand], "MOVIBLE": [movible_cand], "CRITICO": [critico_cand]}
    nivel_por_sku = {"RELLENO": 6, "MOVIBLE": 6, "CRITICO": 6}
    presupuesto = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO

    from src.packing_columnar import _reconstruir_en_construccion

    construcciones = [_reconstruir_en_construccion(pallet_a), _reconstruir_en_construccion(pallet_b)]
    colocados_por_pallet = [{"RELLENO": 1}, {"MOVIBLE": 1}]
    pendientes = {"CRITICO": 1, "RELLENO": 0, "MOVIBLE": 0}

    resultado = _buscar_ejection_chain(
        construcciones, colocados_por_pallet, pendientes, por_sku, capacidad_cama_por_sku={},
        nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={}, presupuesto=presupuesto, n_pallets=2,
        sku_critico="CRITICO", limite_tiempo=None,
    )

    assert resultado is True
    assert pendientes.get("CRITICO", 0) == 0
    for pc in construcciones:
        assert validar_pallet_v5(pc.pallet) == []
