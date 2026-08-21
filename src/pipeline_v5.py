"""[V5] Pipeline V5 (packer columnar/torres).

Reutiliza VAL/DEM/GEO/DER/SPLIT/PESO/EXP de V4 tal cual -esa infraestructura
no depende de si el core de armado es por camas o por torres, reescribirla
sería puro riesgo sin beneficio. Lo que SÍ cambia, patch a patch, es el core
de armado (HOM/P2D/P3D en V4 -> TOR/MS/RES/BAT/RES2 en V5, ver
DOCUMENTACION_TECNICA_V5.md sección 13).

Estado por patch:
- V5-P1: el core de armado delegaba en las funciones V4 -el pipeline V5
  EXISTÍA y corría de punta a punta, pero el resultado era idéntico a V4.
- V5-P5: el core de armado pasa a `packing_columnar.armar_pallets_columnar`
  (torres, sin camas ni clustering por altura). BAT (`bat.py`), soporte
  (`soporte.py`), export (`exportar.py`) y benchmark (`benchmark.py`) siguen
  operando sobre el modelo `Pallet` (V4) -`_palletv5_a_pallet` adapta cada
  `PalletV5` a un `Pallet` equivalente (mismas cajas, mismo peso/altura, sin
  camas) para no duplicar esa infraestructura antes de que P9/P13 la
  reemplacen con versiones nativas V5.
- V5-P7: por CD, se corren las 7 estrategias de `multistart.py` (+ N semillas
  para RANDOM) y se usa la de mejor score lexicográfico -ya no un único pase
  fijo.
- V5-BAT-integrado: BAT deja de ser una pasada aparte DESPUÉS de multi-start
  +residual search -entra como una fila de demanda más (`bat.
  construir_filas_bat_pseudo_sku`) en el MISMO `df_cd` que evalúan las 7
  estrategias/semillas, así que una ordenación que deja a BAT sin lugar
  (forzando un pallet dedicado de más) puntúa peor en el propio score de
  multi-start y pierde -sin criterio nuevo, el conteo de pallets ya es lo
  primero que compara. Ver bat.py, sección "BAT integrado", y PATCH_LOG.md.
"""
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
    multistart,
    reconciliacion_geometrica,
    residual_search,
    soporte,
    validacion,
    validacion_peso,
)
from src.pipeline import (
    _construir_info_sku,
    _construir_pallets_geometria_insuficiente,
    _construir_pallets_sin_clasificar,
)


