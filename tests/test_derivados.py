from src.derivados import calcular_derivados
from src.validacion import validar_y_limpiar


def test_redondeo_hacia_arriba_de_cajas_fraccionarias(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 3.2}],
        maestro_overrides=[{"sku": 1, "categoria": "Cigarros"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    assert df.iloc[0]["Cajas_Teoricas_Redondeadas"] == 4
    assert round(df.iloc[0]["Cajas_Extra_Redondeo"], 2) == 0.8


def test_fallback_geometrico_cuando_falta_cajas_por_cama(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 0}],
        uma_overrides=[{"sku": 1, "largo": 40, "ancho": 25}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    esperado = max((120 // 40) * (100 // 25), (120 // 25) * (100 // 40))
    assert df.iloc[0]["Cajas_Cama_Efectivo"] == esperado


def test_nivel_categoria_none_para_remate(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Comestibles"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    assert df.iloc[0]["Nivel_Categoria"] is None
    assert bool(df.iloc[0]["Es_Categoria_Remate"]) is True


def test_nivel_categoria_asignado_para_categoria_estable(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = validar_y_limpiar(envios, maestro, uma)
    df = calcular_derivados(df)
    assert df.iloc[0]["Nivel_Categoria"] == 1
