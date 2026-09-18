"""[PATCH V6.03] Validación multi-CD + gate de producción.

Corre el MISMO preprocesamiento real que usa
`pipeline_sku_bloque.ejecutar_core_sku_bloque` (validación, normalización
de demanda, reconciliación geométrica, derivados, separación de
BAT/cigarros, exclusión de SKUs sin categoría o con geometría
insuficiente) pero arma los pallets CD por CD, en SECUENCIA -no el pool de
procesos por CD que usa producción- para poder medir tiempo de baseline y
de rescue por separado, por CD, sin ambigüedad.

[sección 9] No introduce un nivel nuevo de paralelización intensiva: cada
CD sigue corriendo con `paralelo_lns=True` (su propio pool de LNS/rescue),
pero nunca hay dos CDs corriendo pools a la vez -un único nivel de
paralelización activo en cualquier momento, igual que producción con un
único CD."""
from __future__ import annotations

import time

import pandas as pd

import config
from src import bat, demanda, derivados, reconciliacion_geometrica, validacion
from src.packing_bloques import armar_pallets_bloques
from src.validacion_v5 import validar_pallet_v5

COLUMNAS_REPORTE = [
    "CD", "Demanda_Cajas", "Pallets_Objetivo", "Cajas_Baseline", "Faltantes_Baseline",
    "Rescue_Activado", "Cajas_Final", "Faltantes_Final", "Pallets_Final",
    "Tiempo_Baseline_s", "Tiempo_Rescue_s", "Tiempo_Total_s",
    "Altura_Max_cm", "Altura_Min_cm", "Overhang_Max_cm",
    "Violaciones_Overlap", "Violaciones_Soporte", "Violaciones_Altura", "Violaciones_Cajas_PH",
    "Errores_Validacion_Total", "SKUs_Faltantes_Baseline", "SKUs_Faltantes_Final",
    "Clase_Rescue", "Gate_CD",
]


def preparar_demanda_por_cd(envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame) -> pd.DataFrame:
    """Mismo preprocesamiento que `pipeline_sku_bloque.ejecutar_core_sku_
    bloque` hasta justo antes de armar pallets -devuelve el DataFrame
    "clasificado" (geometría reconciliada, BAT separado, SKUs sin
    categoría o con geometría insuficiente excluidos) listo para
    `armar_pallets_bloques`, agrupable por CD."""
    df_validado, _log_df = validacion.validar_y_limpiar(envios, maestro, uma)
    df_demanda = demanda.normalizar_demanda(df_validado)
    df_geo, _auditoria = reconciliacion_geometrica.reconciliar(df_demanda)
    df_derivado = derivados.calcular_derivados(df_geo)
    df_no_bat, _df_bat = bat.separar_bat(df_derivado)
    df_clasificado = df_no_bat[
        df_no_bat["Categoria_Normalizada"].notna() & ~df_no_bat["Requiere_Revision_Geometria"]
    ].copy()
    df_clasificado["Cajas_Remanente"] = df_clasificado["Cajas_Teoricas_Redondeadas"].astype(int)
    return df_clasificado


def _overhang_max(pallet) -> float:
    peor = 0.0
    for t in pallet.torres:
        peor = max(
            peor,
            max(0.0, -t.x), max(0.0, -t.y),
            max(0.0, t.x + t.largo - config.PALLET_LARGO),
            max(0.0, t.y + t.ancho - config.PALLET_ANCHO),
        )
    return round(peor, 3)


def _tope_cajas_por_ph(maestro: pd.DataFrame) -> dict[str, int]:
    tope = {}
    for _, fila in maestro.drop_duplicates(subset="SKU").iterrows():
        cph = fila.get("Cajas por PH")
        if pd.notna(cph) and cph > 0:
            tope[fila["SKU"]] = int(cph)
    return tope


def _violaciones_cajas_por_ph(pallets: list, tope_por_sku: dict[str, int]) -> int:
    violaciones = 0
    for p in pallets:
        por_sku: dict[str, int] = {}
        for t in p.torres:
            por_sku[t.sku] = por_sku.get(t.sku, 0) + t.cantidad
        for sku, cant in por_sku.items():
            if sku in tope_por_sku and cant > tope_por_sku[sku]:
                violaciones += 1
    return violaciones


