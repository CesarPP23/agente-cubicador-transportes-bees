"""Hojas propias del core columnar: Torres, Pallets_3D_Data, Estabilidad_V5.
Deben reflejar exactamente lo que armó el packer -ninguna posición
exportada de más ni de menos ("toda posición exportada debe poder ver")."""
import openpyxl

from src.exportar import (
    construir_estabilidad_df,
    construir_pallets_3d_data_df,
    construir_torres_df,
    exportar_workbook,
)
from src.pipeline import ejecutar_pipeline


def _resultado(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cajas": 5}, {"sku": 2, "cajas": 3}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}, {"sku": 2, "categoria": "Aseo"}],
        uma_overrides=[{"sku": 1}, {"sku": 2}],
    )
    return ejecutar_pipeline(envios, maestro, uma)


def test_torres_df_tiene_una_fila_por_torre(dataset_factory):
    resultado = _resultado(dataset_factory)
    df = construir_torres_df(resultado.pallets_v5)
    total_torres = sum(len(p.torres) for p in resultado.pallets_v5)
    assert len(df) == total_torres
    assert {"X", "Y", "Orientacion", "Fuente_Geometria"}.issubset(df.columns)


def test_pallets_3d_data_tiene_una_fila_por_caja_fisica(dataset_factory):
    resultado = _resultado(dataset_factory)
    df = construir_pallets_3d_data_df(resultado.pallets_v5)
    total_cajas = sum(t.cantidad for p in resultado.pallets_v5 for t in p.torres)
    assert len(df) == total_cajas
    assert {"X", "Y", "Z"}.issubset(df.columns)


def test_estabilidad_df_tiene_una_fila_por_pallet_con_metadata(dataset_factory):
    resultado = _resultado(dataset_factory)
    df = construir_estabilidad_df(resultado.pallets_v5)
    con_metadata = sum(1 for p in resultado.pallets_v5 if p.metadata.get("estabilidad") is not None)
    assert len(df) == con_metadata
    assert con_metadata == len(resultado.pallets_v5)


def test_exportar_workbook_incluye_las_3_hojas_de_torres(dataset_factory):
    resultado = _resultado(dataset_factory)
    buffer = exportar_workbook(resultado)
    wb = openpyxl.load_workbook(buffer)
    assert {"Torres", "Pallets_3D_Data", "Estabilidad_V5"}.issubset(set(wb.sheetnames))