def _palletv5_a_pallet(pv5, info_sku: dict) -> Pallet:
    """[V5-P5/P9] Adapta un PalletV5 (torres) a un Pallet (V4, camas) para
    poder reusar soporte.py/exportar.py/benchmark.py sin duplicarlos.
    `camas` queda vacío a propósito -soporte.py no rompe con eso (ver
    docstring de `clasificar_soporte_pallet`).

    Las torres con sku `bat.BAT_SKU_MARCADOR` (colocadas por el mismo
    `armar_pallets_columnar` que todo lo demás, ver V5-BAT-integrado en
    bat.py) no son un SKU real -son la caja física de consolidación- así
    que no aportan una `PalletLinea` directamente. Pero el CONTENIDO real de
    esa caja sí son SKUs reales de Cigarros (`CajaBAT.cantidades_cajas`), y
    V4 SIEMPRE los mostraba como línea de picking (`bat._colocar_bat` llama
    `_construir_lineas` sobre la cama de Cigarros) -sin este paso, un pallet
    100% BAT (o cualquier pallet con Cigarros) desaparecía del
    `Plan_Picking` bajo V5: nadie sabría qué SKUs de Cigarros picking real
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


def ejecutar_core_v5(
    envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame, concentrar_sku: bool = False
) -> ResultadoPipeline:
    """`concentrar_sku` (default False, sin cambio de comportamiento): se
    pasa tal cual a `multistart.generar_soluciones_cd` en cada CD -ver
    packing_columnar.armar_pallets_columnar y PATCH_LOG.md, sección
    "V-AUTO-CONSOLIDADO-DURO"."""
    # VAL / DEM / GEO / DER -- idénticos a V4, ver docstring del módulo.
    df_validado, log_df = validacion.validar_y_limpiar(envios, maestro, uma)
    df_demanda = demanda.normalizar_demanda(df_validado)
    df_geo, auditoria_geometrica_df = reconciliacion_geometrica.reconciliar(df_demanda)
    df_derivado = derivados.calcular_derivados(df_geo)
    info_sku = _construir_info_sku(df_derivado)

    # SPLIT -- BAT sale del cubicaje normal, igual que V4.
    df_no_bat, df_bat = bat.separar_bat(df_derivado)
    df_clasificado = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & ~df_no_bat["Requiere_Revision_Geometria"]
    ].copy()
    df_no_clasificado = df_no_bat[df_no_bat["Categoria_Normalizada"].isna()].copy()
    df_geometria_insuficiente = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & df_no_bat["Requiere_Revision_Geometria"]
    ].copy()

    # --- CORE DE ARMADO (V5-P5/P7: columnar + multi-start) ----------------
    # [V5-P6] PH_PREBUILD=False por defecto: TODA la demanda entra al packer
    # columnar de una, sin extraer pallets homogéneos de antemano -un
    # resultado homogéneo puede seguir apareciendo, pero como consecuencia
    # del packer, no como decisión previa (DOCUMENTACION_LOGICA_V5.md 13).
    df_clasificado = df_clasificado.copy()
    df_clasificado["Cajas_Remanente"] = df_clasificado["Cajas_Teoricas_Redondeadas"].astype(int)

    # [V5-BAT-integrado] BAT entra como una fila de demanda más, en el MISMO
    # `df_cd` que evalúan las 7 estrategias/semillas de multi-start -no una
    # pasada aparte después (ver docstring del módulo y bat.py). Un CD con
    # demanda BAT pero SIN ninguna otra demanda clasificada aparece igual acá
    # (con solo la fila BAT), así que no hace falta ningún manejo aparte para
    # ese caso -antes sí lo necesitaba, porque BAT nunca pasaba por este loop.
    cajas_bat_por_cd = bat.consolidar_bat_por_cd(df_bat)
    df_bat_pseudo = bat.construir_filas_bat_pseudo_sku(cajas_bat_por_cd, info_sku)
    df_armado = pd.concat([df_clasificado, df_bat_pseudo], ignore_index=True, sort=False)

    pallets_v5: list = []
    for cd, grupo in df_armado.groupby("CD"):
        soluciones = multistart.generar_soluciones_cd(grupo, cd, info_sku, concentrar_sku=concentrar_sku)
        mejor = multistart.mejor_solucion(soluciones)
        # [V5-P13] Estrategia/semilla ganadora, para auditoría (Torres):
        # se guarda ANTES de residual_search -esa etapa muta torres/altura
        # de los mismos objetos `PalletV5`, nunca reemplaza la lista
        # completa, así que `metadata` sobrevive intacta.
        for p in mejor.pallets:
            p.metadata["estrategia"] = mejor.estrategia
            p.metadata["seed"] = mejor.seed
        # [V5-P8] Residual elimination -BAT ya está adentro de `mejor.pallets`
        # (se armó junto con todo lo demás), así que esta pasada ya lo ve.
        pallets_cd = residual_search.eliminar_residuales(mejor.pallets)
        # [V5-BAT-integrado] Bookkeeping: un pallet 100% BAT se renombra al
        # esquema PV5-BAT-* que benchmark.py/exportar.py reconocen; las
        # torres BAT (cantidad colocada, sin CajaBAT real todavía) se
        # mapean a los objetos CajaBAT reales del CD (fungibles entre sí).
        bat.renombrar_pallets_bat_puros(pallets_cd, cd)
        bat.asignar_cajas_bat_a_torres(pallets_cd, cajas_bat_por_cd.get(cd, []))
        # [V5-P11] Estabilidad: informativo, no bloquea nada -se calcula y se
        # guarda en metadata para exportar (P13), nunca cambia el armado.
        for p in pallets_cd:
            p.metadata["estabilidad"] = estabilidad.calcular_estabilidad(p)
        pallets_v5.extend(pallets_cd)
    # --- fin CORE DE ARMADO ----------------------------------------------

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
