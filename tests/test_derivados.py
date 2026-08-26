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


def test_subcategoria_rtd_se_fuerza_a_nivel_remate_aunque_sea_licores(dataset_factory):
    """[fix] Four Loko es sensible al peso -confirmado con el usuario, "se
    puede romper" si le ponen algo encima- y la misma regla aplica a TODA
    la subcategoría "RTD"/"Energizante" del Maestro (Four Loko pertenece a
    esa subcategoría, no es el único SKU frágil ahí). Se identifica por la
    columna `Subcategoría` del Maestro, no por texto en la Descripción -así
    no depende de que el SKU se llame literalmente "Four Loko"."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "descripcion": "Four Loko Purple 473ml 6x1"}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores", "subcategoria": "RTD"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Nivel_Categoria"] == config.NIVEL_REMATE
    assert bool(df.iloc[0]["Es_Categoria_Remate"]) is True


def test_subcategoria_energizante_tambien_se_fuerza_a_nivel_remate(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "descripcion": "Red Bull 250ml 24x1"}],
        maestro_overrides=[{"sku": 1, "categoria": "NABs", "subcategoria": "Energizante"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Nivel_Categoria"] == config.NIVEL_REMATE


def test_subcategoria_detecta_sin_importar_mayusculas_ni_espacios(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "descripcion": "Four Loko Watermelon 473ml"}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores", "subcategoria": "  rtd  "}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Nivel_Categoria"] == config.NIVEL_REMATE


def test_four_loko_sin_subcategoria_marcada_ya_no_se_detecta_por_nombre(dataset_factory):
    """[cambio de diseño explícito] Se reemplazó el match por texto en la
    Descripción por la columna `Subcategoría` del Maestro -si un SKU se
    llama "Four Loko" pero el Maestro no le marcó la subcategoría, ya NO
    se fuerza a remate. La fuente de verdad ahora es el Maestro, no el
    nombre del producto."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "descripcion": "Four Loko Purple 473ml 6x1"}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Nivel_Categoria"] == 1


def test_otro_licor_no_se_marca_como_remate(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "descripcion": "Barcelo Anejo 750ml 1x1"}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    df, _ = _derivados(envios, maestro, uma)
    assert df.iloc[0]["Nivel_Categoria"] == 1
    assert bool(df.iloc[0]["Es_Categoria_Remate"]) is False
