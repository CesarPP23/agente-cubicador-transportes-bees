import numpy as np
import pandas as pd

import config
from src import reconciliacion_geometrica


def calcular_peso_caja(peso_bruto_por_unidad: pd.Series, unidades_por_caja: pd.Series) -> pd.Series:
    """Peso de la caja de un SKU, a partir de las columnas crudas de UMA/Maestro.

    Compartida entre `validacion.py` (V6) y este módulo para que los dos usen
    exactamente el mismo número — antes `validacion.py` calculaba su propia
    versión con la fórmula vieja (peso x unidades) sin mirar el flag de abajo,
    y los dos números divergían en silencio.

    La columna "Peso bruto por unidad" de UMA trae, en la práctica, el peso de
    la CAJA del SKU, no el de la unidad suelta (ver config.PESO_UMA_ES_POR_UNIDAD).
    Multiplicarla por "Unidades por caja" infla el peso hasta 1.000x en SKUs con
    packs grandes (Cigarros de 1.000 u/caja daban 16.000 kg por caja), lo que
    hacía que el tope de peso del Paso 4 rechazara casi toda combinación y cada
    cama terminara en su propio pallet.
    """
    if config.PESO_UMA_ES_POR_UNIDAD:
        return peso_bruto_por_unidad * unidades_por_caja
    return peso_bruto_por_unidad


def calcular_derivados(df: pd.DataFrame) -> pd.DataFrame:
    """Asume que `df` ya pasó por `reconciliacion_geometrica.reconciliar`
    (columnas Largo_Efectivo/Ancho_Efectivo/Alto_Efectivo/Fuente_Geometria ya
    presentes) -ver pipeline.py, que corre la reconciliación antes que esto."""
    df = df.copy()

    df["Peso_Caja"] = calcular_peso_caja(df["Peso bruto por unidad"], df["Unidades por caja"])

    df["Cajas_Teoricas_Redondeadas"] = np.ceil(df["Cajas Teóricas"]).astype(int)
    df["Cajas_Extra_Redondeo"] = df["Cajas_Teoricas_Redondeadas"] - df["Cajas Teóricas"]

    # [V3 / sección 6] Cajas_Cama_Efectivo YA NO es min(Maestro, geometría)
    # -esa regla ("la geometría gana por ser más conservadora") es justo la
    # que la reconciliación reemplaza. Ahora: el Maestro manda si es válido
    # (ya reconciliado contra UMA por reconciliacion_geometrica.reconciliar,
    # sección 5); si no hay "Cajas por cama" confiable (V7 ya lo dejó NA),
    # cae a la capacidad geométrica de la geometría EFECTIVA (reconciliada,
    # no la UMA cruda -si el Maestro no aplica para este SKU, al menos se
    # usa la mejor geometría disponible).
    #
    # [V4 / P3] Se usa "Cajas_Cama_Maestro_Reconciliado", NO la columna cruda
    # del Maestro: reconciliar_sku ya degradó ahí los casos geométricamente
    # imposibles (ej. SKU 22183: declara 84 cajas/cama, entran 15 con
    # sobresaliente) al techo real -leer la columna cruda saltearía ese guard
    # y volvería a planificar camas que no se pueden armar en el piso.
    cajas_maestro = pd.to_numeric(
        df.get("Cajas_Cama_Maestro_Reconciliado", df.get("Cajas por cama")), errors="coerce"
    )
    geometrica_efectiva = df.apply(
        lambda r: reconciliacion_geometrica.capacidad_xy_max(r["Largo_Efectivo"], r["Ancho_Efectivo"])[0]
        if pd.notna(r["Largo_Efectivo"]) and pd.notna(r["Ancho_Efectivo"])
        else 0,
        axis=1,
    )
    df["Cajas_Cama_Efectivo"] = (
        cajas_maestro.where(cajas_maestro.notna() & (cajas_maestro > 0), geometrica_efectiva).astype(int)
    )

    # El remate (Comestibles/Cigarros) ahora tiene nivel 7 en vez de None, para
    # poder comparar con el resto cuando una cama mezcla categorías.
    niveles = [config.nivel_de_categoria(c) for c in df["Categoria_Normalizada"]]
    df["Nivel_Categoria"] = pd.Series(niveles, index=df.index, dtype=object)

    # [fix] SKUs frágiles identificados por texto en la Descripción (no por
    # Categoría del Maestro -el SKU puede compartir Categoría con productos
    # que sí soportan peso encima): se fuerza su nivel al de remate
    # (NIVEL_REMATE, el más alto), así el armado por camas nunca coloca
    # nada arriba -mismo mecanismo que ya usa Comestibles/Cigarros, solo que
    # activado por nombre de producto en vez de por Categoría entera.
    # Confirmado con el usuario: "Four Loko" es sensible a peso, se rompe.
    es_fragil_por_nombre = df["Descripción"].astype(str).str.contains("four loko", case=False, na=False)
    df.loc[es_fragil_por_nombre, "Nivel_Categoria"] = config.NIVEL_REMATE

    df["Es_Categoria_Remate"] = df["Categoria_Normalizada"].isin(config.CATEGORIAS_REMATE) | es_fragil_por_nombre

    return df
