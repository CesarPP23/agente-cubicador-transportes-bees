from src.derivados import calcular_derivados
from src.packing_2d import generar_camas
from src.pallets_homogeneos import armar_pallets_homogeneos
from src.validacion import validar_y_limpiar


def test_densidad_maxima_limita_cajas_por_cama(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 12}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 5, "cajas_por_ph": 999}],
        uma_overrides=[{"sku": 1, "largo": 10, "ancho": 10}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
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
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
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
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    assert any({"1", "2"} <= set(c.cantidades.keys()) for c in camas)


def test_categorias_distintas_nunca_comparten_cama(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 2}, {"sku": 2, "cajas": 2}],
        maestro_overrides=[
            {"sku": 1, "categoria": "Comestibles", "cajas_por_ph": 999},
            {"sku": 2, "categoria": "Cigarros", "cajas_por_ph": 999},
        ],
        uma_overrides=[
            {"sku": 1, "alto": 20, "largo": 20, "ancho": 20},
            {"sku": 2, "alto": 20, "largo": 20, "ancho": 20},
        ],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    remanente, _ = armar_pallets_homogeneos(df)

    camas = generar_camas(remanente)["BK31"]
    for cama in camas:
        assert len(cama.categorias) == 1
