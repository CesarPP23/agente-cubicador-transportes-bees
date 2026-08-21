"""[V5-P1] El flag config.PACKER_VERSION es el único punto de rollback entre
el core V4 (camas) y el core V5 (columnar) -acá se prueba que el dispatch
funciona para cualquier valor del flag, sin asumir cuál es el default."""
import pandas as pd
import pytest

import config
from src.pipeline import ejecutar_core_v4, ejecutar_pipeline


@pytest.fixture(autouse=True)
def _restaurar_packer_version():
    original = config.PACKER_VERSION
    yield
    config.PACKER_VERSION = original


def test_default_es_uno_de_los_soportados():
    """El gate formal (P14) todavía no aprueba V5 solo en el dataset real
    (ver PATCH_LOG.md), así que el default "de producción" sigue siendo
    "V4" -pero el usuario puede dejarlo en "V5"/"AUTO"/"AUTO_CONSOLIDADO"
    localmente a propósito para correr y comparar los motores nuevos
    (instrucción explícita en esta sesión). Este test solo valida que el
    flag es uno de los valores soportados, no cuál está activo en este
    checkout."""
    assert config.PACKER_VERSION in ("V4", "V5", "AUTO", "AUTO_CONSOLIDADO", "SKU_CONSOLIDADO", "SKU_BLOQUE")


def test_flag_v4_da_resultado_identico_a_ejecutar_core_v4(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    config.PACKER_VERSION = "V4"
    directo = ejecutar_core_v4(envios.copy(), maestro.copy(), uma.copy())
    via_dispatch = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())

    pd.testing.assert_frame_equal(directo.plan_picking_df, via_dispatch.plan_picking_df)
    pd.testing.assert_frame_equal(directo.resumen_cd_df, via_dispatch.resumen_cd_df)


def test_flag_v5_corre_sin_romper(dataset_factory):
    """[V5-P1] Todavía no tiene que dar el MISMO resultado que V4 -eso llega
    con P4 en adelante- pero tiene que correr de punta a punta sin excepción."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    config.PACKER_VERSION = "V5"
    resultado = ejecutar_pipeline(envios, maestro, uma)
    assert resultado.pallets  # al menos armó algo, no reventó
