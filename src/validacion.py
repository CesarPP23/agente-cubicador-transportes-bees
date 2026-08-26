import pandas as pd

import config
from models import LogEntry
from src.derivados import calcular_peso_caja


def cargar_hojas(ruta_o_buffer):
    xl = pd.ExcelFile(ruta_o_buffer)
    envios = pd.read_excel(xl, "Envios_Julio")
    maestro = pd.read_excel(xl, "Maestro_SKUs")
    uma = pd.read_excel(xl, "UMA")
    return envios, maestro, uma


def _normalizar_sku(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.strip()


def _cabe_en_pallet(largo, ancho) -> bool:
    if pd.isna(largo) or pd.isna(ancho):
        return False
    orientacion_a = largo <= config.PALLET_LARGO and ancho <= config.PALLET_ANCHO
    orientacion_b = ancho <= config.PALLET_LARGO and largo <= config.PALLET_ANCHO
    return orientacion_a or orientacion_b


def validar_y_limpiar(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame):
    log: list[LogEntry] = []

    envios = envios.copy()
    maestro = maestro.copy()
    uma = uma.copy()

    envios["SKU"] = _normalizar_sku(envios["SKU"])
    maestro["SKU"] = _normalizar_sku(maestro["SKU"])
    uma["SKU"] = _normalizar_sku(uma["SKU"])

    # V9 — duplicados CD+SKU: sumar y loguear
    dup_mask = envios.duplicated(subset=["CD", "SKU"], keep=False)
    if dup_mask.any():
        for (cd, sku), grupo in envios[dup_mask].groupby(["CD", "SKU"]):
            log.append(LogEntry(cd, sku, "V9", f"Duplicado CD+SKU sumado ({len(grupo)} filas)"))
    envios = envios.groupby(["CD", "SKU"], as_index=False).agg(
        {"Descripción": "first", "Cajas Teóricas": "sum", "Unidades": "sum"}
    )

    # V8 — Cajas Teóricas > 0
    invalidas = envios["Cajas Teóricas"] <= 0
    for _, fila in envios[invalidas].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V8", "Excluida: Cajas Teóricas <= 0"))
    envios = envios[~invalidas]

    # V2 — SKU debe existir en Maestro y en UMA
    en_maestro = set(maestro["SKU"])
    en_uma = set(uma["SKU"])
    sin_maestro = ~envios["SKU"].isin(en_maestro)
    for _, fila in envios[sin_maestro].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V2", "Excluida: SKU sin Maestro"))
    sin_uma = envios["SKU"].isin(en_maestro) & ~envios["SKU"].isin(en_uma)
    for _, fila in envios[sin_uma].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V2", "Excluida: SKU sin UMA"))
    envios = envios[envios["SKU"].isin(en_maestro) & envios["SKU"].isin(en_uma)]

    df = envios.merge(maestro, on="SKU", how="left").merge(uma, on="SKU", how="left")

    # V3 — Cajas por PH / Camas por PH dentro de rango razonable
    for columna in ["Cajas por PH", "Camas por PH"]:
        no_confiable = df[columna] >= config.UMBRAL_DATO_NO_CONFIABLE
        for _, fila in df[no_confiable].iterrows():
            log.append(
                LogEntry(
                    fila["CD"], fila["SKU"], "V3",
                    f"{columna} no confiable (>= {config.UMBRAL_DATO_NO_CONFIABLE}), se usará fallback",
                )
            )
        df.loc[no_confiable, columna] = pd.NA

    # V7 — Cajas por cama no nulo ni 0
    invalido_cama = df["Cajas por cama"].isna() | (df["Cajas por cama"] == 0)
    for _, fila in df[invalido_cama].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V7", "Cajas por cama nulo o 0, se usará fallback geométrico"))
    df.loc[invalido_cama, "Cajas por cama"] = pd.NA

    # V4 — dimensiones deben permitir al menos una orientación dentro del pallet
    dim_invalida = ~df.apply(lambda r: _cabe_en_pallet(r["Largo de caja"], r["Ancho de caja"]), axis=1)
    for _, fila in df[dim_invalida].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V4", "Excluida: dimensión de caja imposible para el pallet"))

    # V5 — alto de caja dentro del máximo permitido
    alto_invalido = df["Alto de caja"].isna() | (df["Alto de caja"] > config.ALTURA_PRODUCTO_MAX)
    for _, fila in df[alto_invalido].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V5", "Excluida: altura de caja excede el máximo permitido"))

    df = df[~(dim_invalida | alto_invalido)].copy()

    # V6 — peso por caja dentro de un rango sano
    peso_caja = calcular_peso_caja(df["Peso bruto por unidad"], df["Unidades por caja"])
    fuera_rango = peso_caja.isna() | (peso_caja < config.PESO_CAJA_MIN) | (peso_caja > config.PESO_CAJA_MAX)
    df["Peso_No_Validable"] = fuera_rango
    for _, fila in df[fuera_rango].iterrows():
        log.append(LogEntry(fila["CD"], fila["SKU"], "V6", "Peso por caja fuera de rango sano, marcado PESO NO VALIDABLE"))

    # V1 — normalizar categoría; loguear las que no clasifican dentro del orden conocido
    df["Categoria_Normalizada"] = df["Categoría"].map(config.normalizar_categoria)
    no_clasificada = df["Categoria_Normalizada"].isna()
    for _, fila in df[no_clasificada].iterrows():
        log.append(
            LogEntry(
                fila["CD"], fila["SKU"], "9.1",
                f"Categoría '{fila['Categoría']}' no clasificada, excluida del apilado automático",
            )
        )

    log_df = pd.DataFrame([vars(e) for e in log], columns=["cd", "sku", "regla", "accion"])
    return df.reset_index(drop=True), log_df
