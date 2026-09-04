"""[SKU_BLOQUE] Pipeline para la lógica de bloques.

[vuelta al motor exacto -ver PATCH_LOG.md] Se probó `packing_ph_fraccion.py`
(armado aproximado por fracción de PH, calibrado contra un cubicaje real)
pero el usuario, viendo el resultado real en la app, encontró camas con
hasta 21% de cobertura de soporte faltante en promedio (742 torres con
menos del 50% de apoyo real, muchas con 0%) -"eso no puede pasar". Se
volvió a `src/packing_bloques.py` (el motor geométrico exacto, MaxRects 3D,
0% de flotación verificado), ahora con 2 agregados que sí demostró
`packing_ph_fraccion.py` que ayudan a recuperar densidad sin sacrificar la
garantía exacta: orientación flexible (Comestibles/Aseo/Cigarros pueden
acostarse, NABs siempre de pie) y el tope real de `Cajas por PH` por
pallet. `packing_ph_fraccion.py` queda en el repo, probado, pero no es el
que usa el pipeline.

Reutiliza VAL/DEM/GEO/DER/SPLIT/PESO/EXP tal cual el resto de los motores
-esa infraestructura no depende de la estrategia de armado."""
import pandas as pd

import config
from models import Pallet, PalletLinea, ResultadoPipeline
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


def _palletv5_a_pallet(pv5, info_sku: dict) -> Pallet:
    """Adapta un PalletV5 (torres) a un Pallet (mismo modelo que usan
    soporte.py/exportar.py/benchmark.py) para no duplicar esa
    infraestructura. `camas` queda vacío a propósito -soporte.py no rompe
    con eso (ver docstring de `clasificar_soporte_pallet`).

    Las torres con sku `bat.BAT_SKU_MARCADOR` no son un SKU real -son la
    caja física de consolidación de Cigarros/vapes- así que no aportan una
    `PalletLinea` directamente. Pero el CONTENIDO real de esa caja sí son
    SKUs reales de Cigarros (`CajaBAT.cantidades_cajas`), y tienen que
    aparecer en el picking igual que cualquier otro SKU -sin este paso, un
    pallet 100% BAT (o cualquier pallet con Cigarros) desaparecería del
    `Plan_Picking`: nadie sabría qué SKUs de Cigarros picking real
    contiene. Se agregan acá con el mismo criterio (cantidades reales
    fraccionarias, no la caja física entera)."""
    cantidades: dict[str, float] = {}
    for torre in pv5.torres:
        if torre.sku == bat.BAT_SKU_MARCADOR:
            continue
        cantidades[torre.sku] = cantidades.get(torre.sku, 0) + torre.cantidad
    for caja in pv5.cajas_bat:
        for sku, qty in caja.cantidades_cajas.items():
            cantidades[sku] = cantidades.get(sku, 0) + qty

    lineas = []
    for sku, qty in cantidades.items():
        meta = info_sku.get(sku, {})
        lineas.append(
            PalletLinea(
                sku=sku,
                descripcion=meta.get("descripcion", ""),
                categoria=meta.get("categoria", ""),
                nivel_categoria=meta.get("nivel_categoria"),
                cajas_demanda_oficial=qty,
                cajas_extra_consolidacion=0,
                peso_no_validable=bool(meta.get("peso_no_validable", False)),
            )
        )

    pallet = Pallet(
        id=pv5.id, cd=pv5.cd, tipo="Columnar",
        altura_final=pv5.altura_final, peso_estimado=pv5.peso_estimado,
        estado=config.estado_pallet_por_altura(pv5.altura_final),
    )
    pallet.lineas = lineas
    pallet.cajas_bat = list(pv5.cajas_bat)
    pallet.es_host_bat = bool(pv5.metadata.get("es_host_bat", False)) or bool(pv5.cajas_bat)
    return pallet


_COLUMNAS_NOMBRE_CD = ["Nombre CD", "NOMBRE BK", "Nombre_CD", "Nombre CD Destino"]