def _clasificar_rescue(cajas_baseline: int, cajas_final: int, demanda_cajas: int) -> str:
    """[sección 7]"""
    if cajas_baseline >= demanda_cajas:
        return "A"  # no necesitó rescue
    if cajas_final >= demanda_cajas:
        return "B"  # rescue exitoso
    if cajas_final > cajas_baseline:
        return "C"  # mejora pero no completa -FAIL funcional
    return "D"  # rescue no mejora


def evaluar_cd(cd: str, df_cd: pd.DataFrame, maestro: pd.DataFrame, pallets_objetivo: int) -> dict:
    """[sección 4] Corre `armar_pallets_bloques` para UN CD (camino normal
    + rescue automático si hace falta, ya integrado desde V6.02) y arma la
    fila de reporte completa, incluyendo el gate por CD (sección 5) y la
    clasificación del comportamiento del rescue (sección 7)."""
    t0 = time.time()
    pallets = armar_pallets_bloques(df_cd, cd, pallets_objetivo=pallets_objetivo, paralelo_lns=True)
    tiempo_total = time.time() - t0

    cajas_final = sum(t.cantidad for p in pallets for t in p.torres)
    sin_colocar_final: dict[str, int] = {}
    for p in pallets:
        for sku, cant in p.metadata.get("sin_colocar", {}).items():
            sin_colocar_final[sku] = sin_colocar_final.get(sku, 0) + cant
    demanda_cajas = cajas_final + sum(sin_colocar_final.values())

    rescue_stats = None
    for p in pallets:
        rs = p.metadata.get("rescue_stats")
        if rs and rs.get("rescue_activado"):
            rescue_stats = rs
    rescue_activado = rescue_stats is not None
    cajas_baseline = rescue_stats["rescue_cajas_antes"] if rescue_activado else cajas_final
    tiempo_rescue = (rescue_stats.get("rescue_tiempo_s") or 0.0) if rescue_activado else 0.0
    tiempo_baseline = max(0.0, tiempo_total - tiempo_rescue)
    faltantes_baseline = demanda_cajas - cajas_baseline
    skus_faltantes_baseline = (
        rescue_stats.get("rescue_skus_faltantes_antes", []) if rescue_activado else sorted(sin_colocar_final)
    )

    violaciones_geo: list[str] = []
    for p in pallets:
        violaciones_geo += validar_pallet_v5(p)
    v_overlap = sum(1 for v in violaciones_geo if "se superpone con" in v)
    v_soporte = sum(1 for v in violaciones_geo if "caja flotando" in v)
    v_overhang_texto = sum(1 for v in violaciones_geo if "se sale de la base extendida" in v)
    v_altura = sum(1 for p in pallets if p.altura_final > config.ALTURA_MAX_OBSERVADA)

    tope_ph = _tope_cajas_por_ph(maestro)
    v_ph = _violaciones_cajas_por_ph(pallets, tope_ph)

    overhang_max = max((_overhang_max(p) for p in pallets), default=0.0)
    alturas = [p.altura_final for p in pallets]

    errores_total = v_overlap + v_soporte + v_overhang_texto + v_altura + v_ph

    gate_cd = (
        cajas_final == demanda_cajas
        and len(pallets) == pallets_objetivo
        and errores_total == 0
        and (max(alturas, default=0.0) <= config.ALTURA_MAX_OBSERVADA)
        and overhang_max <= config.SOBRESALIENTE_MAX_CM + 1e-6
        and v_ph == 0
    )

    return {
        "CD": cd,
        "Demanda_Cajas": demanda_cajas,
        "Pallets_Objetivo": pallets_objetivo,
        "Cajas_Baseline": cajas_baseline,
        "Faltantes_Baseline": faltantes_baseline,
        "Rescue_Activado": rescue_activado,
        "Cajas_Final": cajas_final,
        "Faltantes_Final": demanda_cajas - cajas_final,
        "Pallets_Final": len(pallets),
        "Tiempo_Baseline_s": round(tiempo_baseline, 3),
        "Tiempo_Rescue_s": round(tiempo_rescue, 3),
        "Tiempo_Total_s": round(tiempo_total, 3),
        "Altura_Max_cm": round(max(alturas, default=0.0), 2),
        "Altura_Min_cm": round(min(alturas, default=0.0), 2),
        "Overhang_Max_cm": overhang_max,
        "Violaciones_Overlap": v_overlap,
        "Violaciones_Soporte": v_soporte,
        "Violaciones_Altura": v_altura,
        "Violaciones_Cajas_PH": v_ph,
        "Errores_Validacion_Total": errores_total,
        "SKUs_Faltantes_Baseline": skus_faltantes_baseline,
        "SKUs_Faltantes_Final": sorted(sin_colocar_final),
        "Clase_Rescue": _clasificar_rescue(cajas_baseline, cajas_final, demanda_cajas),
        "Gate_CD": "PASS" if gate_cd else "FAIL",
    }


