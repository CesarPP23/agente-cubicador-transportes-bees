"""[V3 / sección 8] Demanda a nivel de unidades.

`ceil(Cajas_Teoricas)` por línea puede producir sobre-despacho respecto de la
demanda equivalente real (confirmado con Cigarros: 96% de sus líneas son
fraccionarias, y redondear cada una hacia arriba inflaba la demanda ~3.8x).
Este módulo formaliza -para TODAS las categorías, no solo Cigarros- la
reconciliación en unidades, y deja explícita la política de redondeo por
categoría en vez de aplicar ceil() ciegamente en todos lados.
"""
import numpy as np
import pandas as pd

import config


def normalizar_demanda(df: pd.DataFrame) -> pd.DataFrame:
    """Requiere que `df` ya tenga "Unidades", "Unidades por caja", "Cajas
    Teóricas" y "Categoria_Normalizada" (validacion.validar_y_limpiar ya deja
    las tres primeras; Categoria_Normalizada también, vía V1)."""
    df = df.copy()

    df["Demanda_Unidades_Oficial"] = df["Unidades"]
    df["Unidades_por_Caja"] = df["Unidades por caja"]
    df["Cajas_Completas"] = np.floor(df["Cajas Teóricas"]).astype(int)
    df["Unidades_Fraccionarias"] = (
        df["Demanda_Unidades_Oficial"] - df["Cajas_Completas"] * df["Unidades_por_Caja"]
    )

    # [sección 8.2] Política explícita por categoría: BAT (Cigarros/vapes) se
    # despacha en unidades exactas vía la caja de consolidación (bat.py), el
    # resto sigue redondeando a caja completa -pero ahora el exceso que ESE
    # redondeo produce queda cuantificado en vez de perderse en silencio.
    df["Politica_Redondeo"] = df["Categoria_Normalizada"].apply(
        lambda c: "UNIDADES_EXACTAS" if c in config.CATEGORIAS_BAT else "CAJA_COMPLETA"
    )

    cajas_redondeadas = np.ceil(df["Cajas Teóricas"]).astype(int)
    df["Unidades_Exceso_Redondeo"] = np.where(
        df["Politica_Redondeo"] == "CAJA_COMPLETA",
        (cajas_redondeadas - df["Cajas Teóricas"]) * df["Unidades_por_Caja"],
        0.0,
    )

    return df
