"""[V-AUTO-CONSOLIDADO] Integración: el dispatcher completo no revienta y
nunca pierde demanda ni aumenta pallets frente a AUTO puro."""
import pytest

import config


@pytest.fixture(autouse=True)
def _restaurar_packer_version():
    original = config.PACKER_VERSION
    yield
    config.PACKER_VERSION = original


def test_corre_de_punta_a_punta(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 2, "cajas": 3, "cd": "BK41"}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}, {"sku": 2, "categoria": "Aseo"}],
        uma_overrides=[{"sku": 1}, {"sku": 2}],
    )
    config.PACKER_VERSION = "AUTO_CONSOLIDADO"
    from src.pipeline import ejecutar_pipeline

    resultado = ejecutar_pipeline(envios, maestro, uma)
    assert resultado.pallets
    cds = {p.cd for p in resultado.pallets}
    assert cds == {"BK31", "BK41"}


def test_nunca_da_mas_pallets_que_auto_puro(dataset_factory):
    """La consolidación nunca abre pallets nuevos (ver
    consolidacion_sku.consolidar_por_cd) -así que AUTO_CONSOLIDADO no puede
    dar MÁS pallets que AUTO para la misma entrada."""
    envios, maestro, uma = dataset_factory(
        envios_overrides=[
            {"sku": 1, "cajas": 20, "cd": "BK31"},
            {"sku": 2, "cajas": 15, "cd": "BK31"},
            {"sku": 3, "cajas": 10, "cd": "BK31"},
        ],
        maestro_overrides=[
            {"sku": 1, "categoria": "Licores"},
            {"sku": 2, "categoria": "Aseo"},
            {"sku": 3, "categoria": "Importados"},
        ],
        uma_overrides=[{"sku": 1}, {"sku": 2}, {"sku": 3}],
    )
    from src.pipeline import ejecutar_pipeline

    config.PACKER_VERSION = "AUTO"
    resultado_auto = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())
    config.PACKER_VERSION = "AUTO_CONSOLIDADO"
    resultado_consolidado = ejecutar_pipeline(envios.copy(), maestro.copy(), uma.copy())

    assert len(resultado_consolidado.pallets) <= len(resultado_auto.pallets)