def generar_reporte_multicd(
    envios: pd.DataFrame, maestro: pd.DataFrame, uma: pd.DataFrame, pallets_objetivo_por_cd: dict[str, int],
) -> pd.DataFrame:
    """[sección 3, 4] Punto de entrada. Un CD a la vez, en el orden del
    dict -evita el pool de procesos por CD para poder medir tiempo de
    baseline/rescue por separado (ver docstring del módulo)."""
    df_clasificado = preparar_demanda_por_cd(envios, maestro, uma)
    filas = []
    for cd, pallets_objetivo in pallets_objetivo_por_cd.items():
        df_cd = df_clasificado[df_clasificado["CD"] == cd]
        filas.append(evaluar_cd(cd, df_cd, maestro, pallets_objetivo))
    return pd.DataFrame(filas, columns=COLUMNAS_REPORTE)


def evaluar_gate_agregado(reporte: pd.DataFrame) -> dict:
    """[sección 6] Gate agregado -todo o nada, no promedios."""
    demanda_total = int(reporte["Demanda_Cajas"].sum())
    colocada_total = int(reporte["Cajas_Final"].sum())
    return {
        "demanda_total": demanda_total,
        "colocada_total": colocada_total,
        "demanda_100_pct": colocada_total == demanda_total,
        "todos_pallets_n_correcto": bool((reporte["Pallets_Final"] == reporte["Pallets_Objetivo"]).all()),
        "cero_overlap": int(reporte["Violaciones_Overlap"].sum()) == 0,
        "cero_flotacion": int(reporte["Violaciones_Soporte"].sum()) == 0,
        "cero_violaciones_altura": int(reporte["Violaciones_Altura"].sum()) == 0,
        "cero_violaciones_overhang": bool((reporte["Overhang_Max_cm"] <= config.SOBRESALIENTE_MAX_CM + 1e-6).all()),
        "cero_violaciones_cajas_ph": int(reporte["Violaciones_Cajas_PH"].sum()) == 0,
        "cds_fallidos": reporte.loc[reporte["Gate_CD"] == "FAIL", "CD"].tolist(),
        "gate_agregado": bool((reporte["Gate_CD"] == "PASS").all()),
    }


def _percentiles(serie: pd.Series) -> dict:
    valores = serie.sort_values().reset_index(drop=True)
    n = len(valores)
    if n == 0:
        return {"p50": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "p50": round(float(valores.iloc[int(0.5 * (n - 1))]), 3),
        "p90": round(float(valores.iloc[int(0.9 * (n - 1))]), 3),
        "max": round(float(valores.max()), 3),
    }


def resumen_performance(reporte: pd.DataFrame) -> dict:
    """[PATCH V6.04, sección 15, 16] `Tiempo_Total_s` (TODOS los CDs) y
    `Tiempo_Rescue_s` (SOLO los CDs con `Rescue_Activado=True`) se
    reportan por separado -mezclarlos hace que un CD lento por su propio
    tamaño (ej. BK50, 128.5s, sin rescue) se lea como si fuera "tiempo de
    rescue", cuando `Rescue_Activado=False` ahí. `sample_n` viaja en el
    resultado para dejar explícito que, con pocos CDs, "% de CDs con
    rescue" es un dato a REGISTRAR, no una conclusión estadística (sección
    16: no usarlo como trigger automático de rediseño con una muestra
    chica)."""
    n = len(reporte)
    cds_con_rescue = int(reporte["Rescue_Activado"].sum()) if n else 0
    rescue_only = reporte.loc[reporte["Rescue_Activado"], "Tiempo_Rescue_s"] if n else pd.Series([], dtype=float)
    return {
        "sample_n": n,
        "tiempo_total": _percentiles(reporte["Tiempo_Total_s"]) if n else {"p50": 0.0, "p90": 0.0, "max": 0.0},
        "tiempo_rescue_only": _percentiles(rescue_only),
        "cds_con_rescue": cds_con_rescue,
        "pct_cds_con_rescue": round(100.0 * cds_con_rescue / n, 1) if n else 0.0,
    }
