"""[SKU_CONSOLIDADO] Escenario de comparación explícito -no es V4 (no usa
camas/clustering por altura) ni V5/AUTO (no corre multi-start, no compara
nada contra V4): un único pase determinístico cuya regla principal es "un
SKU que va al mismo CD nunca se reparte en más pallets de los que
necesita".

Instrucción del usuario: correrlo momentáneamente en local, SOLO para bajar
el Excel y confirmar que este no es el camino que quiere tomar -es
deliberadamente un escenario de referencia, no una propuesta.

Construcción:
1. Pallets 100% homogéneos: `floor(demanda / Cajas_por_PH)` por SKU+CD -la
   MISMA regla exacta que ya usa `pallets_homogeneos.py` (no una versión
   nueva, es literalmente la definición de "SKU consolidado sin fragmentar").
2. El remanente (lo que no llega a llenar un pallet homogéneo) entra al
   packer columnar UNA sola vez, sin multi-start, con `concentrar_sku=True`
   -nunca abre un pallet nuevo para un SKU si el último donde se colocó
   todavía tiene lugar (ver packing_columnar.py, "V-AUTO-CONSOLIDADO-DURO").
"""
import pandas as pd

import config
from models import Pallet, ResultadoPipeline
from src import (
    bat,
    benchmark,
    demanda,
    derivados,
    exportar,
    pallets_homogeneos,
    reconciliacion_geometrica,
    soporte,
    validacion,
    validacion_peso,
)
from src.packing_columnar import armar_pallets_columnar
from src.pipeline import (
    _construir_info_sku,
    _construir_pallets_geometria_insuficiente,
    _construir_pallets_sin_clasificar,
)
from src.pipeline_v5 import _palletv5_a_pallet


def ejecutar_core_sku_consolidado(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
    # VAL / DEM / GEO / DER -- idénticas al resto de los motores.
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

    # 1) Pallets 100% homogéneos -misma regla que pallets_homogeneos.py.
    remanente_df, pallets_hom = pallets_homogeneos.armar_pallets_homogeneos(df_clasificado)

    # 2) Remanente -> packer columnar, un único pase, concentrar_sku=True.
    #    BAT entra como pseudo-fila de demanda (mismo mecanismo que V5-BAT-
    #    integrado -no es "usar V5", es la única forma ya construida de que
    #    BAT compita por espacio en vez de perderse en un pase aparte).
    #    OJO: `remanente_df["Cajas_Remanente"]` YA viene con el descuento de
    #    lo que se llevaron los pallets homogéneos (armar_pallets_homogeneos
    #    lo resta antes de devolver el remanente) -pisarlo con
    #    Cajas_Teoricas_Redondeadas otra vez duplicaría esa demanda.
    remanente_df = remanente_df.copy()
    cajas_bat_por_cd = bat.consolidar_bat_por_cd(df_bat)
    df_bat_pseudo = bat.construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku)
    df_armado = pd.concat([remanente_df, df_bat_pseudo], ignore_index=True, sort=False)

    pallets_v5_remanente: list = []
    contador = [0]
    for cd, grupo in df_armado.groupby("CD"):
        pallets_cd = armar_pallets_columnar(grupo, cd, contador=contador, concentrar_sku=True)
        bat.renombrar_pallets_bat_puros(pallets_cd, cd)
        bat.asignar_cajas_bat_a_torres(pallets_cd, cajas_bat_por_cd.get(cd, []))
        pallets_v5_remanente.extend(pallets_cd)

    # CDs con demanda BAT pero SIN ninguna otra demanda clasificada -no
    # pasan por el groupby de arriba (nunca aparecen en df_armado si además
    # no tenían remanente), su BAT igual tiene que salir en algún pallet.
    cds_ya_procesados = {p.cd for p in pallets_v5_remanente} | {p.cd for p in pallets_hom}
    for cd, cajas in cajas_bat_por_cd.items():
        if cd not in cds_ya_procesados and cajas:
            pallets_cd = armar_pallets_columnar(
                pd.DataFrame(columns=remanente_df.columns), cd, contador=contador, concentrar_sku=True
            )
            bat.renombrar_pallets_bat_puros(pallets_cd, cd)
            bat.asignar_cajas_bat_a_torres(pallets_cd, cajas)
            pallets_v5_remanente.extend(pallets_cd)

    pallets_remanente_adaptados = [_palletv5_a_pallet(p, info_sku) for p in pallets_v5_remanente]

    pallets_apilado = pallets_hom + pallets_remanente_adaptados
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
        pallets_v5=pallets_v5_remanente,
    )
