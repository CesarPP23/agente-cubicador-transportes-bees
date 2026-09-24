"""[PATCH V6.11] Demand-First Portfolio -tests de la sección 6 del parche.
Fija el orden productivo del multi-start (`demanda` primero) y confirma que
el beam sigue mapeado por NOMBRE de estrategia (no por posición en la
tupla, sección 3) y que el stop temprano de la sección 4/18 -si el primer
reinicio llega a 100%, los siguientes NUNCA se ejecutan- sigue intacto con
el nuevo orden."""
import config
import src.global_rescue as gr
from src.torres import TorreCandidate

PRESUPUESTO = config.ALTURA_MAX_OBSERVADA - config.ALTURA_PALLET_VACIO


def _cand(sku, largo, ancho, alto, cantidad_disponible=10, max_verticales=10):
    return TorreCandidate(sku, "CD", "L×A", largo, ancho, alto, max_verticales, cantidad_disponible, 1.0)


def test_orden_productivo_es_demanda_altura_critica_footprint():
    assert gr.GLOBAL_MULTI_START_ESTRATEGIAS == ("demanda", "altura_critica", "footprint")


def test_beams_siguen_mapeados_por_nombre_no_por_posicion():
    """[sección 3] El beam de cada estrategia no debe depender de su índice
    en la tupla -reordenar la tupla (este mismo parche) no debe requerir
    ningún cambio en `GLOBAL_BEAM_WIDTH_BY_STRATEGY`."""
    assert gr.GLOBAL_BEAM_WIDTH_BY_STRATEGY == {
        "footprint": 32,
        "altura_critica": 64,
        "demanda": 128,
    }
    assert gr._beam_width_para_estrategia("demanda") == 128
    assert gr._beam_width_para_estrategia("altura_critica") == 64
    assert gr._beam_width_para_estrategia("footprint") == 32


def test_stop_temprano_si_demanda_resuelve_100_por_ciento_no_corren_las_otras():
    """[sección 4] Caso trivial que el primer reinicio (ahora `demanda`)
    resuelve al 100% -Global Rescue debe detenerse ahí mismo, sin ejecutar
    `altura_critica` ni `footprint`."""
    por_sku = {
        "A": [_cand("A", 60, 50, 20, cantidad_disponible=2)],
        "B": [_cand("B", 40, 30, 15, cantidad_disponible=3)],
    }
    nivel_por_sku = {"A": 6, "B": 6}
    sin_colocar = {"A": 2, "B": 3}

    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar=sin_colocar, por_sku=por_sku,
        capacidad_cama_por_sku={}, nivel_por_sku=nivel_por_sku, tope_pallet_por_sku={},
        n_pallets=1, cd="V611STOP", presupuesto=PRESUPUESTO,
    )

    assert faltantes == {}
    assert stats["motivo_stop"] == "completo"
    assert len(stats["reinicios"]) == 1
    assert stats["reinicios"][0]["estrategia"] == "demanda"
    assert stats["reinicios"][0]["beam_width"] == 128
