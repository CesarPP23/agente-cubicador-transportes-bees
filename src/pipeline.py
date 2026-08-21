import pandas as pd

import config
from models import Pallet, PalletLinea, ResultadoPipeline
from src import (
    apilado_3d,
    bat,
    benchmark,
    demanda,
    derivados,
    exportar,
    packing_2d,
    pallets_homogeneos,
    reconciliacion_geometrica,
    soporte,
    validacion,
    validacion_peso,
)


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
            # [V3 / sección 20] Trazabilidad de geometría, para la hoja de
            # auditoría y las columnas Fuente_Geometria/*_Efectivo del output.
            "fuente_geometria": fila.get("Fuente_Geometria"),
            "largo_efectivo": fila.get("Largo_Efectivo"),
            "ancho_efectivo": fila.get("Ancho_Efectivo"),
            "alto_efectivo": fila.get("Alto_Efectivo"),
            "geometria_inferida": bool(fila.get("Geometria_Inferida", False)),
            "unidades_por_caja": fila.get("Unidades_por_Caja", fila.get("Unidades por caja")),
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


def _construir_pallets_geometria_insuficiente(df_insuficiente: pd.DataFrame) -> list[Pallet]:
    """[V3 / sección 5.3.D, 17] SKUs sin geometría utilizable (sin Alto de
    caja, o sin Largo/Ancho y sin techo del Maestro para inferir): no se
    pueden empacar de forma segura, quedan como REQUIERE REVISIÓN en vez de
    forzar una geometría inventada (invariante 17: "todo pallet inviable
    queda como REQUIERE REVISIÓN")."""
    pallets = []
    for cd, grupo in df_insuficiente.groupby("CD"):
        lineas = [
            PalletLinea(
                sku=fila["SKU"],
                descripcion=fila["Descripción"],
                categoria=fila["Categoria_Normalizada"],
                nivel_categoria=fila["Nivel_Categoria"],
                cajas_demanda_oficial=int(fila["Cajas_Teoricas_Redondeadas"]),
                cajas_extra_consolidacion=0,
                peso_no_validable=bool(fila["Peso_No_Validable"]),
            )
            for _, fila in grupo.iterrows()
        ]
        pallet = Pallet(
            id=f"REQUIERE-REVISION-{cd}",
            cd=cd,
            tipo="Requiere Revisión",
            estado=config.ESTADO_DATO_INSUFICIENTE,
        )
        pallet.lineas = lineas
        pallets.append(pallet)
    return pallets


