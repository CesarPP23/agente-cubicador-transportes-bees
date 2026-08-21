from src.derivados import calcular_derivados
from src.packing_2d import generar_camas
from src.pallets_homogeneos import armar_pallets_homogeneos
from src.reconciliacion_geometrica import reconciliar
from src.validacion import validar_y_limpiar


def _derivados(envios, maestro, uma):
    df, log = validar_y_limpiar(envios, maestro, uma)
    df, _auditoria = reconciliar(df)
    return calcular_derivados(df), log


def test_densidad_maxima_limita_cajas_por_cama(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 12}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 5, "cajas_por_ph": 999}],
        uma_overrides=[{"sku": 1, "largo": 10, "ancho": 10}],
    )
    df, _ = _derivados(envios, maestro, uma)
    remanente, pallets_hom = armar_pallets_homogeneos(df)
    assert pallets_hom == []

    camas = generar_camas(remanente)["BK31"]
    assert len(camas) == 3
    for cama in camas:
        assert cama.cantidades["1"] <= 5
    assert sum(cama.cantidades["1"] for cama in camas) == 12


def test_clustering_por_altura_no_combina_alturas_dispares(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 2, "cajas": 5}],
        maestro_overrides=[{"sku": 1, "cajas_por_ph": 999}, {"sku": 2, "cajas_por_ph": 999}],
        uma_overrides=[{"sku": 1, "alto": 20}, {"sku": 2, "alto": 30}],
    )
    df, _ = _derivados(envios, maestro, uma)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    skus_por_cama = [set(c.cantidades.keys()) for c in camas]
    assert not any({"1", "2"} <= s for s in skus_por_cama)


def test_clustering_combina_alturas_similares(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[{"sku": 1, "cajas_por_ph": 999}, {"sku": 2, "cajas_por_ph": 999}],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 22, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = _derivados(envios, maestro, uma)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    assert any({"1", "2"} <= set(c.cantidades.keys()) for c in camas)


def test_categorias_no_remate_pueden_compartir_cama_por_dimension(dataset_factory):
    """[Punto 6] Licores y Lácteos (niveles 1 y 2, separación 1 <=
    MAX_SEPARACION_NIVELES) con cajas de altura parecida ahora SÍ pueden
    terminar en la misma cama -antes el agrupamiento era estrictamente por
    categoría y esto era imposible."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[
            {"sku": 1, "categoria": "Licores", "cajas_por_ph": 999},
            {"sku": 2, "categoria": "Lácteos", "cajas_por_ph": 999},
        ],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 21, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = _derivados(envios, maestro, uma)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    assert any({"1", "2"} <= set(c.cantidades.keys()) for c in camas)
    mixta = next(c for c in camas if {"1", "2"} <= set(c.cantidades.keys()))
    assert set(mixta.categorias) == {"Licores", "Lácteos"}
    assert mixta.nivel_efectivo == 2  # el más restrictivo: Lácteos


def test_merch_y_nabs_pueden_compartir_cama_por_dimension(dataset_factory):
    """[V4b / fotos de los 42 pallets reales] Ya no hay aislamiento de NABs
    respecto de los niveles base -confirmado con Omar, la operación real
    mezcla libremente. Con cajas de igual altura, Merch y NABs ahora SÍ
    pueden terminar en la misma cama."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[
            {"sku": 1, "categoria": "Merch", "cajas_por_ph": 999},
            {"sku": 2, "categoria": "NABs", "cajas_por_ph": 999},
        ],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 20, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = _derivados(envios, maestro, uma)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    assert any({"1", "2"} <= set(c.cantidades.keys()) for c in camas)
