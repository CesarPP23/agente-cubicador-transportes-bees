import math

import numpy as np
import pandas as pd

import config


def _capacidad_geometrica(largo: float, ancho: float) -> int:
    orientacion_a = math.floor(config.PALLET_LARGO / largo) * math.floor(config.PALLET_ANCHO / ancho)
    orientacion_b = math.floor(config.PALLET_LARGO / ancho) * math.floor(config.PALLET_ANCHO / largo)
    return max(orientacion_a, orientacion_b)


def calcular_derivados(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["Peso_Caja"] = df["Peso bruto por unidad"] * df["Unidades por caja"]
    df["Cajas_Teoricas_Redondeadas"] = np.ceil(df["Cajas Teóricas"]).astype(int)
    df["Cajas_Extra_Redondeo"] = df["Cajas_Teoricas_Redondeadas"] - df["Cajas Teóricas"]

    df["Cajas_Cama_Efectivo"] = df.apply(
        lambda r: int(r["Cajas por cama"])
        if pd.notna(r["Cajas por cama"])
        else _capacidad_geometrica(r["Largo de caja"], r["Ancho de caja"]),
        axis=1,
    )

    niveles = [
        config.ORDEN_CATEGORIAS.index(c) + 1 if c in config.ORDEN_CATEGORIAS else None
        for c in df["Categoria_Normalizada"]
    ]
    df["Nivel_Categoria"] = pd.Series(niveles, index=df.index, dtype=object)
    df["Es_Categoria_Remate"] = df["Categoria_Normalizada"].isin(config.CATEGORIAS_REMATE)

    return df
