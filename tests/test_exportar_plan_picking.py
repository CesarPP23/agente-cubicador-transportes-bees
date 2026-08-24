"""[feedback picking] Columnas nuevas pedidas por operación: N° de
parihuela secuencial por CD, Cajas por PH / Unidades por caja de
referencia, y nombre de CD cuando el input lo trae."""
import pandas as pd

from models import Pallet, PalletLinea
from src.exportar import construir_plan_picking_df
from src.pipeline import ejecutar_pipeline


def _pallet(id_, cd, skus):
    p = Pallet(id=id_, cd=cd, tipo="Columnar", altura_final=200.0, peso_estimado=100.0)
    p.lineas = [
        PalletLinea(sku=s, descripcion=f"Producto {s}", categoria="Licores", nivel_categoria=1,
                    cajas_demanda_oficial=5, cajas_extra_consolidacion=0)
        for s in skus
    ]
    return p


def test_n_parihuela_es_secuencial_por_cd_no_global():
    pallets = [
        _pallet("PV5-BK31-001", "BK31", ["1"]),
        _pallet("PV5-BK31-002", "BK31", ["2"]),
        _pallet("PV5-BK41-001", "BK41", ["3"]),
    ]
    df = construir_plan_picking_df(pallets)
    n_por_pallet = df.drop_duplicates("ID_Pallet").set_index("ID_Pallet")["N_Parihuela"].to_dict()
    assert n_por_pallet == {"PV5-BK31-001": 1, "PV5-BK31-002": 2, "PV5-BK41-001": 1}


def test_cajas_por_ph_y_unidades_por_caja_de_info_sku():
    pallets = [_pallet("PV5-BK31-001", "BK31", ["1"])]
    info_sku = {"1": {"unidades_por_caja": 12, "cajas_por_ph": 120}}
    df = construir_plan_picking_df(pallets, info_sku)
    fila = df.iloc[0]
    assert fila["Unidades_Por_Caja"] == 12
    assert fila["Cajas_Por_PH"] == 120


def test_nombre_cd_ausente_queda_vacio():
    pallets = [_pallet("PV5-BK31-001", "BK31", ["1"])]
    df = construir_plan_picking_df(pallets)
    assert df.iloc[0]["Nombre_CD"] is None


def test_nombre_cd_presente_se_usa():
    pallets = [_pallet("PV5-BK31-001", "BK31", ["1"])]
    df = construir_plan_picking_df(pallets, nombres_cd={"BK31": "CD Cañete"})
    assert df.iloc[0]["Nombre_CD"] == "CD Cañete"


def test_nombre_cd_end_to_end_desde_envios_julio(dataset_factory):
    envios, maestro, uma = dataset_factory(
        envios_overrides=[{"sku": 1, "cd": "BK31"}],
        maestro_overrides=[{"sku": 1, "categoria": "Licores"}],
        uma_overrides=[{"sku": 1}],
    )
    envios["Nombre CD"] = "CD Cañete"
    resultado = ejecutar_pipeline(envios, maestro, uma)
    assert (resultado.plan_picking_df["Nombre_CD"] == "CD Cañete").all()
