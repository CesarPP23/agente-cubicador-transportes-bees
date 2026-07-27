import pandas as pd

import config
from models import Pallet, PalletLinea, ResultadoPipeline
from src import apilado_3d, derivados, exportar, packing_2d, pallets_homogeneos, validacion, validacion_peso


def _construir_info_sku(df: pd.DataFrame) -> dict[str, dict]:
    info: dict[str, dict] = {}
    for _, fila in df.drop_duplicates(subset="SKU").iterrows():
        categoria = fila["Categoria_Normalizada"] if pd.notna(fila["Categoria_Normalizada"]) else fila["Categoría"]
        info[fila["SKU"]] = {
            "descripcion": fila["Descripción"],
            "categoria": categoria,
            "nivel_categoria": fila["Nivel_Categoria"],
            "peso_no_validable": bool(fila["Peso_No_Validable"]),
            "peso_caja": fila["Peso_Caja"] if pd.notna(fila["Peso_Caja"]) else 0.0,
        }
    return info


def _construir_pallets_sin_clasificar(df_no_clasificado: pd.DataFrame) -> list[Pallet]:
    pallets = []
    for cd, grupo in df_no_clasificado.groupby("CD"):
        lineas = [
            PalletLinea(
                sku=fila["SKU"],
                descripcion=fila["Descripción"],
                categoria=fila["Categoría"],
                nivel_categoria=None,
                cajas_demanda_oficial=int(fila["Cajas_Teoricas_Redondeadas"]),
                cajas_extra_consolidacion=0,
                peso_no_validable=bool(fila["Peso_No_Validable"]),
            )
            for _, fila in grupo.iterrows()
        ]
        pallet = Pallet(
            id=f"SIN-ASIGNAR-{cd}",
            cd=cd,
            tipo="Requiere Revisión",
            estado=config.ESTADO_CATEGORIA_NO_CLASIFICADA,
        )
        pallet.lineas = lineas
        pallets.append(pallet)
    return pallets


def ejecutar_pipeline(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
    df_validado, log_df = validacion.validar_y_limpiar(envios, maestro, uma)
    df_derivado = derivados.calcular_derivados(df_validado)

    info_sku = _construir_info_sku(df_derivado)

    df_clasificado = df_derivado[df_derivado["Categoria_Normalizada"].notna()].copy()
    df_no_clasificado = df_derivado[df_derivado["Categoria_Normalizada"].isna()].copy()

    remanente_df, pallets_hom = pallets_homogeneos.armar_pallets_homogeneos(df_clasificado)
    camas_por_cd = packing_2d.generar_camas(remanente_df)
    pallets_apilado = apilado_3d.armar_pallets(camas_por_cd, info_sku, pallets_semilla=pallets_hom)
    pallets_sin_clasificar = _construir_pallets_sin_clasificar(df_no_clasificado)

    todos_pallets = pallets_apilado + pallets_sin_clasificar
    validacion_peso.validar_pesos(todos_pallets, info_sku)

    plan_picking_df = exportar.construir_plan_picking_df(todos_pallets)
    resumen_cd_df = exportar.construir_resumen_cd_df(todos_pallets)

    return ResultadoPipeline(
        plan_picking_df=plan_picking_df,
        log_validacion_df=log_df,
        resumen_cd_df=resumen_cd_df,
        pallets=todos_pallets,
        info_sku=info_sku,
    )


def ejecutar_desde_archivo(ruta_o_buffer) -> ResultadoPipeline:
    envios, maestro, uma = validacion.cargar_hojas(ruta_o_buffer)
    return ejecutar_pipeline(envios, maestro, uma)
