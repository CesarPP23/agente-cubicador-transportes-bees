from src.apilado_3d import armar_pallets
from src.derivados import calcular_derivados
from src.packing_2d import generar_camas
from src.pallets_homogeneos import armar_pallets_homogeneos
from src.pipeline import _construir_info_sku
from src.validacion import validar_y_limpiar


def test_pallet_homogeneo_se_completa_con_remate_disponible(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[
            {"sku": 1, "cd": "BK31", "cajas": 20},
            {"sku": 2, "cd": "BK31", "cajas": 500},
        ],
        maestro_overrides=[
            {"sku": 1, "categoria": "Licores", "cajas_por_cama": 10, "camas_por_ph": 4, "cajas_por_ph": 20},
            {"sku": 2, "categoria": "Comestibles", "cajas_por_cama": 50, "cajas_por_ph": 99999},
        ],
        uma_overrides=[
            {"sku": 1, "largo": 30, "ancho": 20, "alto": 25},
            {"sku": 2, "largo": 30, "ancho": 20, "alto": 20},
        ],
    )

    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    info_sku = _construir_info_sku(df)

    remanente, pallets_hom = armar_pallets_homogeneos(df)
    assert len(pallets_hom) == 1
    altura_base = pallets_hom[0].altura_final
    assert altura_base < 185

    camas_por_cd = generar_camas(remanente)
    pallets = armar_pallets(camas_por_cd, info_sku, pallets_semilla=pallets_hom)

    pallet_topado = next(p for p in pallets if p.id == pallets_hom[0].id)
    assert pallet_topado.tipo == "Homogéneo + Remate"
    assert pallet_topado.altura_final > altura_base
    assert any(cama.categorias[0] == "Comestibles" for cama in pallet_topado.camas)
