import config
from src.derivados import calcular_derivados
from src.reconciliacion_geometrica import reconciliar
from src.validacion import validar_y_limpiar


def _derivados(envios, maestro, uma):
    """[V3] calcular_derivados asume que el df ya pasó por reconciliar (trae
    Largo_Efectivo/Ancho_Efectivo/Alto_Efectivo) -mismo orden que pipeline.py."""
    df, log = validar_y_limpiar(envios, maestro, uma)
    df, _auditoria = reconciliar(df)
    return calcular_derivados(df), log


def test_redondeo_hacia_arriba_de_cajas_fraccionarias(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 3.2}],
        maestro_overrides=[{"sku": 1, "categoria": "Cigarros"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Cajas_Teoricas_Redondeadas"] == 4
    assert round(df.iloc[0]["Cajas_Extra_Redondeo"], 2) == 0.8


def test_fallback_geometrico_cuando_falta_cajas_por_cama(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "cajas_por_cama": 0}],
        uma_overrides=[{"sku": 1, "largo": 40, "ancho": 25}],
    )
    df, _ = _derivados(envios, maestro, uma)
    esperado = max((120 // 40) * (100 // 25), (120 // 25) * (100 // 40))
    assert df.iloc[0]["Cajas_Cama_Efectivo"] == esperado


def test_nivel_categoria_remate_es_el_nivel_mas_alto(dataset_factory):
    """[Sección 1.3 / v2] El remate ya no queda en None: config.nivel_de_categoria
    le da NIVEL_REMATE (7), el nivel más alto de la escala, para poder compararlo
    con el resto cuando una cama mezcla categorías (punto 6)."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Comestibles"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Nivel_Categoria"] == config.NIVEL_REMATE
    assert bool(df.iloc[0]["Es_Categoria_Remate"]) is True


def test_nivel_categoria_asignado_para_categoria_estable(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Nivel_Categoria"] == 1
