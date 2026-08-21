"""[SKU_CONSOLIDADO] Escenario de referencia: un único pase, sin
multi-start, sin comparación contra V4/V5 -solo prioriza no repartir un
SKU en más pallets de los necesarios dentro de un CD."""
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
    config.PACKER_VERSION = "SKU_CONSOLIDADO"
    from src.pipeline import ejecutar_pipeline

    resultado = ejecutar_pipeline(envios, maestro, uma)
    assert resultado.pallets
    cds = {p.cd for p in resultado.pallets}
    assert cds == {"BK31", "BK41"}


def test_no_pierde_demanda(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 37}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores", "cajas_por_ph": 10}],
        uma_overrides=[{"sku": 1}],
    )
    config.PACKER_VERSION = "SKU_CONSOLIDADO"
    from src.pipeline import ejecutar_pipeline

    resultado = ejecutar_pipeline(envios, maestro, uma)
    total = resultado.plan_picking_df["Cajas_Totales_Pallet"].sum()
    assert total == 37


def test_pallets_homogeneos_completos_quedan_puros():
    """Demanda de 37 cajas con capacidad 10 por PH -tienen que salir 3
    pallets 100% homogéneos (30 cajas) y el resto (7) va al remanente."""
    from src.pallets_homogeneos import armar_pallets_homogeneos
    import pandas as pd

    df = pd.DataFrame(
        [{"SKU": "1", "CD": "BK31", "Cajas_Teoricas_Redondeadas": 37, "Cajas por PH": 10, "Camas por PH": 1, "Alto_Efectivo": 20.0, "Peso_Caja": 1.0, "Categoria_Normalizada": "Licores", "Nivel_Categoria": 1, "Descripción": "x", "Peso_No_Validable": False}]
    )
    remanente, pallets = armar_pallets_homogeneos(df)
    assert len(pallets) == 3
    assert all(p.lineas[0].cajas_demanda_oficial == 10 for p in pallets)
    assert remanente["Cajas_Remanente"].iloc[0] == 7
