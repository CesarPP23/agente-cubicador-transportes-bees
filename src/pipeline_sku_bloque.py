"""[SKU_BLOQUE] Pipeline para la lógica de bloques.

[PH_FRACCION -ver PATCH_LOG.md] El motor de armado activo es
`src/packing_ph_fraccion.py::armar_pallets_ph_fraccion` (importado acá
como `armar_pallets_bloques` para no tocar el resto de este archivo) -
calibrado contra un cubicaje real armado a mano, arma por fracción de PH
en vez de geometría exacta caja por caja. `src/packing_bloques.py` (el
motor geométrico exacto, MaxRects 3D con verificación caja por caja) sigue
en el repo y probado, pero ya no es el que usa el pipeline -se puede volver
a él cambiando el import de acá si hace falta la verificación exacta en
vez de la densidad real.

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
from src.packing_ph_fraccion import armar_pallets_ph_fraccion as armar_pallets_bloques
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


def ejecutar_core_sku_bloque(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> ResultadoPipeline:
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

    plan_picking_df = exportar.construir_plan_picking_df(todos_pallets, info_sku, nombres_cd)
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