def _construir_nombres_cd(envios: pd.DataFrame) -> dict[str, str]:
    """[feedback picking] "Falta nombre de CD" -si `Envios_Julio` trae una
    columna reconocible con el nombre legible del CD (ej. "CD Cañete" para
    "BK31"), se usa para la columna `Nombre_CD` del plan de picking. Si no
    existe ninguna de las variantes conocidas, devuelve vacío -no se
    inventa un nombre que no está en el dato de entrada."""
    columna = next((c for c in _COLUMNAS_NOMBRE_CD if c in envios.columns), None)
    if columna is None:
        return {}
    pares = envios[["CD", columna]].dropna().drop_duplicates(subset="CD")
    return dict(zip(pares["CD"], pares[columna]))


def _demanda_excluida_geometria(envios: pd.DataFrame, maestro: pd.DataFrame, log_df: pd.DataFrame) -> pd.DataFrame:
    """[bug real, corregido acá] La regla V4 de validacion.py (dimensión de
    caja imposible para el pallet, en ninguna orientación) excluye la fila
    de la demanda ANTES de que llegue a reconciliacion_geometrica -por
    diseño, ver test_dimension_imposible_se_excluye: esa demanda nunca debe
    competir por espacio en el motor de armado. Pero antes se perdía del
    todo salvo por una línea en `Log_Validacion` -es tan "no colocada" como
    la que rechaza `armar_pallets_bloques`, así que se reconstruye acá
    (CD/SKU/Descripcion/Categoria/Cajas_No_Colocadas) para sumarla a
    `cajas_no_colocadas_df` en vez de perderla."""
    excluidas = log_df[log_df["regla"] == "V4"][["cd", "sku"]].drop_duplicates()
    columnas = ["CD", "SKU", "Descripcion", "Categoria", "Cajas_No_Colocadas"]
    if excluidas.empty:
        return pd.DataFrame(columns=columnas)

    envios = envios.copy()
    envios["SKU"] = envios["SKU"].astype(str).str.strip()
    demanda = envios.groupby(["CD", "SKU"], as_index=False).agg(
        {"Descripción": "first", "Cajas Teóricas": "sum"}
    )

    maestro = maestro.copy()
    maestro["SKU"] = maestro["SKU"].astype(str).str.strip()
    categorias = maestro[["SKU", "Categoría"]].drop_duplicates(subset="SKU")

    demanda = demanda.merge(categorias, on="SKU", how="left")
    demanda = demanda.merge(excluidas.rename(columns={"cd": "CD", "sku": "SKU"}), on=["CD", "SKU"], how="inner")
    return demanda.rename(
        columns={"Descripción": "Descripcion", "Categoría": "Categoria", "Cajas Teóricas": "Cajas_No_Colocadas"}
    )[columnas]


def ejecutar_core_sku_bloque(
    envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame,
    pallets_objetivo_por_cd: dict[str, int] | None = None,
) -> ResultadoPipeline:
    nombres_cd = _construir_nombres_cd(envios)
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
    pallets_objetivo_por_cd = pallets_objetivo_por_cd or {}
    for cd, grupo in df_armado.groupby("CD"):
        cds_procesados.add(cd)
        pallets_cd = armar_pallets_bloques(
            grupo, cd, contador=contador, pallets_objetivo=pallets_objetivo_por_cd.get(cd)
        )
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

    plan_picking_df = exportar.construir_plan_picking_df(todos_pallets, info_sku, nombres_cd)
    resumen_cd_df = exportar.construir_resumen_cd_df(todos_pallets)
    demanda_excluida_geometria_df = _demanda_excluida_geometria(envios, maestro, log_df)
    cajas_no_colocadas_df = exportar.construir_cajas_no_colocadas_df(
        pallets_v5, info_sku, demanda_excluida_geometria_df
    )

    return ResultadoPipeline(
        plan_picking_df=plan_picking_df,
        log_validacion_df=log_df,
        resumen_cd_df=resumen_cd_df,
        pallets=todos_pallets,
        info_sku=info_sku,
        auditoria_geometrica_df=auditoria_geometrica_df,
        benchmark_df=bench_df,
        pallets_v5=pallets_v5,
        cajas_no_colocadas_df=cajas_no_colocadas_df,
    )
