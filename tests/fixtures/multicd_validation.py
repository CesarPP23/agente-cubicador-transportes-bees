"""[PATCH V6.03] Dataset real de validación multi-CD.

Extraído de `Plantilla_Ejemplo_Agente_Cubicador (1) (3).xlsx` (el mismo
archivo real usado para el fixture BK31 de V6.01, versión más reciente
-11 sep-, filtrado a los CDs que traen `Pallets_Objetivo` en la hoja de
planificación real: 5 CDs, BK31 incluido)."""
from pathlib import Path

import pandas as pd

_ARCHIVO = Path(__file__).parent / "multicd_validation.xlsx"


def cargar_dataset() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Devuelve (envios, maestro, uma, pallets_objetivo_por_cd)."""
    envios = pd.read_excel(_ARCHIVO, sheet_name="Envios_Julio")
    maestro = pd.read_excel(_ARCHIVO, sheet_name="Maestro_SKUs")
    uma = pd.read_excel(_ARCHIVO, sheet_name="UMA")
    pobj_df = pd.read_excel(_ARCHIVO, sheet_name="Pallets_Objetivo")
    pallets_objetivo_por_cd = dict(zip(pobj_df["CD"], pobj_df["Pallets_Objetivo"].astype(int)))
    return envios, maestro, uma, pallets_objetivo_por_cd
