"""[PATCH V6.10] Beam por Estrategia -tests de la sección 4 del parche.
`_beam_width_para_estrategia` es la ÚNICA fuente de verdad para el ancho
de haz de cada reinicio del multi-start; estos tests no dependen de
ningún harness ni de correr el pipeline completo."""
import src.global_rescue as gr


def test_beam_footprint_32():
    assert gr._beam_width_para_estrategia("footprint") == 32


def test_beam_altura_critica_64():
    assert gr._beam_width_para_estrategia("altura_critica") == 64


def test_beam_demanda_128():
    assert gr._beam_width_para_estrategia("demanda") == 128


def test_beam_estrategia_desconocida_usa_fallback_documentado():
    """Una estrategia no listada en `GLOBAL_BEAM_WIDTH_BY_STRATEGY` no
    debe lanzar `KeyError` -cae al fallback seguro documentado
    (`GLOBAL_BEAM_WIDTH_FALLBACK`)."""
    assert gr._beam_width_para_estrategia("estrategia_inexistente") == gr.GLOBAL_BEAM_WIDTH_FALLBACK


def test_beam_mapa_cubre_exactamente_las_estrategias_del_multi_start():
    """Única fuente de verdad -sin esto, una estrategia nueva agregada a
    `GLOBAL_MULTI_START_ESTRATEGIAS` sin actualizar el mapa caería
    silenciosamente al fallback en vez de fallar visiblemente en un test."""
    assert set(gr.GLOBAL_MULTI_START_ESTRATEGIAS) == set(gr.GLOBAL_BEAM_WIDTH_BY_STRATEGY.keys())


def test_beam_width_stats_reporta_el_mapa_completo():
    """`global_rescue()` debe reportar el mapa completo en stats -ya no
    tiene sentido un único `beam_width` global cuando cada reinicio puede
    usar uno distinto (ver `stats["reinicios"]`, que sigue reportando el
    beam_width EFECTIVO de cada intento)."""
    pallets, faltantes, stats = gr.global_rescue(
        pallets=[], sin_colocar={}, por_sku={}, capacidad_cama_por_sku={}, nivel_por_sku={},
        tope_pallet_por_sku={}, n_pallets=1, cd="TESTBEAM", presupuesto=100.0,
    )
    assert stats["beam_width_por_estrategia"] == gr.GLOBAL_BEAM_WIDTH_BY_STRATEGY