def ejecutar_pipeline(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
    """[V5-P1, V-AUTO] Despacha según config.PACKER_VERSION -"V4" (core de
    camas, default de producción), "V5" (core columnar/torres, ver
    Parches/v5/PATCH_LOG.md), "AUTO" (corre ambos y se queda con el mejor
    CD por CD, ver src/pipeline_auto.py), "AUTO_CONSOLIDADO" (igual que
    AUTO, pero concentrando cada SKU en el menor número de pallets posible
    dentro de su CD antes de comparar, ver src/pipeline_auto_consolidado.py
    y src/consolidacion_sku.py) o "SKU_CONSOLIDADO" (escenario de
    referencia momentáneo: un único pase, sin multi-start, que prioriza
    NUNCA repartir un SKU en más pallets de los necesarios -ver
    src/pipeline_sku_consolidado.py, PATCH_LOG.md). Cambiar el flag es el
    único punto de rollback: nunca hace falta tocar código para volver a V4."""
    if config.PACKER_VERSION == "SKU_BLOQUE":
        from src import pipeline_sku_bloque

        return pipeline_sku_bloque.ejecutar_core_sku_bloque(envios, maestro, uma)
    if config.PACKER_VERSION == "SKU_CONSOLIDADO":
        from src import pipeline_sku_consolidado

        return pipeline_sku_consolidado.ejecutar_core_sku_consolidado(envios, maestro, uma)
    if config.PACKER_VERSION == "AUTO_CONSOLIDADO":
        from src import pipeline_auto_consolidado

        return pipeline_auto_consolidado.ejecutar_core_auto_consolidado(envios, maestro, uma)
    if config.PACKER_VERSION == "AUTO":
        from src import pipeline_auto

        return pipeline_auto.ejecutar_core_auto(envios, maestro, uma)
    if config.PACKER_VERSION == "V5":
        from src import pipeline_v5

        return pipeline_v5.ejecutar_core_v5(envios, maestro, uma)
    return ejecutar_core_v4(envios, maestro, uma)


def ejecutar_core_v4(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
    """[V5-P1] Core V4 (camas) -idéntico al `ejecutar_pipeline` de antes de
    V5, solo renombrado para poder convivir con `pipeline_v5.ejecutar_core_v5`
    detrás del flag `config.PACKER_VERSION`."""
    # VAL
    df_validado, log_df = validacion.validar_y_limpiar(envios, maestro, uma)

    # DEM -- [V3 sección 8] demanda a nivel de unidades, política de redondeo
    # explícita por categoría.
    df_demanda = demanda.normalizar_demanda(df_validado)

    # GEO -- [V3 sección 5] reconciliación geométrica Maestro<->UMA. Se corre
    # sobre TODA la demanda (BAT incluido) -no porque BAT necesite geometría
    # (usa una caja fija, ver bat.py), sino para que info_sku (peso, nivel,
    # categoría) quede completo para TODOS los SKUs antes de separar BAT; si
    # se reconciliara después del split, los SKUs de Cigarros nunca pasarían
    # por derivados.calcular_derivados y bat._colocar_bat fallaría al buscar
    # su peso/categoría en info_sku.
    df_geo, auditoria_geometrica_df = reconciliacion_geometrica.reconciliar(df_demanda)
    df_derivado = derivados.calcular_derivados(df_geo)

    info_sku = _construir_info_sku(df_derivado)

    # SPLIT -- [V3 sección 9.1] BAT (Cigarros/vapes) sale del cubicaje normal,
    # ya con info_sku resuelto.
    df_no_bat, df_bat = bat.separar_bat(df_derivado)

    df_clasificado = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & ~df_no_bat["Requiere_Revision_Geometria"]
    ].copy()
    df_no_clasificado = df_no_bat[df_no_bat["Categoria_Normalizada"].isna()].copy()
    df_geometria_insuficiente = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & df_no_bat["Requiere_Revision_Geometria"]
    ].copy()

    # HOM -> P2D -> P3D
    remanente_df, pallets_hom = pallets_homogeneos.armar_pallets_homogeneos(df_clasificado)
    camas_por_cd = packing_2d.generar_camas(remanente_df)
    pallets_apilado = apilado_3d.armar_pallets(camas_por_cd, info_sku, pallets_semilla=pallets_hom)

    # BATPOOL -- [V3 sección 9.2] cajas BAT consolidadas por CD, en unidades.
    cajas_bat_por_cd = bat.consolidar_bat_por_cd(df_bat)

    # HOST -- [V3 sección 9.3, 11.5] host dinámico DESPUÉS de armar todo lo
    # demás, sin reserva de altura anticipada.
    bat.asignar_hosts_bat(pallets_apilado, cajas_bat_por_cd, info_sku)

    # SOP -- [V3 sección 14, 15] portante/terminal + support ratio, KPI/alerta.
    for pallet in pallets_apilado:
        soporte.clasificar_soporte_pallet(pallet)

    pallets_sin_clasificar = _construir_pallets_sin_clasificar(df_no_clasificado)
    pallets_geometria_insuficiente = _construir_pallets_geometria_insuficiente(df_geometria_insuficiente)

    todos_pallets = pallets_apilado + pallets_sin_clasificar + pallets_geometria_insuficiente

    # PESO
    validacion_peso.validar_pesos(todos_pallets, info_sku)

    # BENCH -- [V5-P0] El benchmark real de referencia (42 pallets) excluye
    # las filas PALET=0 del dato HISTÓRICO -cigarros/vapes que en esa
    # operación terminaron encima de pallets ya existentes, no un pallet
    # físico adicional (sección 8.3 de DOCUMENTACION_LOGICA_V5.md). Pero eso
    # es una propiedad del DATO REAL, no una licencia para que el MODELO
    # excluya sus propios PH-BAT-* dedicados del conteo: si el modelo abre
    # uno, es un pallet físico más que Transporte tiene que mover, y así debe
    # contarlo (invariante 11 V5: "Pallet BAT dedicado cuenta como pallet
    # físico"). El benchmark ahora se calcula sobre TODOS los pallets
    # armados, sin excepciones.
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

    # EXP
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
    )


def ejecutar_desde_archivo(ruta_o_buffer) -> ResultadoPipeline:
    envios, maestro, uma = validacion.cargar_hojas(ruta_o_buffer)
    return ejecutar_pipeline(envios, maestro, uma)
