import pandas as pd

from src.validacion import validar_y_limpiar


def test_normaliza_casing_de_categoria(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Nabs"}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert df.iloc[0]["Categoria_Normalizada"] == "NABs"


def test_categoria_no_clasificada_se_loguea_pero_no_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Otros"}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["Categoria_Normalizada"])
    assert (log["regla"] == "9.1").any()


def test_sku_sin_maestro_se_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 2}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V2").any()


def test_sentinel_cajas_por_ph_se_marca_no_confiable(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 100}],
        maestro_overrides=[{"sku": 1, "cajas_por_ph": 999999999}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert pd.isna(df.iloc[0]["Cajas por PH"])
    assert (log["regla"] == "V3").any()


def test_dimension_imposible_se_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1, "largo": 452, "ancho": 452}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V4").any()


def test_altura_excesiva_se_excluye(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1, "alto": 575}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V5").any()


def test_cajas_por_cama_cero_se_trata_como_nulo(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 0}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert pd.isna(df.iloc[0]["Cajas por cama"])
    assert (log["regla"] == "V7").any()


def test_peso_fuera_de_rango_se_marca_no_validable_sin_excluir(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "unidades_por_caja": 1000}],
        uma_overrides=[{"sku": 1, "peso_unidad": 1.0}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 1
    assert bool(df.iloc[0]["Peso_No_Validable"]) is True
    assert (log["regla"] == "V6").any()


def test_cajas_teoricas_no_positivas_se_excluyen(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 0}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 0
    assert (log["regla"] == "V8").any()


def test_duplicados_cd_sku_se_suman(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 1, "cajas": 7}],
        maestro_overrides=[{"sku": 1}],
        uma_overrides=[{"sku": 1}],
    )
    df, log = validar_y_limpiar(envios, maestro, uma)
    assert len(df) == 1
    assert df.iloc[0]["Cajas Teóricas"] == 12
    assert (log["regla"] == "V9").any()
