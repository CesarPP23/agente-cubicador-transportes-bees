"""[SKU_BLOQUE] Pipeline para la lógica de bloques (ver
src/packing_bloques.py -instrucción explícita del usuario sobre cómo tiene
que priorizar el armado: cada SKU es un bloque indivisible mientras sea
posible, se agrupan bloques enteros para llegar a la altura óptima, y solo
se parte un bloque como último recurso).

Reutiliza VAL/DEM/GEO/DER/SPLIT/PESO/EXP tal cual el resto de los motores
-esa infraestructura no depende de la estrategia de armado."""
import pandas as pd

import config
from models import Pallet, ResultadoPipeline
from src import (
    bat,
    benchmark,
    demanda,
    derivados,
    estabilidad,
    exportar,
    reconciliacion_geometrica,
    soporte,
    validacion,
    validacion_peso,
)
from src.packing_bloques import armar_pallets_bloques
from src.pipeline import (
    _construir_info_sku,
    _construir_pallets_geometria_insuficiente,
    _construir_pallets_sin_clasificar,
)
from src.pipeline_v5 import _palletv5_a_pallet


def ejecutar_core_sku_bloque(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
    df_validado, log_df = validacion.validar_y_limpiar(envios, maestro, uma)
    df_demanda = demanda.normalizar_demanda(df_validado)
    df_geo, auditoria_geometrica_df = reconciliacion_geometrica.reconciliar(df_demanda)
    df_derivado = derivados.calcular_derivados(df_geo)
    info_sku = _construir_info_sku(df_derivado)

    df_no_bat, df_bat = bat.separar_bat(df_derivado)
    df_clasificado = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & ~df_no_bat["Requiere_Revision_Geometria"]
    ].copy()
    df_no_clasificado = df_no_bat[df_no_bat["Categoria_Normalizada"].isna()].copy()
    df_geometria_insuficiente = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & df_no_bat["Requiere_Revision_Geometria"]
    ].copy()

    df_clasificado = df_clasificado.copy()
    df_clasificado["Cajas_Remanente"] = df_clasificado["Cajas_Teoricas_Redondeadas"].astype(int)

    # BAT entra como pseudo-fila más -mismo mecanismo que V5-BAT-integrado,
    # así compite por espacio en vez de perderse en un pase aparte.
    cajas_bat_por_cd = bat.consolidar_bat_por_cd(df_bat)
    df_bat_pseudo = bat.construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku)
    df_armado = pd.concat([df_clasificado, df_bat_pseudo], ignore_index=True, sort=False)

    pallets_v5: list = []
    contador = [0]
    cds_procesados: set[str] = set()
    for cd, grupo in df_armado.groupby("CD"):
        cds_procesados.add(cd)
        pallets_cd = armar_pallets_bloques(grupo, cd, contador=contador)
        bat.renombrar_pallets_bat_puros(pallets_cd, cd)
        bat.asignar_cajas_bat_a_torres(pallets_cd, cajas_bat_por_cd.get(cd, []))
        for p in pallets_cd:
            p.metadata["estabilidad"] = estabilidad.calcular_estabilidad(p)
        pallets_v5.extend(pallets_cd)

    for cd, cajas in cajas_bat_por_cd.items():
        if cd not in cds_procesados and cajas:
            pallets_cd = armar_pallets_bloques(
                pd.DataFrame(columns=df_armado.columns), cd, contador=contador
            )
            bat.renombrar_pallets_bat_puros(pallets_cd, cd)
            bat.asignar_cajas_bat_a_torres(pallets_cd, cajas)
            pallets_v5.extend(pallets_cd)

    pallets_apilado = [_palletv5_a_pallet(p, info_sku) for p in pallets_v5]
    for pallet in pallets_apilado:
        soporte.clasificar_soporte_pallet(pallet)

    pallets_sin_clasificar = _construir_pallets_sin_clasificar(df_no_clasificado)
    pallets_geometria_insuficiente = _construir_pallets_geometria_insuficiente(df_geometria_insuficiente)
    todos_pallets = pallets_apilado + pallets_sin_clasificar + pallets_geometria_insuficiente

    validacion_peso.validar_pesos(todos_pallets, info_sku)

    geometria_inferida_count = int(
        auditoria_geometrica_df["Fuente_Geometria"].isin(("INFERIDA_MAESTRO", "MAESTRO_IMPOSIBLE_DEGRADADO")).sum()
    )
    demanda_unidades_error = float(df_demanda["Unidades_Exceso_Redondeo"].sum())
    bench_resultado = benchmark.calcular_kpis(
        pallets_apilado,
        demanda_unidades_error=demanda_unidades_error,
        geometria_inferida_count=geometria_inferida_count,
    )
    bench_df = benchmark.benchmark_df([bench_resultado])

    plan_picking_df = exportar.construir_plan_picking_df(todos_pallets, info_sku)
    resumen_cd_df = exportar.construir_resumen_cd_df(todos_pallets)

    return ResultadoPipeline(
        plan_picking_df=plan_picking_df,
        log_validacion_df=log_df,
        resumen_cd_df=resumen_cd_df,
        pallets=todos_pallets,
        info_sku=info_sku,
        auditoria_geometrica_df=auditoria_geometrica_df,
        benchmark_df=bench_df,
        pallets_v5=pallets_v5,
    )
