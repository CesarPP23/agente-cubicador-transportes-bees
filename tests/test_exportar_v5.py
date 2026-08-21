"""[V5-P13] Hojas propias del core columnar: Torres, Pallets_3D_Data,
Estabilidad_V5. Deben reflejar exactamente lo que armó el packer -ninguna
posición exportada de más ni de menos ("toda posición exportada debe poder
verse")."""
import openpyxl
import pytest

import config
from src.exportar import (
    construir_estabilidad_df,
    construir_pallets_3d_data_df,
    construir_torres_df,
    exportar_workbook,
)
from src.pipeline import ejecutar_pipeline


@pytest.fixture(autouse=True)
def _restaurar_packer_version():
    original = config.PACKER_VERSION
    yield
    config.PACKER_VERSION = original


@pytest.fixture
def resultado_v5(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 2, "cajas": 3}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}, {"sku": 2, "categoria": "Aseo"}],
        uma_overrides=[{"sku": 1}, {"sku": 2}],
    )
    config.PACKER_VERSION = "V5"
    return ejecutar_pipeline(envios, maestro, uma)


def test_torres_df_tiene_una_fila_por_torre(resultado_v5):
    df = construir_torres_df(resultado_v5.pallets_v5)
    total_torres = sum(len(p.torres) for p in resultado_v5.pallets_v5)
    assert len(df) == total_torres
    assert {"X", "Y", "Orientacion", "Fuente_Geometria"}.issubset(df.columns)


def test_pallets_3d_data_tiene_una_fila_por_caja_fisica(resultado_v5):
    df = construir_pallets_3d_data_df(resultado_v5.pallets_v5)
    total_cajas = sum(t.cantidad for p in resultado_v5.pallets_v5 for t in p.torres)
    assert len(df) == total_cajas
    assert {"X", "Y", "Z"}.issubset(df.columns)


def test_estabilidad_df_tiene_una_fila_por_pallet_con_metadata(resultado_v5):
    df = construir_estabilidad_df(resultado_v5.pallets_v5)
    con_metadata = sum(1 for p in resultado_v5.pallets_v5 if p.metadata.get("estabilidad") is not None)
    assert len(df) == con_metadata
    assert con_metadata == len(resultado_v5.pallets_v5)  # P11 la calcula para todos


def test_exportar_workbook_v5_incluye_las_3_hojas_nuevas(resultado_v5):
    buffer = exportar_workbook(resultado_v5)
    wb = openpyxl.load_workbook(buffer)
    assert {"Torres", "Pallets_3D_Data", "Estabilidad_V5"}.issubset(set(wb.sheetnames))


def test_exportar_workbook_v4_no_agrega_hojas_v5(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    config.PACKER_VERSION = "V4"
    resultado = ejecutar_pipeline(envios, maestro, uma)
    buffer = exportar_workbook(resultado)
    wb = openpyxl.load_workbook(buffer)
    assert not {"Torres", "Pallets_3D_Data", "Estabilidad_V5"} & set(wb.sheetnames)
